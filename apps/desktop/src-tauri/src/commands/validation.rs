use crate::ipc::{BridgeError, MAX_FRAME};
use serde_json::{Map, Value};

pub fn authorize(window: &str, method: &str, params: &Value) -> Result<(), BridgeError> {
    let allowed = match window {
        "control-center" => [
            "get_state",
            "start_capture",
            "stop_capture",
            "set_capture_mode",
            "set_target",
            "set_region",
            "select_capture_area",
            "set_hover_delay",
            "set_hotkey",
            "update_settings",
            "grant_permission",
            "refresh_permissions",
            "retry_runtime",
            "quit",
            "check_for_updates",
            "install_update",
            "install_application_update",
            "cancel_update",
            "open_release_notes",
            "get_logs",
            "clear_logs",
            "export_diagnostics",
            "frontend_ready",
            "select_region",
            "copy_text",
        ]
        .contains(&method),
        "popup" => [
            "frontend_ready",
            "popup_close",
            "popup_expand",
            "popup_geometry",
            "popup_pressed",
        ]
        .contains(&method),
        "region-selector" => {
            ["frontend_ready", "confirm_region", "cancel_region"].contains(&method)
        }
        _ => false,
    };
    if !allowed {
        return Err(BridgeError::new(
            "not_allowed",
            "This action is unavailable from this window.",
        ));
    }
    let object = params.as_object().ok_or_else(invalid_params)?;
    if serde_json::to_vec(params)
        .map_err(|_| invalid_params())?
        .len()
        > MAX_FRAME - 512
    {
        return Err(BridgeError::new(
            "message_too_large",
            "The desktop request exceeds its size limit.",
        ));
    }

    match method {
        "update_settings" => {
            keys(object, &["changes"])?;
            if !object.get("changes").is_some_and(Value::is_object) {
                return Err(invalid_params());
            }
        }
        "set_hover_delay" => {
            keys(object, &["delay_ms"])?;
            integer(object, "delay_ms", 0, 10_000)?;
        }
        "copy_text" => {
            keys(object, &["text"])?;
            if !object["text"]
                .as_str()
                .is_some_and(|s| s.len() <= 64 * 1024)
            {
                return Err(invalid_params());
            }
        }
        "set_hotkey" => {
            keys(object, &["hotkey"])?;
            bounded_string(object, "hotkey", 128)?;
        }
        "set_capture_mode" => {
            keys(object, &["mode"])?;
            bounded_string(object, "mode", 32)?;
        }
        "set_target" => {
            keys(object, &["target"])?;
            if !(object["target"].is_string() || object["target"].is_i64()) {
                return Err(invalid_params());
            }
        }
        "set_region" => {
            keys(object, &["region"])?;
            if !object["region"].is_null() {
                region(&object["region"])?;
            }
        }
        "grant_permission" => {
            keys(object, &["permission"])?;
            bounded_string(object, "permission", 64)?;
        }
        "install_update" => {
            keys(object, &["resource_id"])?;
            bounded_string(object, "resource_id", 64)?;
        }
        "install_application_update" => {
            if !object.is_empty() {
                keys(object, &["confirm_full"])?;
                boolean(object, "confirm_full")?;
            }
        }
        "frontend_ready" => {
            keys(object, &["view"])?;
            let expected = match window {
                "control-center" => "control_center",
                "popup" => "popup",
                _ => "region_selector",
            };
            if object["view"].as_str() != Some(expected) {
                return Err(invalid_params());
            }
        }
        "popup_close" => {
            keys(object, &["sequence"])?;
            sequence(object)?;
        }
        "popup_expand" => {
            keys(object, &["sequence", "expanded"])?;
            sequence(object)?;
            boolean(object, "expanded")?;
        }
        "popup_geometry" => {
            keys(object, &["sequence", "width", "height"])?;
            sequence(object)?;
            number(object, "width", 1.0, 1000.0)?;
            number(object, "height", 1.0, 1000.0)?;
        }
        "confirm_region" => {
            keys(object, &["region", "coordinate_space", "scale_factor"])?;
            region(&object["region"])?;
            if object["coordinate_space"].as_str() != Some("overlay_logical") {
                return Err(invalid_params());
            }
            number(object, "scale_factor", 0.1, 10.0)?;
        }
        _ => keys(object, &[])?,
    }
    Ok(())
}

fn keys(object: &Map<String, Value>, names: &[&str]) -> Result<(), BridgeError> {
    if object.len() != names.len() || names.iter().any(|n| !object.contains_key(*n)) {
        return Err(invalid_params());
    }
    Ok(())
}

fn bounded_string(object: &Map<String, Value>, key: &str, bound: usize) -> Result<(), BridgeError> {
    if object[key]
        .as_str()
        .is_some_and(|v| !v.is_empty() && v.len() <= bound)
    {
        Ok(())
    } else {
        Err(invalid_params())
    }
}

fn boolean(object: &Map<String, Value>, key: &str) -> Result<(), BridgeError> {
    if object[key].is_boolean() {
        Ok(())
    } else {
        Err(invalid_params())
    }
}

fn integer(object: &Map<String, Value>, key: &str, min: i64, max: i64) -> Result<(), BridgeError> {
    if object[key]
        .as_i64()
        .is_some_and(|v| (min..=max).contains(&v))
    {
        Ok(())
    } else {
        Err(invalid_params())
    }
}

fn number(object: &Map<String, Value>, key: &str, min: f64, max: f64) -> Result<(), BridgeError> {
    if object[key]
        .as_f64()
        .is_some_and(|v| v.is_finite() && (min..=max).contains(&v))
    {
        Ok(())
    } else {
        Err(invalid_params())
    }
}

fn sequence(object: &Map<String, Value>) -> Result<(), BridgeError> {
    integer(object, "sequence", 1, crate::ipc::MAX_SEQUENCE as i64)
}

fn region(value: &Value) -> Result<(), BridgeError> {
    let object = value.as_object().ok_or_else(invalid_params)?;
    keys(object, &["left", "top", "width", "height"])?;
    integer(object, "left", -100_000, 100_000)?;
    integer(object, "top", -100_000, 100_000)?;
    integer(object, "width", 1, 100_000)?;
    integer(object, "height", 1, 100_000)
}

fn invalid_params() -> BridgeError {
    BridgeError::new(
        "invalid_params",
        "The desktop action has invalid parameters.",
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn separates_window_authority_and_rejects_extra_fields() {
        assert!(authorize("control-center", "get_state", &json!({})).is_ok());
        assert!(authorize("popup", "update_settings", &json!({"changes": {}})).is_err());
        assert!(authorize("unknown", "get_state", &json!({})).is_err());
        assert!(authorize("control-center", "get_state", &json!({"path":"/tmp"})).is_err());
        assert!(authorize("popup", "frontend_ready", &json!({"view":"control_center"})).is_err());
        // Only the popup reports presses, and a press carries nothing.
        assert!(authorize("popup", "popup_pressed", &json!({})).is_ok());
        assert!(authorize("popup", "popup_pressed", &json!({"x":1})).is_err());
        assert!(authorize("control-center", "popup_pressed", &json!({})).is_err());
    }

    #[test]
    fn accepts_negative_region_origins_and_rejects_boolean_coordinates() {
        assert!(authorize(
            "region-selector",
            "confirm_region",
            &json!({"region":{"left":-100,"top":-50,"width":20,"height":40},"coordinate_space":"overlay_logical","scale_factor":2.0})
        )
        .is_ok());
        assert!(authorize(
            "region-selector",
            "confirm_region",
            &json!({"region":{"left":true,"top":0,"width":20,"height":40},"coordinate_space":"overlay_logical","scale_factor":2.0})
        )
        .is_err());
        assert!(authorize(
            "popup",
            "popup_geometry",
            &json!({"sequence":1,"width":1001,"height":20})
        )
        .is_err());
    }
}
