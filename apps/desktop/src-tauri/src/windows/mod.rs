use crate::ipc::BridgeError;
use serde_json::{json, Value};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, WebviewWindow};

#[derive(Default)]
pub struct Presentation {
    pub state: Option<Value>,
    pub popup: Option<Value>,
    pub sequence: u64,
    pub visible: bool,
    queued: bool,
    state_pending: bool,
    popup_pending: bool,
    status: Option<Value>,
    status_pending: bool,
}

pub type SharedPresentation = Arc<Mutex<Presentation>>;

pub fn create(app: &AppHandle) -> tauri::Result<()> {
    for config in &app.config().app.windows {
        let window = tauri::WebviewWindowBuilder::from_config(app, config)?
            .on_navigation(allowed_navigation)
            .build()?;
        if window.label() == "control-center" {
            let window_handle = window.clone();
            window.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window_handle.hide();
                }
            });
        }
    }
    Ok(())
}

pub fn show_control_center(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("control-center") {
        let _ = window.show().and_then(|_| window.set_focus());
    }
}

pub fn event(
    app: &AppHandle,
    presentation: &SharedPresentation,
    sequence: u64,
    name: &str,
    payload: Value,
) {
    let mut state = presentation.lock().expect("presentation");
    match name {
        "state" => {
            state.state = Some(payload);
            state.state_pending = true;
        }
        "popup" | "popup_hide" => {
            if sequence <= state.sequence {
                return;
            }
            state.sequence = sequence;
            state.visible = name == "popup";
            state.popup = Some(json!({"type":name,"sequence":sequence,"payload":payload}));
            state.popup_pending = true;
        }
        "service_status" => {
            state.status = Some(payload);
            state.status_pending = true;
        }
        _ => return,
    }
    // Keep at most one native dispatch queued while newer snapshots supersede it.
    if state.queued {
        return;
    }
    state.queued = true;
    drop(state);
    let app_handle = app.clone();
    let state_handle = presentation.clone();
    if app
        .run_on_main_thread(move || flush_events(&app_handle, &state_handle))
        .is_err()
    {
        presentation.lock().expect("presentation").queued = false;
    }
}

fn flush_events(app: &AppHandle, presentation: &SharedPresentation) {
    let mut state = presentation.lock().expect("presentation");
    state.queued = false;
    if std::mem::take(&mut state.state_pending) {
        if let Some(snapshot) = &state.state {
            let _ = app.emit_to("control-center", "desktop-state", snapshot);
        }
    }
    if std::mem::take(&mut state.status_pending) {
        if let Some(status) = &state.status {
            let _ = app.emit_to("control-center", "desktop-service-status", status);
        }
    }
    if std::mem::take(&mut state.popup_pending) {
        if let Some(window) = app.get_webview_window("popup") {
            if state.visible {
                if let Some(message) = &state.popup {
                    let _ = show_popup(&window, &message["payload"]);
                }
            } else {
                let _ = window.hide();
            }
            if let Some(message) = &state.popup {
                let _ = window.emit("desktop-popup", message);
            }
        }
    }
}

pub fn local_action(
    window: &WebviewWindow,
    presentation: &SharedPresentation,
    method: &str,
    params: &Value,
) -> Result<Value, BridgeError> {
    let mut state = presentation.lock().expect("presentation");
    if method == "frontend_ready" {
        if window.label() == "popup" {
            if let Some(message) = &state.popup {
                let _ = window.emit("desktop-popup", message);
            }
        } else if window.label() == "control-center" {
            if let Some(snapshot) = &state.state {
                let _ = window.emit("desktop-state", snapshot);
            }
        }
        if window.label() == "control-center" {
            if let Some(status) = &state.status {
                let _ = window.emit("desktop-service-status", status);
            }
        }
        return Ok(json!({}));
    }
    if !state.visible || params["sequence"].as_u64() != Some(state.sequence) {
        return Err(BridgeError::new(
            "stale_popup",
            "This popup has been superseded.",
        ));
    }
    match method {
        "popup_close" => {
            state.visible = false;
            let message = json!({"type":"popup_hide","sequence":state.sequence,"payload":{}});
            state.popup = Some(message.clone());
            window.hide().map_err(|_| window_error())?;
            let _ = window.emit("desktop-popup", message);
        }
        // Expansion changes native size through the frontend's subsequent geometry command.
        "popup_expand" => {
            if let Some(message) = &mut state.popup {
                message["payload"]["expanded"] = params["expanded"].clone();
            }
        }
        "popup_geometry" => {
            let width = params["width"].as_f64().ok_or_else(window_error)?;
            let height = params["height"].as_f64().ok_or_else(window_error)?;
            window
                .set_size(LogicalSize::new(width, height))
                .map_err(|_| window_error())?;
        }
        _ => return Err(window_error()),
    }
    Ok(json!({}))
}

fn show_popup(window: &WebviewWindow, payload: &Value) -> Result<(), BridgeError> {
    let geometry = popup_geometry(payload)?;
    window
        .set_position(LogicalPosition::new(geometry.0, geometry.1))
        .and_then(|_| window.set_size(LogicalSize::new(geometry.2, geometry.3)))
        .and_then(|_| window.show())
        .map_err(|_| window_error())
}

fn popup_geometry(payload: &Value) -> Result<(f64, f64, f64, f64), BridgeError> {
    let coordinate = |value: &Value, min: f64, max: f64| {
        value
            .as_f64()
            .filter(|v| v.is_finite() && (min..=max).contains(v))
            .ok_or_else(window_error)
    };
    Ok((
        coordinate(&payload["position"]["x"], -100_000.0, 100_000.0)?,
        coordinate(&payload["position"]["y"], -100_000.0, 100_000.0)?,
        coordinate(&payload["size"]["width"], 1.0, 1000.0)?,
        coordinate(&payload["size"]["height"], 1.0, 1000.0)?,
    ))
}

fn allowed_navigation(url: &tauri::Url) -> bool {
    let bundled = (url.scheme() == "tauri" && url.host_str() == Some("localhost"))
        || (matches!(url.scheme(), "http" | "https")
            && url.host_str() == Some("tauri.localhost")
            && url.port().is_none());
    let dev = cfg!(debug_assertions)
        && url.scheme() == "http"
        && url.host_str() == Some("localhost")
        && url.port() == Some(5173);
    bundled || dev
}

fn window_error() -> BridgeError {
    BridgeError::new("window_error", "Hanly could not update the popup window.")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn geometry_preserves_fractional_and_negative_logical_positions() {
        assert_eq!(
            popup_geometry(
                &json!({"position":{"x":-40.5,"y":-3},"size":{"width":380,"height":200}})
            )
            .unwrap(),
            (-40.5, -3.0, 380.0, 200.0)
        );
        assert!(
            popup_geometry(&json!({"position":{"x":0,"y":0},"size":{"width":0,"height":200}}))
                .is_err()
        );
    }

    #[test]
    fn navigation_rejects_foreign_and_file_origins() {
        assert!(allowed_navigation(
            &tauri::Url::parse("tauri://localhost/index.html").unwrap()
        ));
        assert!(!allowed_navigation(
            &tauri::Url::parse("https://example.com").unwrap()
        ));
        assert!(!allowed_navigation(
            &tauri::Url::parse("file:///etc/passwd").unwrap()
        ));
        assert!(!allowed_navigation(
            &tauri::Url::parse("http://tauri.localhost:8080").unwrap()
        ));
    }
}
