pub mod selector;

use crate::ipc::BridgeError;
use serde_json::{json, Value};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter, Manager, WebviewWindow};

#[derive(Default)]
pub struct Presentation {
    pub state: Option<Value>,
    pub popup: Option<Value>,
    pub sequence: u64,
    sequence_base: u64,
    pub visible: bool,
    paint_revision: u64,
    pub region: Option<Value>,
    applied_theme: Option<Option<tauri::Theme>>,
    /// The side a presented answer took; expansion keeps it.
    placed_above: Option<bool>,
    queued: bool,
    state_pending: bool,
    popup_pending: bool,
    status: Option<Value>,
    status_pending: bool,
}

pub type SharedPresentation = Arc<Mutex<Presentation>>;

pub fn reset(presentation: &SharedPresentation) {
    let mut state = presentation.lock().expect("presentation");
    let sequence = state.sequence;
    // React remains alive when Python restarts; its freshness counter must not
    // move backwards with the replacement service's new wire event stream.
    *state = Presentation {
        sequence,
        sequence_base: sequence,
        ..Presentation::default()
    };
}

pub fn create(app: &AppHandle) -> tauri::Result<()> {
    for config in &app.config().app.windows {
        let window = tauri::WebviewWindowBuilder::from_config(app, config)?
            .incognito(
                app.state::<crate::DesktopState>()
                    .options
                    .app_config
                    .is_some(),
            )
            .on_navigation(allowed_navigation)
            .build()?;
        if window.label() == "popup" {
            crate::platform::configure_popup(&window)
                .map_err(|e| tauri::Error::Anyhow(anyhow::anyhow!(e.message)))?;
        }
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
            let Some(sequence) = popup_event_sequence(&state, sequence) else {
                return;
            };
            state.sequence = sequence;
            state.visible = name == "popup";
            if name == "popup_hide" || payload["replacement"].as_bool() != Some(false) {
                state.placed_above = None;
            }
            state.popup = Some(json!({"type":name,"sequence":sequence,"payload":payload}));
            state.popup_pending = true;
        }
        "service_status" => {
            if payload["state"] == "failed" {
                state.visible = false;
                state.popup =
                    Some(json!({"type":"popup_hide","sequence":state.sequence,"payload":{}}));
                state.popup_pending = true;
            }
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

fn popup_event_sequence(state: &Presentation, wire_sequence: u64) -> Option<u64> {
    wire_sequence
        .checked_add(state.sequence_base)
        .filter(|sequence| *sequence > state.sequence && *sequence <= crate::ipc::MAX_SEQUENCE)
}

fn flush_events(app: &AppHandle, presentation: &SharedPresentation) {
    let (snapshot, status, popup) = {
        let mut state = presentation.lock().expect("presentation");
        state.queued = false;
        let snapshot = std::mem::take(&mut state.state_pending)
            .then(|| state.state.clone())
            .flatten();
        let status = std::mem::take(&mut state.status_pending)
            .then(|| state.status.clone())
            .flatten();
        let popup =
            std::mem::take(&mut state.popup_pending).then(|| (state.visible, state.popup.clone()));
        (snapshot, status, popup)
    };

    // Native dispatch can re-enter the event loop; never retain its shared lock.
    if let Some(snapshot) = snapshot {
        let theme = match snapshot["config"]["theme"].as_str() {
            Some("dark") => Some(tauri::Theme::Dark),
            Some("light") => Some(tauri::Theme::Light),
            _ => None,
        };
        let changed = {
            let mut state = presentation.lock().expect("presentation");
            let changed = state.applied_theme != Some(theme);
            state.applied_theme = Some(theme);
            changed
        };
        if changed {
            for window in app.webview_windows().values() {
                let _ = window.set_theme(theme);
            }
        }
        let _ = app.emit_to("control-center", "desktop-state", snapshot);
    }
    if let Some(status) = status {
        let _ = app.emit_to("control-center", "desktop-service-status", status);
    }
    if let Some((visible, message)) = popup {
        let current = presentation.lock().expect("presentation").popup == message;
        if !current {
            return;
        }
        if let Some(window) = app.get_webview_window("popup") {
            if visible {
                let replacement = message.as_ref().is_some_and(|message| {
                    message["payload"]["replacement"].as_bool() != Some(false)
                });
                let _ = crate::platform::prepare_popup_update(&window, replacement);
            } else {
                let _ = crate::platform::hide_popup(&window);
            }
            if let Some(message) = message {
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
    if method == "frontend_ready" {
        let messages = {
            let state = presentation.lock().expect("presentation");
            match window.label() {
                "popup" => vec![("desktop-popup", state.popup.clone())],
                "control-center" => vec![
                    ("desktop-state", state.state.clone()),
                    ("desktop-service-status", state.status.clone()),
                ],
                "region-selector" => vec![("desktop-region", state.region.clone())],
                _ => vec![],
            }
        };
        for (event, payload) in messages {
            if let Some(payload) = payload {
                let _ = window.emit(event, payload);
            }
        }
        return Ok(json!({}));
    }

    let window = window.clone();
    let presentation = presentation.clone();
    let method = method.to_owned();
    let params = params.clone();
    let (sender, receiver) = std::sync::mpsc::sync_channel(1);
    let dispatch_window = window.clone();
    window
        .run_on_main_thread(move || {
            if method == "popup_geometry" {
                if let Err(error) =
                    render_popup(&dispatch_window, &presentation, &params, sender.clone())
                {
                    let _ = sender.send(Err(error));
                }
            } else {
                let result = apply_popup_action(&dispatch_window, &presentation, &method, &params);
                let _ = sender.send(result);
            }
        })
        .map_err(|_| window_error())?;
    receiver
        .recv_timeout(std::time::Duration::from_secs(10))
        .map_err(|_| window_error())?
}

fn apply_popup_action(
    window: &WebviewWindow,
    presentation: &SharedPresentation,
    method: &str,
    params: &Value,
) -> Result<Value, BridgeError> {
    let (message, service_sequence, payload, placed_above) = {
        let mut state = presentation.lock().expect("presentation");
        let service_sequence = popup_service_sequence(&state, params)?;
        let message = match method {
            "popup_close" => {
                state.visible = false;
                let message = json!({"type":"popup_hide","sequence":state.sequence,"payload":{}});
                state.popup = Some(message.clone());
                Some(message)
            }
            "popup_expand" => {
                if let Some(message) = &mut state.popup {
                    message["payload"]["expanded"] = params["expanded"].clone();
                }
                None
            }
            "popup_measure" => None,
            _ => return Err(window_error()),
        };
        let payload = state
            .popup
            .as_ref()
            .map(|message| message["payload"].clone());
        (message, service_sequence, payload, state.placed_above)
    };

    match method {
        "popup_close" => {
            crate::platform::hide_popup(window)?;
            let _ = window.emit("desktop-popup", message.expect("close message"));
        }
        "popup_measure" => {
            let width = params["width"].as_f64().ok_or_else(window_error)?;
            let height = params["height"].as_f64().ok_or_else(window_error)?;
            let payload = payload.ok_or_else(window_error)?;
            let (x, y, _, _) = popup_geometry(&payload)?;
            let band = popup_band(&payload)?;
            let placed = fit_measured_popup(window, (x, y), (width, height), band, placed_above)?;
            let (left, top) = placed.origin;
            return Ok(json!({"sequence":service_sequence,"room":placed.room,
                "x":left,"y":top,"width":width,"height":placed.height,"above":placed.above}));
        }
        // The frontend follows expansion with its measured geometry command.
        "popup_expand" => {}
        _ => return Err(window_error()),
    }
    Ok(json!({"sequence":service_sequence}))
}

fn render_popup(
    window: &WebviewWindow,
    presentation: &SharedPresentation,
    params: &Value,
    finished: std::sync::mpsc::SyncSender<Result<Value, BridgeError>>,
) -> Result<(), BridgeError> {
    let placed = apply_popup_action(window, presentation, "popup_measure", params)?;
    let revision = {
        let mut state = presentation.lock().expect("presentation");
        state.paint_revision = state
            .paint_revision
            .checked_add(1)
            .ok_or_else(window_error)?;
        state.paint_revision
    };
    let window = window.clone();
    let presentation = presentation.clone();
    let params = params.clone();
    let width = placed["width"].as_f64().ok_or_else(window_error)?;
    let height = placed["height"].as_f64().ok_or_else(window_error)?;
    let snapshot_window = window.clone();
    crate::platform::prepare_popup_frame(&snapshot_window, width, height, move |painted| {
        let result = (|| {
            let painted = painted?;
            // Rendering is asynchronous: a newer result or a close must win
            // even when the older WebKit snapshot finishes afterwards.
            {
                let state = presentation.lock().expect("presentation");
                current_popup_paint(&state, &params, revision)?;
            }
            crate::platform::present_popup_frame(
                &window,
                placed["x"].as_f64().ok_or_else(window_error)?,
                placed["y"].as_f64().ok_or_else(window_error)?,
                width,
                height,
                painted,
            )
        })();
        if let Err(error) = result {
            complete_popup_render(
                &window,
                &presentation,
                &params,
                revision,
                Err(error),
                &finished,
            );
            return;
        }

        let painting = presentation.clone();
        let painted_params = params.clone();
        let painted_window = window.clone();
        let completion = finished.clone();
        // Reveal a ready image first. Acknowledge geometry only after the
        // visible WebKit canvas has painted and its cover can be removed.
        if let Err(error) =
            crate::platform::prepare_popup_frame(&window, width, height, move |ready| {
                complete_popup_render(
                    &painted_window,
                    &painting,
                    &painted_params,
                    revision,
                    ready.map(|_| placed),
                    &completion,
                );
            })
        {
            complete_popup_render(
                &window,
                &presentation,
                &params,
                revision,
                Err(error),
                &finished,
            );
        }
    })
}

fn complete_popup_render(
    window: &WebviewWindow,
    presentation: &SharedPresentation,
    params: &Value,
    revision: u64,
    result: Result<Value, BridgeError>,
    finished: &std::sync::mpsc::SyncSender<Result<Value, BridgeError>>,
) {
    let result = (|| {
        {
            let state = presentation.lock().expect("presentation");
            current_popup_paint(&state, params, revision)?;
        }
        let mut placed = match result {
            Ok(placed) => placed,
            Err(error) => {
                // Never leave a frozen, unclickable card after a paint error.
                // Logical currency remains intact for the frontend's bounded retry.
                let _ = crate::platform::hide_popup(window);
                return Err(error);
            }
        };
        crate::platform::uncover_popup()?;
        let (x, y) = crate::platform::popup_position(window)?;
        placed["x"] = json!(x);
        placed["y"] = json!(y);
        let mut state = presentation.lock().expect("presentation");
        current_popup_paint(&state, params, revision)?;
        state.placed_above = placed["above"].as_bool();
        Ok(placed)
    })();
    let _ = finished.send(result);
}

fn current_popup_paint(
    state: &Presentation,
    params: &Value,
    revision: u64,
) -> Result<(), BridgeError> {
    popup_service_sequence(state, params)?;
    if state.paint_revision != revision {
        return Err(BridgeError::new(
            "stale_popup",
            "This popup layout has been superseded.",
        ));
    }
    Ok(())
}

fn popup_service_sequence(state: &Presentation, params: &Value) -> Result<u64, BridgeError> {
    if !state.visible || params["sequence"].as_u64() != Some(state.sequence) {
        return Err(BridgeError::new(
            "stale_popup",
            "This popup has been superseded.",
        ));
    }
    // The wire event counter orders all events; Python's counter identifies
    // popup content only. Capture the translation under the freshness lock.
    state
        .popup
        .as_ref()
        .and_then(|message| message["payload"]["sequence"].as_u64())
        .filter(|sequence| *sequence > 0)
        .ok_or_else(window_error)
}

/// Least height an answer is still useful at. Below a word with less room
/// than this the card goes above it; otherwise it stays below and scrolls.
const MIN_USABLE_HEIGHT: f64 = 160.0;

/// Kept clear above the Dock so the card's edge and shadow stay visible.
const WORK_AREA_MARGIN: f64 = 6.0;

#[derive(Debug, PartialEq)]
struct Placement {
    origin: (f64, f64),
    height: f64,
    above: Option<bool>,
    /// Height available on the chosen side, which the card is capped to.
    room: f64,
}

fn fit_measured_popup(
    window: &WebviewWindow,
    (x, y): (f64, f64),
    size: (f64, f64),
    band: Option<(f64, f64)>,
    above: Option<bool>,
) -> Result<Placement, BridgeError> {
    for monitor in window.available_monitors().map_err(|_| window_error())? {
        let scale = monitor.scale_factor();
        let origin = monitor.position().to_logical::<f64>(scale);
        let extent = monitor.size().to_logical::<f64>(scale);
        if x >= origin.x
            && x < origin.x + extent.width
            && y >= origin.y
            && y < origin.y + extent.height
        {
            // The work area excludes the menu bar and Dock, which a card
            // placed against the full display would slide under.
            let area = monitor.work_area();
            let area_origin = area.position.to_logical::<f64>(scale);
            let area_size = area.size.to_logical::<f64>(scale);
            let bounds = (
                area_origin.x,
                area_origin.y,
                area_size.width,
                area_size.height - WORK_AREA_MARGIN,
            );
            return Ok(place_measured((x, y), size, bounds, band, above));
        }
    }
    Ok(Placement {
        origin: (x, y),
        height: size.1,
        above,
        room: size.1,
    })
}

/// Place the measured card below its word, as the desktop always has.
///
/// A card taller than the room below keeps its place and is capped to that
/// room, scrolling inside; only a word too close to the bottom for a usable
/// card sends it above. Expansion keeps the side the answer took.
fn place_measured(
    (x, y): (f64, f64),
    (width, height): (f64, f64),
    bounds: (f64, f64, f64, f64),
    band: Option<(f64, f64)>,
    above: Option<bool>,
) -> Placement {
    let Some((band_top, band_bottom)) = band else {
        let height = height.min(bounds.3);
        return Placement {
            origin: fit_position((x, y), (width, height), bounds),
            height,
            above,
            room: bounds.3,
        };
    };
    let below_room = (bounds.1 + bounds.3 - band_bottom.floor()).max(0.0);
    let above_room = (band_top.ceil() - bounds.1).max(0.0);
    let above =
        above.unwrap_or(below_room < height.min(MIN_USABLE_HEIGHT) && above_room > below_room);
    let room = if above { above_room } else { below_room };
    let height = height.min(room).max(1.0);
    let top = if above {
        (band_top - height).floor()
    } else {
        band_bottom.floor()
    };
    Placement {
        origin: (fit_position((x, top), (width, height), bounds).0, top),
        height,
        above: Some(above),
        room,
    }
}

fn fit_position(
    position: (f64, f64),
    size: (f64, f64),
    bounds: (f64, f64, f64, f64),
) -> (f64, f64) {
    (
        position
            .0
            .clamp(bounds.0, (bounds.0 + bounds.2 - size.0).max(bounds.0)),
        position
            .1
            .clamp(bounds.1, (bounds.1 + bounds.3 - size.1).max(bounds.1)),
    )
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

fn popup_band(payload: &Value) -> Result<Option<(f64, f64)>, BridgeError> {
    let band = &payload["band"];
    if band.is_null() {
        return Ok(None);
    }
    let edge = |value: &Value| {
        value
            .as_f64()
            .filter(|v| v.is_finite() && (-100_000.0..=100_000.0).contains(v))
            .ok_or_else(window_error)
    };
    let (top, bottom) = (edge(&band["top"])?, edge(&band["bottom"])?);
    if top > bottom {
        return Err(window_error());
    }
    Ok(Some((top, bottom)))
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
    fn measured_expansion_stays_on_its_negative_origin_display() {
        assert_eq!(
            fit_position(
                (-100.5, 700.0),
                (460.0, 560.0),
                (-1440.0, 0.0, 1440.0, 900.0)
            ),
            (-460.0, 340.0)
        );
        assert_eq!(
            fit_position((40.5, 54.5), (340.0, 219.0), (0.0, 0.0, 1440.0, 900.0)),
            (40.5, 54.5)
        );
    }

    #[test]
    fn answers_stay_below_their_word_and_tall_ones_scroll_above_the_dock() {
        // A work area that ends above a Dock at 900.
        let area = (0.0, 25.0, 1440.0, 815.0);
        let placed = |band: (f64, f64), height: f64, above: Option<bool>| {
            place_measured((100.0, band.1), (340.0, height), area, Some(band), above)
        };

        // Mid-screen: below the word, full height.
        assert_eq!(
            placed((494.0, 526.0), 282.0, None),
            Placement {
                origin: (100.0, 526.0),
                height: 282.0,
                above: Some(false),
                room: 314.0
            }
        );
        // Taller than the room below: still below, capped above the Dock.
        assert_eq!(
            placed((494.0, 526.0), 560.0, None),
            Placement {
                origin: (100.0, 526.0),
                height: 314.0,
                above: Some(false),
                room: 314.0
            }
        );
        // Expanding keeps the side and the cap; the card scrolls.
        assert_eq!(placed((494.0, 526.0), 900.0, Some(false)).height, 314.0);
        // Too close to the bottom for a usable card: above the word.
        assert_eq!(
            placed((730.0, 760.0), 282.0, None),
            Placement {
                origin: (100.0, 448.0),
                height: 282.0,
                above: Some(true),
                room: 705.0
            }
        );
        // Older payloads without a band retain plain work-area clamping.
        assert_eq!(
            place_measured((100.0, 800.0), (340.0, 282.0), area, None, None).origin,
            (100.0, 558.0)
        );
    }

    #[test]
    fn popup_actions_translate_event_order_without_accepting_stale_content() {
        let mut state = Presentation {
            visible: true,
            sequence: 212,
            popup: Some(json!({"payload":{"sequence":3}})),
            ..Presentation::default()
        };
        assert_eq!(
            popup_service_sequence(&state, &json!({"sequence":212})).unwrap(),
            3
        );
        assert_eq!(
            popup_service_sequence(&state, &json!({"sequence":211}))
                .unwrap_err()
                .code,
            "stale_popup"
        );
        state.visible = false;
        assert!(popup_service_sequence(&state, &json!({"sequence":212})).is_err());
        state.visible = true;
        state.popup = Some(json!({"payload":{}}));
        assert!(popup_service_sequence(&state, &json!({"sequence":212})).is_err());
    }

    #[test]
    fn late_paint_cannot_replace_a_newer_layout_or_reopen_a_closed_popup() {
        let mut state = Presentation {
            visible: true,
            sequence: 212,
            paint_revision: 2,
            popup: Some(json!({"payload":{"sequence":3}})),
            ..Presentation::default()
        };
        let params = json!({"sequence":212});
        assert!(current_popup_paint(&state, &params, 1).is_err());
        assert!(current_popup_paint(&state, &params, 2).is_ok());
        state.visible = false;
        assert!(current_popup_paint(&state, &params, 2).is_err());
        state.visible = true;
        state.sequence = 213;
        assert!(current_popup_paint(&state, &params, 2).is_err());
    }

    #[test]
    fn replacement_service_preserves_react_freshness_and_rejects_duplicate_events() {
        let presentation = Arc::new(Mutex::new(Presentation {
            sequence: 212,
            visible: true,
            popup: Some(json!({"payload":{"sequence":3}})),
            ..Presentation::default()
        }));
        reset(&presentation);
        let mut state = presentation.lock().unwrap();
        assert!(!state.visible);
        assert!(state.popup.is_none());
        assert_eq!(popup_event_sequence(&state, 1), Some(213));
        state.sequence = 213;
        assert_eq!(popup_event_sequence(&state, 1), None);
        assert_eq!(popup_event_sequence(&state, 2), Some(214));
        assert_eq!(popup_event_sequence(&state, crate::ipc::MAX_SEQUENCE), None);
    }

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
