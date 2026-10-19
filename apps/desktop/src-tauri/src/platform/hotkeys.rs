use crate::{ipc::BridgeError, DesktopState};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::str::FromStr;
use tauri::{AppHandle, Manager};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

pub(crate) type InputEvent = (String, &'static str);
pub(crate) type InputSender = std::sync::mpsc::SyncSender<InputEvent>;

#[derive(Clone)]
pub struct Binding {
    pub action: String,
    pub text: String,
    pub shortcut: Shortcut,
}

pub fn bindings(config: &Value) -> Result<Vec<Binding>, BridgeError> {
    let mut seen = HashSet::new();
    let mut list = Vec::new();
    for (field, action) in [
        ("hotkey", "push_to_hover"),
        ("hover_hotkey", "toggle_hover"),
        ("capture_hotkey", "toggle_capture"),
    ] {
        let text = config[field].as_str().ok_or_else(invalid)?.to_owned();
        if text.is_empty() && field == "capture_hotkey" {
            continue;
        }
        let shortcut = Shortcut::from_str(&normalize(&text)).map_err(|_| invalid())?;
        if !seen.insert(shortcut.id()) {
            return Err(BridgeError::new(
                "hotkey_conflict",
                "Two Hanly actions use the same shortcut.",
            ));
        }
        list.push(Binding {
            action: action.into(),
            text,
            shortcut,
        });
    }
    Ok(list)
}

pub struct Registration {
    candidate: Vec<Binding>,
    previous: Vec<Binding>,
    added: Vec<Shortcut>,
}

pub fn prepare(app: &AppHandle, candidate: Vec<Binding>) -> Result<Registration, BridgeError> {
    let previous = app
        .state::<DesktopState>()
        .hotkeys
        .lock()
        .expect("hotkey bindings")
        .clone();
    let existing: HashSet<u32> = previous.iter().map(|b| b.shortcut.id()).collect();
    let mut added = Vec::new();
    for binding in &candidate {
        if existing.contains(&binding.shortcut.id()) {
            continue;
        }
        if app.global_shortcut().register(binding.shortcut).is_err() {
            for shortcut in added {
                let _ = app.global_shortcut().unregister(shortcut);
            }
            return Err(BridgeError::new(
                "hotkey_conflict",
                "Hanly could not register this shortcut. Another application may own it.",
            ));
        }
        added.push(binding.shortcut);
    }
    // Existing shortcuts remain registered and active until Python commits persistence.
    Ok(Registration {
        candidate,
        previous,
        added,
    })
}

pub fn abort(app: &AppHandle, registration: Registration) {
    for shortcut in registration.added {
        let _ = app.global_shortcut().unregister(shortcut);
    }
}

pub fn commit(app: &AppHandle, registration: Registration) -> Result<Vec<Binding>, BridgeError> {
    let keep: HashSet<u32> = registration
        .candidate
        .iter()
        .map(|b| b.shortcut.id())
        .collect();
    *app.state::<DesktopState>()
        .hotkeys
        .lock()
        .expect("hotkey bindings") = registration.candidate;
    let mut failed = false;
    for binding in &registration.previous {
        if !keep.contains(&binding.shortcut.id()) {
            failed |= app.global_shortcut().unregister(binding.shortcut).is_err();
        }
    }
    if failed {
        return Err(BridgeError::new("hotkey_cleanup_failed", "The new shortcuts were saved, but Hanly could not release an old shortcut. Restart Hanly."));
    }
    Ok(registration.previous)
}

pub fn replace(app: &AppHandle, candidate: Vec<Binding>) -> Result<Vec<Binding>, BridgeError> {
    commit(app, prepare(app, candidate)?)
}

pub fn registered_map(app: &AppHandle) -> Value {
    let state = app.state::<DesktopState>();
    let map: HashMap<String, String> = state
        .hotkeys
        .lock()
        .expect("hotkey bindings")
        .iter()
        .map(|b| (b.action.clone(), b.text.clone()))
        .collect();
    json!(map)
}

pub fn handler(
    app: &AppHandle,
    shortcut: &Shortcut,
    event: tauri_plugin_global_shortcut::ShortcutEvent,
) {
    let state = app.state::<DesktopState>();
    if state.options.trace {
        println!(
            "{}",
            json!({"type":"trace","payload":{"event":"native_hotkey_edge","shortcut_id":shortcut.id(),"pressed":event.state() == ShortcutState::Pressed}})
        );
    }
    let action = state
        .hotkeys
        .lock()
        .expect("hotkey bindings")
        .iter()
        .find(|b| b.shortcut.id() == shortcut.id())
        .map(|b| b.action.clone());
    let Some(action) = action else {
        return;
    };
    let edge = if event.state() == ShortcutState::Pressed {
        "pressed"
    } else {
        "released"
    };
    if let Some(sender) = state.input.lock().expect("input sender").as_ref() {
        if sender.try_send((action, edge)).is_err() {
            state
                .input_overflow
                .store(true, std::sync::atomic::Ordering::Release);
        }
    };
}

pub fn start_input(app: &AppHandle) {
    let (sender, receiver) = std::sync::mpsc::sync_channel::<InputEvent>(32);
    let state = app.state::<DesktopState>();
    *state.input.lock().expect("input sender") = Some(sender);
    let overflow = state.input_overflow.clone();
    let app = app.clone();
    let worker = std::thread::spawn(move || {
        while let Ok((action, edge)) = receiver.recv() {
            let Ok(service) = app.state::<DesktopState>().service() else {
                continue;
            };
            if overflow.swap(false, std::sync::atomic::Ordering::AcqRel) {
                while receiver.try_recv().is_ok() {}
                // Queue saturation must never leave push-to-hover held indefinitely.
                let _ = service.request(
                    "host",
                    "native.input",
                    json!({"action":"push_to_hover","edge":"released"}),
                );
                crate::windows::event(
                    &app,
                    &app.state::<DesktopState>().presentation,
                    0,
                    "service_status",
                    json!({"state":"failed","code":"input_overloaded","message":"Shortcut input was interrupted. Release the keys and try again."}),
                );
                continue;
            }
            let result =
                service.request("host", "native.input", json!({"action":action,"edge":edge}));
            let error = match result {
                Err(error) => Some(error),
                Ok(value) if value["accepted"].as_bool() == Some(false) => Some(BridgeError::new(
                    "input_unavailable",
                    "This shortcut is not ready. Wait for Hanly to finish preparing.",
                )),
                _ => None,
            };
            if let Some(error) = error {
                crate::windows::event(
                    &app,
                    &app.state::<DesktopState>().presentation,
                    0,
                    "service_status",
                    json!({"state":"failed","code":error.code,"message":error.message}),
                );
            }
        }
    });
    *state.input_thread.lock().expect("input worker") = Some(worker);
}

fn normalize(value: &str) -> String {
    value
        .split('+')
        .map(|p| match p.trim().to_ascii_lowercase().as_str() {
            "space" => "Space".into(),
            "ctrl" => "Control".into(),
            "cmd" | "command" => "Super".into(),
            "alt" | "option" => "Alt".into(),
            "shift" => "Shift".into(),
            other => other.to_owned(),
        })
        .collect::<Vec<_>>()
        .join("+")
}
fn invalid() -> BridgeError {
    BridgeError::new(
        "invalid_hotkey",
        "This shortcut cannot be registered by Hanly.",
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn mac_letter_defaults_keep_control_and_command_as_distinct_modifiers() {
        let list = bindings(&json!({
            "hotkey":"ctrl+cmd+h", "hover_hotkey":"ctrl+cmd+p", "capture_hotkey":"ctrl+cmd+r"
        }))
        .unwrap();
        assert_eq!(list.len(), 3);
        for (binding, key) in list.iter().zip(["H", "P", "R"]) {
            assert_eq!(
                binding.shortcut,
                Shortcut::from_str(&format!("Control+Super+{key}")).unwrap()
            );
        }
    }

    #[test]
    fn preserves_control_chords_and_rejects_duplicates() {
        let config = json!({"hotkey":"ctrl+shift+space","hover_hotkey":"ctrl+shift+f9","capture_hotkey":"ctrl+shift+f10"});
        let list = bindings(&config).unwrap();
        assert_eq!(list.len(), 3);
        assert_eq!(list[0].text, "ctrl+shift+space");
        let mut duplicate = config;
        duplicate["capture_hotkey"] = duplicate["hotkey"].clone();
        assert!(bindings(&duplicate).is_err());
    }
}
