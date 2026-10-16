mod validation;
use crate::{ipc::BridgeError, DesktopState};
use serde_json::{json, Value};
use std::sync::atomic::Ordering;
use tauri::{AppHandle, Manager, State, WebviewWindow};

#[tauri::command]
pub async fn desktop_request(
    app: AppHandle,
    window: WebviewWindow,
    state: State<'_, DesktopState>,
    method: String,
    params: Value,
) -> Result<Value, BridgeError> {
    validation::authorize(window.label(), &method, &params)?;
    if method == "copy_text" {
        use tauri_plugin_clipboard_manager::ClipboardExt;
        app.clipboard()
            .write_text(params["text"].as_str().expect("validated clipboard text"))
            .map_err(|_| BridgeError::new("clipboard_error", "Hanly could not copy the logs."))?;
        return Ok(json!({}));
    }
    if method == "frontend_ready" {
        if window.label() == "control-center" {
            state.ui_ready.store(true, Ordering::Release);
        }
        return crate::windows::local_action(&window, &state.presentation, &method, &params);
    }
    if method == "popup_pressed" {
        // The press's activation completes asynchronously; each check hands
        // it back once Hanly is active and does nothing otherwise.
        let app = app.clone();
        std::thread::spawn(move || {
            for delay in [0, 40, 80, 160, 320] {
                std::thread::sleep(std::time::Duration::from_millis(delay));
                if app
                    .run_on_main_thread(crate::platform::yield_activation)
                    .is_err()
                {
                    break;
                }
            }
        });
        return Ok(json!({}));
    }
    if method == "quit" {
        app.exit(0);
        return Ok(json!({}));
    }
    if method == "retry_runtime" {
        return tauri::async_runtime::spawn_blocking(move || crate::retry_service(&app))
            .await
            .map_err(|_| {
                BridgeError::new(
                    "service_error",
                    "Hanly could not restart its desktop service.",
                )
            })?;
    }
    let service = state.service()?;
    let label = window.label().to_owned();
    let app_handle = app.clone();
    let result = tauri::async_runtime::spawn_blocking(move || {
        match method.as_str() {
            "select_region" | "select_capture_area" => {
                return crate::windows::selector::open(&app_handle);
            }
            "cancel_region" => return crate::windows::selector::cancel(&app_handle),
            "confirm_region" => return crate::windows::selector::confirm(&app_handle, &params),
            _ => {}
        }

        if method.starts_with("popup_") {
            return popup_action(&app_handle, &window, &service, &method, params);
        }
        if method == "update_settings" && changes_hotkeys(&params) {
            return update_hotkeys(&app_handle, &service, params);
        }
        if method == "set_hotkey" {
            return update_hotkeys(
                &app_handle,
                &service,
                json!({"changes":{"hotkey":params["hotkey"]}}),
            );
        }

        let result = service.request(&label, &method, params)?;
        if method == "update_settings" {
            crate::send_context(&app_handle, &service)?;
        }
        Ok(result)
    })
    .await
    .map_err(|_| BridgeError::new("service_error", "The desktop request could not finish."))??;
    if result.get("app").is_some() {
        state.presentation.lock().expect("presentation").state = Some(result.clone());
    }
    Ok(result)
}

fn changes_hotkeys(params: &Value) -> bool {
    params["changes"].as_object().is_some_and(|changes| {
        ["hotkey", "hover_hotkey", "capture_hotkey"]
            .iter()
            .any(|key| changes.contains_key(*key))
    })
}

fn popup_action(
    app: &AppHandle,
    window: &WebviewWindow,
    service: &crate::lifecycle::Service,
    method: &str,
    mut params: Value,
) -> Result<Value, BridgeError> {
    let applied = crate::windows::local_action(
        window,
        &app.state::<DesktopState>().presentation,
        method,
        &params,
    )?;
    params["sequence"] = applied["sequence"].clone();
    let (native_method, native_params) = match method {
        "popup_close" => ("service.popup_close", params),
        "popup_expand" => ("service.popup_expand", params),
        "popup_geometry" => {
            let position = window
                .outer_position()
                .map_err(|_| {
                    BridgeError::new("window_error", "Hanly could not read its popup geometry.")
                })?
                .to_logical::<f64>(window.scale_factor().map_err(|_| {
                    BridgeError::new("window_error", "Hanly could not read its popup scale.")
                })?);
            (
                "service.popup_geometry",
                json!({
                    "sequence":params["sequence"], "x":position.x, "y":position.y,
                    "width":params["width"], "height":params["height"]
                }),
            )
        }
        _ => return Err(BridgeError::new("not_allowed", "Unknown popup action.")),
    };
    let mut reply = service.request(window.label(), native_method, native_params)?;
    // The room beside the word is the native host's answer, not the service's;
    // React caps the card to it.
    if let (Some(room), Some(fields)) = (applied.get("room"), reply.as_object_mut()) {
        fields.insert("room".to_owned(), room.clone());
    }
    Ok(reply)
}

fn update_hotkeys(
    app: &AppHandle,
    service: &crate::lifecycle::Service,
    params: Value,
) -> Result<Value, BridgeError> {
    let state = app.state::<DesktopState>();
    let _transaction = state.settings_lock.lock().expect("settings transaction");
    let prepared = service.request("control-center", "settings.prepare", params)?;
    let token = prepared["token"].clone();
    let candidate = match crate::platform::hotkeys::bindings(&prepared["settings"]) {
        Ok(candidate) => candidate,
        Err(error) => {
            let _ = service.request("control-center", "settings.abort", json!({"token":token}));
            return Err(error);
        }
    };
    let registration = match crate::platform::hotkeys::prepare(app, candidate) {
        Ok(previous) => previous,
        Err(error) => {
            let _ = service.request("control-center", "settings.abort", json!({"token":token}));
            return Err(error);
        }
    };
    match service.request("control-center", "settings.commit", json!({"token":token})) {
        Ok(_) => {
            crate::platform::hotkeys::commit(app, registration)?;
            crate::send_context(app, service)?;
            service.request("control-center", "get_state", json!({}))
        }
        Err(error) => {
            crate::platform::hotkeys::abort(app, registration);
            let _ = service.request("control-center", "settings.abort", json!({"token":token}));
            Err(error)
        }
    }
}
