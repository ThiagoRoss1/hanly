mod commands;
mod ipc;
mod lifecycle;
mod windows;

use ipc::BridgeError;
use lifecycle::Service;
use serde_json::json;
use std::sync::{Arc, Mutex};
use tauri::Manager;

pub struct DesktopState {
    service: Result<Arc<Service>, BridgeError>,
    presentation: windows::SharedPresentation,
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_clipboard_manager::init())
        .invoke_handler(tauri::generate_handler![commands::desktop_request])
        .setup(|app| {
            let presentation = Arc::new(Mutex::new(windows::Presentation::default()));
            let events_app = app.handle().clone();
            let events_presentation = presentation.clone();
            let events = Arc::new(move |sequence, event: &str, payload| {
                windows::event(&events_app, &events_presentation, sequence, event, payload)
            });
            let service = lifecycle::service_command()
                .and_then(|command| Service::launch(command, events))
                .map(Arc::new);
            app.manage(DesktopState {
                service,
                presentation,
            });
            windows::create(app.handle())?;
            install_tray(app.handle())?;
            let handle = app.handle().clone();
            let service = app.state::<DesktopState>().service.clone();
            tauri::async_runtime::spawn_blocking(move || {
                let result = service
                    .and_then(|s| s.request("host", "service.hello", json!({})))
                    .and_then(validate_handshake);
                let status = match result {
                    Ok(_) => json!({"state":"ready"}),
                    Err(error) => {
                        json!({"state":"failed","code":error.code,"message":error.message})
                    }
                };
                let presentation = &handle.state::<DesktopState>().presentation;
                windows::event(&handle, presentation, 0, "service_status", status);
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Hanly desktop could not initialize");
    app.run(|app, event| match event {
        tauri::RunEvent::Exit => {
            if let Ok(service) = &app.state::<DesktopState>().service {
                service.stop();
            }
        }
        #[cfg(target_os = "macos")]
        tauri::RunEvent::Reopen { .. } => windows::show_control_center(app),
        _ => {}
    });
}

fn install_tray(app: &tauri::AppHandle) -> tauri::Result<()> {
    use tauri::menu::{Menu, MenuItem};
    let open = MenuItem::with_id(app, "open", "Open Hanly", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit Hanly", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &quit])?;
    let mut tray = tauri::tray::TrayIconBuilder::new()
        .menu(&menu)
        .tooltip("Hanly")
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open" => windows::show_control_center(app),
            "quit" => app.exit(0),
            _ => {}
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

fn validate_handshake(value: serde_json::Value) -> Result<(), BridgeError> {
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
