mod commands;
mod ipc;
mod lifecycle;
mod platform;
mod windows;

use ipc::BridgeError;
use lifecycle::{options::LaunchOptions, Service};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::Manager;
use tauri_plugin_global_shortcut::GlobalShortcutExt;

pub struct DesktopState {
    service: Mutex<Result<Arc<Service>, BridgeError>>,
    events: lifecycle::EventSink,
    presentation: windows::SharedPresentation,
    hotkeys: Mutex<Vec<platform::hotkeys::Binding>>,
    settings_lock: Mutex<()>,
    ui_ready: AtomicBool,
    options: LaunchOptions,
    input: Mutex<Option<platform::hotkeys::InputSender>>,
    input_overflow: Arc<AtomicBool>,
    input_thread: Mutex<Option<std::thread::JoinHandle<()>>>,
}

impl DesktopState {
    pub(crate) fn service(&self) -> Result<Arc<Service>, BridgeError> {
        self.service.lock().expect("service owner").clone()
    }
}

pub(crate) fn retry_service(app: &tauri::AppHandle) -> Result<Value, BridgeError> {
    let state = app.state::<DesktopState>();
    let _guard = state.settings_lock.lock().expect("settings transaction");
    if let Ok(service) = state.service() {
        if service.connected() {
            return service.request("control-center", "retry_runtime", json!({}));
        }
        service.stop();
    }
    windows::reset(&state.presentation);
    let service = lifecycle::service_command(Some(app), &state.options)
        .and_then(|command| Service::launch(command, state.events.clone()))
        .map(Arc::new);
    *state.service.lock().expect("service owner") = service;
    start_service(app, &state.options);
    state
        .service()?
        .request("control-center", "get_state", json!({}))
}

pub fn run() {
    let options = match LaunchOptions::parse(std::env::args().skip(1)) {
        Ok(options) => options,
        Err(error) => {
            eprintln!("{}", error.message);
            std::process::exit(2);
        }
    };
    if options
        .self_check
        .as_deref()
        .is_some_and(|mode| mode != "ui")
    {
        let result = (|| -> Result<Value, BridgeError> {
            let command = lifecycle::service_command(None, &options)?;
            let service = Service::launch(command, Arc::new(|_, _, _| {}))?;
            validate_handshake(service.request("host", "service.hello", json!({}))?)?;
            service.request(
                "host",
                "self_check",
                json!({"mode":options.self_check,"image":options.self_check_image}),
            )
        })();
        match result {
            Ok(result) => {
                println!("{result}");
                std::process::exit(if result["ok"].as_bool() == Some(true) {
                    0
                } else {
                    2
                });
            }
            Err(error) => {
                println!(
                    "{}",
                    json!({"ok":false,"mode":options.self_check,"error":error.code,"message":error.message})
                );
                std::process::exit(2);
            }
        }
    }
    let setup_options = options.clone();
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(platform::hotkeys::handler)
                .build(),
        )
        .invoke_handler(tauri::generate_handler![commands::desktop_request])
        .setup(move |app| {
            platform::configure_application();
            let presentation = Arc::new(Mutex::new(windows::Presentation::default()));
            let events_app = app.handle().clone();
            let events_presentation = presentation.clone();
            let trace = setup_options.trace;
            let lab_observer = cfg!(debug_assertions)
                && std::env::var("HANLY_DESKTOP_SERVICE_MODULE").as_deref()
                    == Ok("lab.service_observer");
            let events = Arc::new(move |sequence, event: &str, payload: Value| {
                if event == "lab_capture" {
                    if lab_observer {
                        println!("{}", json!({"type":"lab_capture","payload":payload}));
                    }
                } else if event == "native_action" {
                    if payload["action"] == "restart_required" {
                        events_app.exit(0);
                    }
                } else if event == "trace" {
                    if trace {
                        println!("{}", json!({"type":"trace","payload":payload}));
                    }
                } else {
                    windows::event(&events_app, &events_presentation, sequence, event, payload);
                    if event == "state" {
                        update_tray(&events_app);
                    }
                }
            });
            let service = lifecycle::service_command(Some(app.handle()), &setup_options)
                .and_then(|command| Service::launch(command, events.clone()))
                .map(Arc::new);
            app.manage(DesktopState {
                service: Mutex::new(service),
                events,
                presentation,
                hotkeys: Mutex::new(Vec::new()),
                settings_lock: Mutex::new(()),
                ui_ready: AtomicBool::new(false),
                options: setup_options.clone(),
                input: Mutex::new(None),
                input_overflow: Arc::new(AtomicBool::new(false)),
                input_thread: Mutex::new(None),
            });
            let headless = setup_options
                .self_check
                .as_deref()
                .is_some_and(|mode| mode != "ui");
            if !headless {
                windows::create(app.handle())?;
                install_tray(app.handle())?;
            }
            platform::hotkeys::start_input(app.handle());
            let signal_app = app.handle().clone();
            ctrlc::set_handler(move || signal_app.exit(0))?;
            let handle = app.handle().clone();
            let startup_options = setup_options.clone();
            tauri::async_runtime::spawn_blocking(move || start_service(&handle, &startup_options));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Hanly desktop could not initialize");
    app.run(|app, event| match event {
        tauri::RunEvent::Exit => {
            let state = app.state::<DesktopState>();
            let _ = app.global_shortcut().unregister_all();
            state.input.lock().expect("input sender").take();
            if let Ok(service) = app.state::<DesktopState>().service() {
                service.stop();
            }
            if let Some(worker) = state.input_thread.lock().expect("input worker").take() {
                let _ = worker.join();
            };
        }
        #[cfg(target_os = "macos")]
        tauri::RunEvent::Reopen { .. } => windows::show_control_center(app),
        _ => {}
    });
}

fn start_service(app: &tauri::AppHandle, options: &LaunchOptions) {
    let state = app.state::<DesktopState>();
    let service = state.service();
    let result = service
        .as_ref()
        .map_err(Clone::clone)
        .and_then(|service| service.request("host", "service.hello", json!({})))
        .and_then(validate_handshake);
    if let Err(error) = result {
        windows::event(
            app,
            &state.presentation,
            0,
            "service_status",
            json!({"state":"failed","code":error.code,"message":error.message}),
        );
        if options.self_check.is_some() {
            println!("{}", json!({"ok":false,"error":error.code}));
            app.exit(2);
        }
        return;
    }
    let service = service.as_ref().expect("service handshake validated");
    if let Some(mode) = &options.self_check {
        run_self_check(app, service, mode, options);
        return;
    }
    // Runtime composition may finish quickly, so deliver the native capability before reading state.
    if let Err(error) = send_context(app, service) {
        windows::event(
            app,
            &state.presentation,
            0,
            "service_status",
            json!({"state":"failed","code":error.code,"message":error.message}),
        );
        return;
    }
    let mut registration_error = None;
    let initial = service.request("control-center", "get_state", json!({}));
    if let Ok(snapshot) = initial {
        match platform::hotkeys::bindings(&snapshot["config"]) {
            Ok(bindings) => {
                registration_error = platform::hotkeys::replace(app, bindings).err();
            }
            Err(error) => {
                registration_error = Some(error);
            }
        }
        let _ = send_context(app, service);
        windows::event(app, &state.presentation, 0, "state", snapshot);
    }
    if options.update_ready.is_some() || options.update_challenge.is_some() {
        let deadline = Instant::now() + Duration::from_secs(15);
        while !state.ui_ready.load(Ordering::Acquire) {
            if Instant::now() >= deadline {
                return;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
    }
    for (field, path) in [
        ("legacy_ready_path", &options.update_ready),
        ("challenge_path", &options.update_challenge),
    ] {
        if let Some(path) = path {
            if let Err(error) = service.request("host", "update.acknowledge", json!({(field):path}))
            {
                windows::event(
                    app,
                    &state.presentation,
                    0,
                    "service_status",
                    json!({"state":"failed","code":error.code,"message":error.message}),
                );
            }
        }
    }
    let status = match registration_error {
        Some(error) => json!({"state":"failed","code":error.code,"message":error.message}),
        None => json!({"state":"ready"}),
    };
    windows::event(app, &state.presentation, 0, "service_status", status);
}

fn run_self_check(app: &tauri::AppHandle, service: &Service, mode: &str, options: &LaunchOptions) {
    let result = (|| -> Result<Value, BridgeError> {
        if mode != "ui" {
            return service.request(
                "host",
                "self_check",
                json!({"mode":mode,"image":options.self_check_image}),
            );
        }
        let deadline = Instant::now() + Duration::from_secs(60);
        while !app.state::<DesktopState>().ui_ready.load(Ordering::Acquire) {
            if Instant::now() >= deadline {
                return Err(BridgeError::new(
                    "ui_timeout",
                    "The React desktop window did not connect.",
                ));
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        let mut result =
            service.request("host", "self_check", json!({"mode":"ui","image":null}))?;
        result["mode"] = json!("ui");
        result["frontend_ready"] = json!(true);
        result["service"] = json!(true);
        result["state"] = service.request("control-center", "get_state", json!({}))?;
        Ok(result)
    })();
    match result {
        Ok(result) => {
            let ok = result["ok"].as_bool() == Some(true);
            println!("{result}");
            app.exit(if ok { 0 } else { 2 });
        }
        Err(error) => {
            println!(
                "{}",
                json!({"ok":false,"mode":mode,"error":error.code,"message":error.message})
            );
            app.exit(2);
        }
    }
}

pub fn send_context(app: &tauri::AppHandle, service: &Service) -> Result<Value, BridgeError> {
    let mut context = platform::context(app)?;
    context["registered_hotkeys"] = platform::hotkeys::registered_map(app);
    service.request("host", "native.context", context)
}

fn install_tray(app: &tauri::AppHandle) -> tauri::Result<()> {
    use tauri::menu::{Menu, MenuItem};
    let capture = MenuItem::with_id(app, "capture", "Start capture", true, None::<&str>)?;
    let open = MenuItem::with_id(app, "open", "Open Hanly", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit Hanly", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&capture, &open, &quit])?;
    app.manage(TrayCapture(capture));
    let mut tray = tauri::tray::TrayIconBuilder::with_id("hanly")
        .menu(&menu)
        .tooltip("Hanly")
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open" => windows::show_control_center(app),
            "quit" => app.exit(0),
            "capture" => {
                let method = if capture_running(app) {
                    "stop_capture"
                } else {
                    "start_capture"
                };
                if let Ok(service) = app.state::<DesktopState>().service() {
                    let app = app.clone();
                    let service = service.clone();
                    tauri::async_runtime::spawn_blocking(move || {
                        if let Err(error) = service.request("control-center", method, json!({})) {
                            windows::event(
                                &app,
                                &app.state::<DesktopState>().presentation,
                                0,
                                "service_status",
                                json!({"state":"failed","code":error.code,"message":error.message}),
                            );
                            windows::show_control_center(&app);
                        }
                    });
                }
            }
            _ => {}
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

/// The tray's single capture item, relabelled from each published state.
struct TrayCapture(tauri::menu::MenuItem<tauri::Wry>);

fn capture_running(app: &tauri::AppHandle) -> bool {
    app.try_state::<DesktopState>().is_some_and(|state| {
        state
            .presentation
            .lock()
            .expect("presentation")
            .state
            .as_ref()
            .is_some_and(|s| s["app"]["capture_running"].as_bool() == Some(true))
    })
}

fn update_tray(app: &tauri::AppHandle) {
    let running = capture_running(app);
    let app_handle = app.clone();
    // Service reader callbacks must not wait on the native loop during root shutdown.
    let _ = app.run_on_main_thread(move || {
        if let Some(tray) = app_handle.tray_by_id("hanly") {
            let _ = tray.set_tooltip(Some(if running {
                "Hanly — watching"
            } else {
                "Hanly — stopped"
            }));
        }
        if let Some(item) = app_handle.try_state::<TrayCapture>() {
            let _ = item.0.set_text(if running {
                "Stop capture"
            } else {
                "Start capture"
            });
        }
    });
}

fn validate_handshake(value: Value) -> Result<(), BridgeError> {
    if value["service"] != "hanly-desktop"
        || value["protocol_version"] != 1
        || value["limits"]["max_frame_bytes"] != ipc::MAX_FRAME
        || value["limits"]["max_pending"] != ipc::MAX_PENDING
    {
        return Err(BridgeError::new(
            "protocol_mismatch",
            "The desktop service has an incompatible protocol.",
        ));
    }
    Ok(())
}
