//! A real nonactivating panel, with a painted frame before native presentation.

use crate::ipc::BridgeError;
use block2::RcBlock;
use objc2::{rc::Retained, MainThreadMarker, MainThreadOnly};
use objc2_app_kit::{
    NSBackingStoreType, NSColor, NSImage, NSImageScaling, NSImageView, NSPanel, NSView, NSWindow,
    NSWindowAnimationBehavior, NSWindowCollectionBehavior, NSWindowStyleMask,
};
use objc2_foundation::{NSError, NSPoint, NSRect, NSSize};
use objc2_web_kit::{WKSnapshotConfiguration, WKWebView};
use std::cell::RefCell;
use tauri::WebviewWindow;

const CANVAS: NSSize = NSSize::new(460.0, 560.0);

struct Popup {
    panel: Retained<NSPanel>,
    container: Retained<NSView>,
    canvas: Retained<NSView>,
    cover: Retained<NSImageView>,
    image: Option<Retained<NSImage>>,
}

thread_local! {
    static POPUP: RefCell<Option<Popup>> = const { RefCell::new(None) };
}

pub struct PaintedPopup(Retained<NSImage>);

pub fn configure(window: &WebviewWindow) -> Result<(), BridgeError> {
    let mtm = MainThreadMarker::new().ok_or_else(error)?;
    let raw = window.ns_window().map_err(|_| error())?;
    // Keep Tao's observed window/class intact. Reparent its content with public
    // AppKit APIs; the Tauri root still owns the webview and every command.
    let original = unsafe { &*(raw as *const NSWindow) };
    let canvas = original.contentView().ok_or_else(error)?;
    let frame = NSRect::new(NSPoint::new(0.0, 0.0), CANVAS);
    let panel = NSPanel::initWithContentRect_styleMask_backing_defer(
        NSPanel::alloc(mtm),
        frame,
        NSWindowStyleMask::Borderless | NSWindowStyleMask::NonactivatingPanel,
        NSBackingStoreType::Buffered,
        false,
    );
    // The root retains the panel; AppKit must not release that owner on close.
    unsafe {
        panel.setReleasedWhenClosed(false);
    }
    // Utility-window ordering otherwise scales the card for several frames.
    panel.setAnimationBehavior(NSWindowAnimationBehavior::None);
    panel.setFloatingPanel(true);
    panel.setBecomesKeyOnlyIfNeeded(true);
    panel.setHidesOnDeactivate(false);
    panel.setCollectionBehavior(
        NSWindowCollectionBehavior::CanJoinAllSpaces
            | NSWindowCollectionBehavior::FullScreenAuxiliary,
    );
    panel.setLevel(3);
    panel.setOpaque(false);
    panel.setBackgroundColor(Some(&NSColor::clearColor()));
    panel.setHasShadow(true);

    let container = NSView::initWithFrame(NSView::alloc(mtm), frame);
    container.setWantsLayer(true);
    if let Some(layer) = container.layer() {
        layer.setCornerRadius(14.0);
        layer.setMasksToBounds(true);
    }
    original.setContentView(None);
    canvas.setFrame(frame);
    // The webview never resizes during a card transition. Only the panel crops
    // its fixed canvas; a cached image covers DOM changes until paint is ready.
    canvas.setAutoresizingMask(objc2_app_kit::NSAutoresizingMaskOptions::empty());
    container.addSubview(&canvas);
    let cover = NSImageView::initWithFrame(NSImageView::alloc(mtm), frame);
    cover.setImageScaling(NSImageScaling::ScaleAxesIndependently);
    cover.setHidden(true);
    container.addSubview(&cover);
    panel.setContentView(Some(&container));
    POPUP.with(|slot| {
        *slot.borrow_mut() = Some(Popup {
            panel,
            container,
            canvas,
            cover,
            image: None,
        })
    });
    Ok(())
}

pub fn freeze() -> Result<(), BridgeError> {
    POPUP.with(|slot| {
        let slot = slot.borrow();
        let popup = slot.as_ref().ok_or_else(error)?;
        if popup.panel.isVisible() {
            popup.cover.setImage(popup.image.as_deref());
            popup.cover.setHidden(popup.image.is_none());
            popup.cover.displayIfNeeded();
        }
        Ok(())
    })
}

pub fn paint(
    window: &WebviewWindow,
    width: f64,
    height: f64,
    finished: impl FnOnce(Result<PaintedPopup, BridgeError>) + Send + 'static,
) -> Result<(), BridgeError> {
    window
        .with_webview(move |native| {
            let Some(mtm) = MainThreadMarker::new() else {
                finished(Err(error()));
                return;
            };
            let finished = RefCell::new(Some(finished));
            let completion = RcBlock::new(move |image: *mut NSImage, _error: *mut NSError| {
                let result = unsafe { Retained::retain(image) }
                    .map(PaintedPopup)
                    .ok_or_else(error);
                if let Some(finished) = finished.borrow_mut().take() {
                    finished(result);
                }
            });
            // Unlike DOM measurement or a hidden-window rAF, this public WebKit
            // barrier completes with the new content actually rendered.
            unsafe {
                let config = WKSnapshotConfiguration::new(mtm);
                config.setRect(NSRect::new(
                    NSPoint::new(0.0, 0.0),
                    NSSize::new(width, height),
                ));
                config.setAfterScreenUpdates(true);
                let webview = &*(native.inner() as *const WKWebView);
                webview.takeSnapshotWithConfiguration_completionHandler(Some(&config), &completion);
            }
        })
        .map_err(|_| error())
}

pub fn present(
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    painted: PaintedPopup,
) -> Result<(), BridgeError> {
    let mtm = MainThreadMarker::new().ok_or_else(error)?;
    let primary = objc2_app_kit::NSScreen::screens(mtm)
        .firstObject()
        .ok_or_else(error)?;
    let primary = primary.frame();
    let (left, bottom) =
        super::cocoa_popup_origin(x, y, height, primary.origin.y + primary.size.height);
    POPUP.with(|slot| {
        let mut slot = slot.borrow_mut();
        let popup = slot.as_mut().ok_or_else(error)?;
        popup.cover.setImage(Some(&painted.0));
        popup.cover.setHidden(false);
        popup.panel.setFrame_display(
            NSRect::new(NSPoint::new(left, bottom), NSSize::new(width, height)),
            false,
        );
        popup
            .canvas
            .setFrameOrigin(NSPoint::new(0.0, height - CANVAS.height));
        popup.cover.setFrame(popup.container.bounds());
        popup.container.layoutSubtreeIfNeeded();
        popup.panel.displayIfNeeded();
        popup.panel.invalidateShadow();
        popup.image = Some(painted.0);
        if !popup.panel.isVisible() {
            popup.panel.orderFrontRegardless();
        }
        Ok(())
    })
}

pub fn uncover() -> Result<(), BridgeError> {
    POPUP.with(|slot| {
        let slot = slot.borrow();
        slot.as_ref().ok_or_else(error)?.cover.setHidden(true);
        Ok(())
    })
}

pub fn hide() -> Result<(), BridgeError> {
    POPUP.with(|slot| {
        let mut slot = slot.borrow_mut();
        let popup = slot.as_mut().ok_or_else(error)?;
        popup.panel.orderOut(None);
        popup.cover.setImage(None);
        popup.cover.setHidden(true);
        popup.image = None;
        Ok(())
    })
}

pub fn position() -> Result<(f64, f64), BridgeError> {
    let mtm = MainThreadMarker::new().ok_or_else(error)?;
    let primary = objc2_app_kit::NSScreen::screens(mtm)
        .firstObject()
        .ok_or_else(error)?;
    let top = primary.frame().origin.y + primary.frame().size.height;
    POPUP.with(|slot| {
        let slot = slot.borrow();
        let frame = slot.as_ref().ok_or_else(error)?.panel.frame();
        Ok((frame.origin.x, top - frame.origin.y - frame.size.height))
    })
}

fn error() -> BridgeError {
    BridgeError::new(
        "popup_render_error",
        "Hanly could not prepare the popup's rendered frame.",
    )
}
