mod validation;

use crate::{ipc::BridgeError, DesktopState};
use serde_json::{json, Value};
use tauri::{AppHandle, State, WebviewWindow};

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
    if method == "frontend_ready" || method.starts_with("popup_") {
        return crate::windows::local_action(&window, &state.presentation, &method, &params);
    }
    if method == "quit" {
        app.exit(0);
        return Ok(json!({}));
    }
    if ["select_region", "cancel_region", "confirm_region"].contains(&method.as_str()) {
        return Err(BridgeError::new(
            "unavailable",
            "Capture area selection is not ready in this build.",
        ));
    }
    let service = state.service.as_ref().map_err(Clone::clone)?.clone();
    let label = window.label().to_owned();
    let snapshot_method = method == "get_state";
    let result =
        tauri::async_runtime::spawn_blocking(move || service.request(&label, &method, params))
            .await
            .map_err(|_| {
                BridgeError::new("service_error", "The desktop request could not finish.")
            })??;
    if snapshot_method {
        state.presentation.lock().expect("presentation").state = Some(result.clone());
    }
    Ok(result)
}
