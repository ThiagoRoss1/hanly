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
        use objc2_app_kit::{NSWindow, NSWindowCollectionBehavior};
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
        }
    }
    window.set_focusable(false).map_err(|_| window_error())
}

fn window_error() -> BridgeError {
    BridgeError::new(
        "platform_error",
        "Hanly could not read the native desktop geometry.",
    )
}
