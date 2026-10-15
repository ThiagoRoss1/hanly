pub mod hotkeys;

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
    {
        use objc2_app_kit::{NSColor, NSWindow, NSWindowCollectionBehavior};
        let raw = window.ns_window().map_err(|_| window_error())?;
        // Public AppKit behavior keeps a non-key floating window visible while another app is active.
        unsafe {
            let window = &*(raw as *const NSWindow);
            window.setHidesOnDeactivate(false);
            window.setCollectionBehavior(
                NSWindowCollectionBehavior::CanJoinAllSpaces
                    | NSWindowCollectionBehavior::FullScreenAuxiliary,
            );
            window.setLevel(3);
            window.setOpaque(false);
            window.setBackgroundColor(Some(&NSColor::clearColor()));
            // Clip the entire native content, including the opaque webview, to
            // the card. Public AppKit/Core Animation avoids WKWebView private APIs.
            if let Some(content) = window.contentView() {
                content.setWantsLayer(true);
                if let Some(layer) = content.layer() {
                    layer.setCornerRadius(14.0);
                    layer.setMasksToBounds(true);
                }
            }
            window.setHasShadow(true);
        }
    }
    window.set_focusable(false).map_err(|_| window_error())
}

pub fn present_popup_frame(
    window: &WebviewWindow,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<(), BridgeError> {
    #[cfg(target_os = "macos")]
    {
        use objc2::MainThreadMarker;
        use objc2_app_kit::{NSScreen, NSWindow};
        use objc2_foundation::{NSPoint, NSRect, NSSize};

        let mtm = MainThreadMarker::new().ok_or_else(window_error)?;
        let primary = NSScreen::screens(mtm)
            .firstObject()
            .ok_or_else(window_error)?;
        let primary_frame = primary.frame();
        let (left, bottom) = cocoa_popup_origin(
            x,
            y,
            height,
            primary_frame.origin.y + primary_frame.size.height,
        );
        let raw = window.ns_window().map_err(|_| window_error())?;
        // Tao queues size/position setters but shows synchronously on macOS.
        // Commit one public AppKit frame before ordering it onto the screen.
        unsafe {
            let native = &*(raw as *const NSWindow);
            native.setFrame_display(
                NSRect::new(NSPoint::new(left, bottom), NSSize::new(width, height)),
                true,
            );
            if let Some(content) = native.contentView() {
                content.layoutSubtreeIfNeeded();
            }
            native.invalidateShadow();
            if !native.isVisible() {
                native.orderFrontRegardless();
            }
        }
        Ok(())
    }
    #[cfg(not(target_os = "macos"))]
    {
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
