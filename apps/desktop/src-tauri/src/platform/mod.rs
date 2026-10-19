pub mod hotkeys;
#[cfg(target_os = "macos")]
mod popup_macos;
#[cfg(target_os = "macos")]
pub use popup_macos::PaintedPopup;
#[cfg(not(target_os = "macos"))]
pub struct PaintedPopup;

use crate::ipc::BridgeError;
use serde_json::{json, Value};
use tauri::{AppHandle, Manager, WebviewWindow};

pub fn configure_application() {
    #[cfg(target_os = "macos")]
    {
        use objc2::{AnyThread, MainThreadMarker};
        use objc2_app_kit::{NSApplication, NSImage};
        use objc2_foundation::NSData;
        let mtm = MainThreadMarker::new().expect("native application setup runs on main thread");
        let data = NSData::with_bytes(include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../../packages/hanly-app/src/hanly_app/assets/icons/hanly-macos-icon.png"
        )));
        if let Some(image) = NSImage::initWithData(NSImage::alloc(), &data) {
            // The image stays retained through the public AppKit setter on the main thread.
            unsafe {
                NSApplication::sharedApplication(mtm).setApplicationIconImage(Some(&image));
            }
        }
    }
}

pub fn context(app: &AppHandle) -> Result<Value, BridgeError> {
    let window = app
        .get_webview_window("control-center")
        .ok_or_else(window_error)?;
    let monitors = window.available_monitors().map_err(|_| window_error())?;
    let cursor = window.cursor_position().map_err(|_| window_error())?;
    #[cfg(target_os = "macos")]
    // Tao reports the global macOS cursor using the primary display's scale, including on other displays.
    let scale = window
        .primary_monitor()
        .map_err(|_| window_error())?
        .map_or(1.0, |m| m.scale_factor());
    #[cfg(not(target_os = "macos"))]
    let scale = monitors
        .iter()
        .find(|m| {
            let p = m.position();
            let s = m.size();
            cursor.x >= f64::from(p.x)
                && cursor.y >= f64::from(p.y)
                && cursor.x < f64::from(p.x) + f64::from(s.width)
                && cursor.y < f64::from(p.y) + f64::from(s.height)
        })
        .map_or(1.0, |m| m.scale_factor());
    let list:Vec<Value>=monitors.iter().enumerate().map(|(i,m)| {
        let p=m.position().to_logical::<f64>(m.scale_factor());
        let s=m.size().to_logical::<f64>(m.scale_factor());
        json!({"index":i+1,"name":m.name().cloned().unwrap_or_else(||format!("Display {}",i+1)),"bounds":{"left":p.x.round() as i64,"top":p.y.round() as i64,"width":s.width.round() as i64,"height":s.height.round() as i64}})
    }).collect();
    let cursor = cursor.to_logical::<f64>(scale);
    Ok(
        json!({"cursor":{"x":cursor.x,"y":cursor.y},"monitors":list,"vision_available":vision_available()}),
    )
}

fn vision_available() -> bool {
    #[cfg(target_os = "macos")]
    {
        let version = objc2_foundation::NSProcessInfo::processInfo().operatingSystemVersion();
        // VNRecognizeTextRequest is public from macOS 10.15. No OCR framework or provider is loaded here.
        version.majorVersion > 10 || (version.majorVersion == 10 && version.minorVersion >= 15)
    }
    #[cfg(not(target_os = "macos"))]
    {
        false
    }
}

pub fn configure_popup(window: &WebviewWindow) -> Result<(), BridgeError> {
    #[cfg(target_os = "macos")]
    popup_macos::configure(window)?;
    window.set_focusable(false).map_err(|_| window_error())
}

pub fn prepare_popup_update(window: &WebviewWindow, replacement: bool) -> Result<(), BridgeError> {
    #[cfg(target_os = "macos")]
    {
        let _ = (window, replacement);
        popup_macos::freeze()
    }
    #[cfg(not(target_os = "macos"))]
    {
        if replacement {
            window.hide().map_err(|_| window_error())?;
        }
        Ok(())
    }
}

pub fn prepare_popup_frame(
    window: &WebviewWindow,
    width: f64,
    height: f64,
    finished: impl FnOnce(Result<PaintedPopup, BridgeError>) + Send + 'static,
) -> Result<(), BridgeError> {
    #[cfg(target_os = "macos")]
    {
        popup_macos::paint(window, width, height, finished)
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (window, width, height);
        finished(Ok(PaintedPopup));
        Ok(())
    }
}

pub fn hide_popup(window: &WebviewWindow) -> Result<(), BridgeError> {
    #[cfg(target_os = "macos")]
    {
        let _ = window;
        popup_macos::hide()
    }
    #[cfg(not(target_os = "macos"))]
    {
        window.hide().map_err(|_| window_error())
    }
}

pub fn popup_position(window: &WebviewWindow) -> Result<(f64, f64), BridgeError> {
    #[cfg(target_os = "macos")]
    {
        let _ = window;
        popup_macos::position()
    }
    #[cfg(not(target_os = "macos"))]
    {
        let position = window
            .outer_position()
            .map_err(|_| window_error())?
            .to_logical::<f64>(window.scale_factor().map_err(|_| window_error())?);
        Ok((position.x, position.y))
    }
}

pub fn uncover_popup() -> Result<(), BridgeError> {
    #[cfg(target_os = "macos")]
    {
        popup_macos::uncover()
    }
    #[cfg(not(target_os = "macos"))]
    {
        Ok(())
    }
}

pub fn present_popup_frame(
    window: &WebviewWindow,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    painted: PaintedPopup,
) -> Result<(), BridgeError> {
    #[cfg(target_os = "macos")]
    {
        let _ = window;
        popup_macos::present(x, y, width, height, painted)
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = painted;
        window
            .set_size(tauri::LogicalSize::new(width, height))
            .and_then(|_| window.set_position(tauri::LogicalPosition::new(x, y)))
            .map_err(|_| window_error())?;
        if !window.is_visible().map_err(|_| window_error())? {
            window.show().map_err(|_| window_error())?;
        }
        Ok(())
    }
}

#[cfg(any(target_os = "macos", test))]
fn cocoa_popup_origin(x: f64, y: f64, height: f64, primary_top: f64) -> (f64, f64) {
    (x, primary_top - y - height)
}

fn window_error() -> BridgeError {
    BridgeError::new(
        "platform_error",
        "Hanly could not read the native desktop geometry.",
    )
}

#[cfg(test)]
mod tests {
    use super::cocoa_popup_origin;

    #[test]
    fn cocoa_frame_preserves_top_left_and_negative_display_origins() {
        assert_eq!(
            cocoa_popup_origin(111.0, 134.0, 365.0, 881.0),
            (111.0, 382.0)
        );
        assert_eq!(
            cocoa_popup_origin(-460.5, -200.0, 560.0, 900.0),
            (-460.5, 540.0)
        );
    }
}
