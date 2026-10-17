use crate::{ipc::BridgeError, DesktopState};
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager};

pub fn open(app: &AppHandle) -> Result<Value, BridgeError> {
    let state = app.state::<DesktopState>();
    let service = state.service()?;
    let context = crate::platform::context(app)?;
    let bounds = union_bounds(&context["monitors"])?;
    {
        let mut presentation = state.presentation.lock().expect("presentation");
        if presentation.region.is_some() {
            return Err(BridgeError::new(
                "selection_active",
                "Capture area selection is already open.",
            ));
        }
        presentation.region = Some(json!({"bounds":bounds,"monitors":context["monitors"]}));
    }
    if let Err(error) = service.request("host", "native.selection", json!({"active":true})) {
        state.presentation.lock().expect("presentation").region = None;
        return Err(error);
    }
    if let Some(center) = app.get_webview_window("control-center") {
        let _ = center.hide();
    }
    if let Some(popup) = app.get_webview_window("popup") {
        let _ = crate::platform::hide_popup(&popup);
    }
    let backdrop = match service.request(
        "host",
        "native.selection_snapshot",
        json!({"bounds":bounds}),
    ) {
        Ok(snapshot) => snapshot,
        Err(error) => {
            let _ = cancel(app);
            return Err(error);
        }
    };
    let metadata =
        json!({"bounds":bounds,"monitors":context["monitors"],"image":backdrop["image"]});
    state.presentation.lock().expect("presentation").region = Some(metadata.clone());
    let window = app
        .get_webview_window("region-selector")
        .ok_or_else(error)?;
    let result = window
        .set_position(LogicalPosition::new(
            bounds["left"].as_f64().unwrap(),
            bounds["top"].as_f64().unwrap(),
        ))
        .and_then(|_| {
            window.set_size(LogicalSize::new(
                bounds["width"].as_f64().unwrap(),
                bounds["height"].as_f64().unwrap(),
            ))
        })
        .and_then(|_| window.show())
        .and_then(|_| window.set_focus());
    if result.is_err() {
        let _ = cancel(app);
        return Err(error());
    }
    let _ = window.emit("desktop-region", metadata);
    Ok(json!({}))
}

pub fn cancel(app: &AppHandle) -> Result<Value, BridgeError> {
    let state = app.state::<DesktopState>();
    state.presentation.lock().expect("presentation").region = None;
    if let Some(window) = app.get_webview_window("region-selector") {
        let _ = window.hide();
        let _ = window.emit("desktop-region", Value::Null);
    }
    let service = state.service()?;
    service.request("host", "native.selection", json!({"active":false}))?;
    crate::windows::show_control_center(app);
    service.request("control-center", "get_state", json!({}))
}

pub fn confirm(app: &AppHandle, params: &Value) -> Result<Value, BridgeError> {
    let state = app.state::<DesktopState>();
    let metadata = state
        .presentation
        .lock()
        .expect("presentation")
        .region
        .clone()
        .ok_or_else(|| {
            BridgeError::new(
                "selection_expired",
                "Capture area selection is no longer active.",
            )
        })?;
    let region = global_region(&metadata["bounds"], &params["region"])?;
    let service = state.service()?;
    let result = service.request("host", "native.region_selected", json!({"region":region}));
    if result.is_ok() {
        let _ = cancel(app);
    }
    result
}

fn union_bounds(monitors: &Value) -> Result<Value, BridgeError> {
    let list = monitors
        .as_array()
        .filter(|m| !m.is_empty())
        .ok_or_else(error)?;
    let mut left = i64::MAX;
    let mut top = i64::MAX;
    let mut right = i64::MIN;
    let mut bottom = i64::MIN;
    for monitor in list {
        let b = &monitor["bounds"];
        let x = b["left"].as_i64().ok_or_else(error)?;
        let y = b["top"].as_i64().ok_or_else(error)?;
        let w = b["width"].as_i64().filter(|n| *n > 0).ok_or_else(error)?;
        let h = b["height"].as_i64().filter(|n| *n > 0).ok_or_else(error)?;
        left = left.min(x);
        top = top.min(y);
        right = right.max(x + w);
        bottom = bottom.max(y + h);
    }
    Ok(json!({"left":left,"top":top,"width":right-left,"height":bottom-top}))
}

fn global_region(bounds: &Value, local: &Value) -> Result<Value, BridgeError> {
    let x = local["left"].as_i64().ok_or_else(error)?;
    let y = local["top"].as_i64().ok_or_else(error)?;
    let w = local["width"]
        .as_i64()
        .filter(|n| *n >= 8)
        .ok_or_else(error)?;
    let h = local["height"]
        .as_i64()
        .filter(|n| *n >= 8)
        .ok_or_else(error)?;
    if x < 0
        || y < 0
        || x + w > bounds["width"].as_i64().ok_or_else(error)?
        || y + h > bounds["height"].as_i64().ok_or_else(error)?
    {
        return Err(error());
    }
    Ok(
        json!({"left":bounds["left"].as_i64().ok_or_else(error)?+x,"top":bounds["top"].as_i64().ok_or_else(error)?+y,"width":w,"height":h}),
    )
}

fn error() -> BridgeError {
    BridgeError::new(
        "invalid_region",
        "Choose a capture area at least 8 × 8 pixels inside the desktop.",
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn preserves_negative_native_origin_without_double_scaling() {
        let bounds=union_bounds(&json!([{"bounds":{"left":-1920,"top":0,"width":1920,"height":1080}},{"bounds":{"left":0,"top":-100,"width":1728,"height":1117}}])).unwrap();
        let region = global_region(
            &bounds,
            &json!({"left":20,"top":30,"width":100,"height":200}),
        )
        .unwrap();
        assert_eq!(region["left"], -1900);
        assert_eq!(region["top"], -70);
        assert!(global_region(&bounds, &json!({"left":0,"top":0,"width":1,"height":200})).is_err());
    }
}
