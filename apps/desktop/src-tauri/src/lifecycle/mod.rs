pub mod options;
#[cfg(windows)]
mod windows_job;

use crate::ipc::{self, BridgeError, Message, MAX_PENDING};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::io::{BufReader, Write};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

type Answer = Result<Value, BridgeError>;
pub(crate) type EventSink = Arc<dyn Fn(u64, &str, Value) + Send + Sync>;

struct Channel {
    writer: Option<mpsc::SyncSender<Vec<u8>>>,
    pending: HashMap<String, mpsc::SyncSender<Answer>>,
    failure: Option<BridgeError>,
    stopped: bool,
    on_failure: Arc<dyn Fn(BridgeError) + Send + Sync>,
}

/// Owns the private service process and resolves every outstanding request at disconnect.
pub struct Service {
    channel: Arc<Mutex<Channel>>,
    child: Arc<Mutex<Child>>,
    #[cfg(windows)]
    job: Arc<Mutex<Option<windows_job::WindowsJob>>>,
    next_id: AtomicU64,
    threads: Mutex<Vec<thread::JoinHandle<()>>>,
}

impl Service {
    pub fn launch(mut command: Command, events: EventSink) -> Result<Self, BridgeError> {
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            command.process_group(0);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command
                .creation_flags(0x08000004)
                .env("HANLY_SUPERVISED_JOB", "1");
        }
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| {
                BridgeError::new(
                    "service_start_failed",
                    "Hanly could not start its desktop service.",
                )
            })?;
        #[cfg(windows)]
        let job = match windows_job::WindowsJob::attach(&child).and_then(|job| {
            job.resume(child.id())?;
            Ok(job)
        }) {
            Ok(job) => Arc::new(Mutex::new(Some(job))),
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
        };
        let group_pid = child.id();
        let mut input = child.stdin.take().expect("piped service stdin");
        let output = child.stdout.take().expect("piped service stdout");
        let (writer, writes) = mpsc::sync_channel::<Vec<u8>>(MAX_PENDING);
        let failure_events = events.clone();
        let channel = Arc::new(Mutex::new(Channel {
            writer: Some(writer),
            pending: HashMap::new(),
            failure: None,
            stopped: false,
            on_failure: Arc::new(move |error: BridgeError| {
                failure_events(
                    0,
                    "service_status",
                    json!({"state":"failed","code":error.code,"message":error.message}),
                )
            }),
        }));
        let child = Arc::new(Mutex::new(child));

        let write_channel = channel.clone();
        let writer_thread = thread::spawn(move || {
            while let Ok(frame) = writes.recv() {
                if input.write_all(&frame).and_then(|_| input.flush()).is_err() {
                    fail(&write_channel, disconnected());
                    break;
                }
            }
        });
        let read_channel = channel.clone();
        let reader_thread = thread::spawn(move || {
            let mut reader = BufReader::new(output);
            let mut sequence = 0;
            loop {
                let frame = match ipc::read_frame(&mut reader) {
                    Ok(Some(frame)) => frame,
                    Ok(None) => {
                        fail(&read_channel, disconnected());
                        break;
                    }
                    Err(_) => {
                        fail(&read_channel, ipc::protocol_error());
                        break;
                    }
                };
                match ipc::decode(&frame) {
                    Ok(Message::Reply {
                        id, result, error, ..
                    }) => {
                        let answer = read_channel
                            .lock()
                            .expect("service channel")
                            .pending
                            .remove(&id);
                        match answer {
                            Some(answer) => {
                                let _ = answer.send(match error {
                                    Some(error) => Err(error),
                                    None => Ok(result.expect("validated reply")),
                                });
                            }
                            None => {
                                fail(&read_channel, ipc::protocol_error());
                                break;
                            }
                        }
                    }
                    Ok(Message::Event {
                        sequence: incoming,
                        event,
                        payload,
                        ..
                    }) => {
                        if incoming <= sequence {
                            fail(&read_channel, ipc::protocol_error());
                            break;
                        }
                        sequence = incoming;
                        events(incoming, &event, payload);
                    }
                    Err(error) => {
                        fail(&read_channel, error);
                        break;
                    }
                }
            }
        });
        let watch_channel = channel.clone();
        let watch_child = child.clone();
        #[cfg(windows)]
        let watch_job = job.clone();
        let watcher_thread = thread::spawn(move || loop {
            let (stopped, failed) = {
                let state = watch_channel.lock().expect("service channel");
                (state.stopped, state.failure.is_some())
            };
            let mut child = watch_child.lock().expect("service process");
            // A wedged writer or a malformed service must not keep the family alive.
            if failed && !stopped {
                #[cfg(windows)]
                watch_job.lock().expect("service job").take();
                terminate_family(group_pid, &mut child);
            }
            match child.try_wait() {
                Ok(Some(_)) | Err(_) => {
                    #[cfg(windows)]
                    watch_job.lock().expect("service job").take();
                    terminate_family(group_pid, &mut child);
                    fail(&watch_channel, disconnected());
                    break;
                }
                Ok(None) => {}
            }
            drop(child);
            thread::sleep(Duration::from_millis(20));
        });
        Ok(Self {
            channel,
            child,
            #[cfg(windows)]
            job,
            next_id: AtomicU64::new(1),
            threads: Mutex::new(vec![writer_thread, reader_thread, watcher_thread]),
        })
    }

    pub fn request(&self, window: &str, method: &str, params: Value) -> Answer {
        self.request_with_timeout(
            window,
            method,
            params,
            Duration::from_secs(if method == "self_check" { 120 } else { 15 }),
        )
    }

    fn request_with_timeout(
        &self,
        window: &str,
        method: &str,
        params: Value,
        timeout: Duration,
    ) -> Answer {
        let id = format!("native-{}", self.next_id.fetch_add(1, Ordering::Relaxed));
        let mut frame = serde_json::to_vec(&json!({"version":1,"type":"request","id":id,"window":window,"method":method,"params":params})).map_err(|_| ipc::protocol_error())?;
        if frame.len() > ipc::MAX_FRAME {
            return Err(BridgeError::new(
                "message_too_large",
                "The desktop request exceeds its size limit.",
            ));
        }
        frame.push(b'\n');
        let (answer, received) = mpsc::sync_channel(1);
        {
            let mut channel = self.channel.lock().expect("service channel");
            if let Some(error) = &channel.failure {
                return Err(error.clone());
            }
            if channel.stopped {
                return Err(disconnected());
            }
            if channel.pending.len() >= MAX_PENDING {
                return Err(BridgeError::new(
                    "busy",
                    "The desktop service is busy. Try again shortly.",
                ));
            }
            let writer = channel.writer.as_ref().ok_or_else(disconnected)?;
            writer.try_send(frame).map_err(|_| {
                BridgeError::new("busy", "The desktop service is busy. Try again shortly.")
            })?;
            channel.pending.insert(id.clone(), answer);
        }
        match received.recv_timeout(timeout) {
            Ok(answer) => answer,
            Err(_) => {
                // Ambiguous completion cannot be retried safely on the same session.
                let error = BridgeError::new(
                    "service_timeout",
                    "The desktop service did not respond in time.",
                );
                fail(&self.channel, error.clone());
                Err(error)
            }
        }
    }

    pub fn connected(&self) -> bool {
        let channel = self.channel.lock().expect("service channel");
        !channel.stopped && channel.failure.is_none()
    }

    pub fn stop(&self) {
        let _ = self.request_with_timeout(
            "host",
            "service.shutdown",
            json!({}),
            Duration::from_secs(2),
        );
        {
            let mut channel = self.channel.lock().expect("service channel");
            channel.stopped = true;
            channel.writer.take();
        }
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            let mut child = self.child.lock().expect("service process");
            if matches!(child.try_wait(), Ok(Some(_))) {
                break;
            }
            if Instant::now() >= deadline {
                terminate_family(child.id(), &mut child);
                let _ = child.wait();
                break;
            }
            drop(child);
            thread::sleep(Duration::from_millis(20));
        }
        #[cfg(unix)]
        {
            let pid = self.child.lock().expect("service process").id();
            // Detached update helpers have their own session; only service/lookup descendants share this group.
            unsafe {
                libc::kill(-(pid as i32), libc::SIGKILL);
            }
        }
        #[cfg(windows)]
        self.job.lock().expect("service job").take();
        fail(&self.channel, disconnected());
        for thread in self.threads.lock().expect("service threads").drain(..) {
            let _ = thread.join();
        }
    }
}

impl Drop for Service {
    fn drop(&mut self) {
        self.stop();
    }
}

fn terminate_family(pid: u32, child: &mut Child) {
    #[cfg(unix)]
    unsafe {
        libc::kill(-(pid as i32), libc::SIGKILL);
    }
    let _ = child.kill();
}

fn fail(channel: &Mutex<Channel>, error: BridgeError) {
    let mut channel = channel.lock().expect("service channel");
    let first_failure = channel.failure.is_none();
    if first_failure {
        channel.failure = Some(error.clone());
    }
    channel.writer.take();
    for (_, answer) in channel.pending.drain() {
        let _ = answer.send(Err(error.clone()));
    }
    let report = first_failure && !channel.stopped;
    let on_failure = channel.on_failure.clone();
    drop(channel);
    if report {
        on_failure(error);
    }
}

fn disconnected() -> BridgeError {
    BridgeError::new(
        "service_disconnected",
        "The desktop service disconnected. Restart Hanly to reconnect.",
    )
}

pub fn service_command(
    app: Option<&tauri::AppHandle>,
    options: &options::LaunchOptions,
) -> Result<Command, BridgeError> {
    use tauri::Manager;
    let executable = std::env::current_exe().map_err(|_| {
        BridgeError::new(
            "service_missing",
            "Hanly could not locate its native executable.",
        )
    })?;
    let service_name = if cfg!(windows) {
        "hanly-service.exe"
    } else {
        "hanly-service"
    };
    let resource_root = if let Some(app) = app {
        app.path().resource_dir().map_err(|_| {
            BridgeError::new(
                "service_missing",
                "Hanly could not locate its runtime resources.",
            )
        })?
    } else if cfg!(target_os = "macos")
        && executable
            .parent()
            .is_some_and(|p| p.file_name().is_some_and(|n| n == "MacOS"))
    {
        executable
            .parent()
            .and_then(|p| p.parent())
            .expect("bundle Contents directory")
            .join("Resources")
    } else {
        executable
            .parent()
            .expect("native executable directory")
            .join("resources")
    };
    let primary = resource_root.join("hanly-service").join(service_name);
    let portable = executable
        .parent()
        .ok_or_else(|| {
            BridgeError::new(
                "service_missing",
                "Hanly could not locate its installation.",
            )
        })?
        .join("resources/hanly-service")
        .join(service_name);
    let bundled = if primary.is_file() {
        Some(primary)
    } else if portable.is_file() {
        Some(portable)
    } else {
        None
    };
    let mut command;
    #[cfg(debug_assertions)]
    let observer = std::env::var("HANLY_DESKTOP_SERVICE_MODULE")
        .ok()
        .filter(|module| module == "lab.service_observer");
    #[cfg(not(debug_assertions))]
    let observer: Option<String> = None;
    if let Some(service) = bundled.filter(|_| observer.is_none()) {
        command = Command::new(service);
    } else {
        #[cfg(debug_assertions)]
        {
            let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../..")
                .canonicalize()
                .map_err(|_| {
                    BridgeError::new("service_missing", "The development checkout is missing.")
                })?;
            let python = if cfg!(windows) {
                root.join(".venv/Scripts/python.exe")
            } else {
                root.join(".venv/bin/python")
            };
            command = Command::new(python);
            command
                .args(["-m", observer.as_deref().unwrap_or("hanly_app.service")])
                .current_dir(root);
        }
        #[cfg(not(debug_assertions))]
        {
            return Err(BridgeError::new(
                "service_missing",
                "The packaged desktop service is missing. Reinstall Hanly.",
            ));
        }
    }
    let install_root = if cfg!(target_os = "macos")
        && executable
            .parent()
            .is_some_and(|p| p.file_name().is_some_and(|n| n == "MacOS"))
    {
        executable
            .parent()
            .and_then(|p| p.parent())
            .and_then(|p| p.parent())
            .map(std::path::Path::to_path_buf)
            .unwrap_or_else(|| resource_root.clone())
    } else {
        executable
            .parent()
            .expect("native executable directory")
            .to_path_buf()
    };
    command
        .arg("--installation-root")
        .arg(install_root)
        .arg("--root-pid")
        .arg(std::process::id().to_string());
    for (name, path) in [
        ("--runtime-config", &options.runtime_config),
        ("--app-config", &options.app_config),
    ] {
        if let Some(path) = path {
            command.arg(name).arg(path);
        }
    }
    if let Some(roi) = &options.roi {
        command.args(["--roi", roi]);
    }
    if options.trace {
        command.arg("--trace");
    }
    if let Some(mode) = &options.self_check {
        command.args(["--self-check-mode", mode]);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    Ok(command)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture(script: &str) -> Service {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let python = std::env::var_os("HANLY_TEST_PYTHON")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| {
                if cfg!(windows) {
                    root.join(".venv/Scripts/python.exe")
                } else {
                    root.join(".venv/bin/python")
                }
            });
        let mut command = Command::new(python);
        command.args(["-u", "-c", script]);
        Service::launch(command, Arc::new(|_, _, _| {})).unwrap()
    }

    #[test]
    fn correlates_replies_and_reaps_the_service_on_shutdown() {
        let service = fixture("import sys,json\nfor line in sys.stdin:\n r=json.loads(line)\n print(json.dumps({'version':1,'type':'reply','id':r['id'],'result':{'method':r['method']}}),flush=True)\n if r['method']=='service.shutdown': break");
        assert_eq!(
            service.request("host", "service.hello", json!({})).unwrap()["method"],
            "service.hello"
        );
        service.stop();
        assert!(service.child.lock().unwrap().try_wait().unwrap().is_some());
        assert!(service.request("host", "service.hello", json!({})).is_err());
    }

    #[test]
    fn malformed_output_fails_requests_and_terminates_the_child() {
        let service = fixture(
            "import sys,time\nsys.stdin.readline()\nprint('not JSON',flush=True)\ntime.sleep(10)",
        );
        assert_eq!(
            service
                .request("host", "service.hello", json!({}))
                .unwrap_err()
                .code,
            "protocol_error"
        );
        service.stop();
        assert!(service.child.lock().unwrap().try_wait().unwrap().is_some());
    }

    #[test]
    fn timeout_closes_ambiguous_session_without_orphaning_it() {
        let service = fixture("import sys,time\nsys.stdin.readline()\ntime.sleep(10)");
        let error = service
            .request_with_timeout(
                "host",
                "service.hello",
                json!({}),
                Duration::from_millis(100),
            )
            .unwrap_err();
        assert_eq!(error.code, "service_timeout");
        service.stop();
        assert!(service.child.lock().unwrap().try_wait().unwrap().is_some());
    }

    #[test]
    fn exit_resolves_pending_requests_as_disconnect() {
        let service = fixture("import sys\nsys.stdin.readline()");
        assert_eq!(
            service
                .request("host", "service.hello", json!({}))
                .unwrap_err()
                .code,
            "service_disconnected"
        );
        service.stop();
    }

    #[test]
    fn rejects_non_monotonic_event_order() {
        let service = fixture("import sys,json,time\nr=json.loads(sys.stdin.readline())\ne={'version':1,'type':'event','sequence':1,'event':'state','payload':{}}\nprint(json.dumps(e),flush=True)\nprint(json.dumps(e),flush=True)\ntime.sleep(10)");
        assert_eq!(
            service
                .request("host", "service.hello", json!({}))
                .unwrap_err()
                .code,
            "protocol_error"
        );
        service.stop();
    }
}

#[cfg(test)]
mod integration_tests {
    use super::*;

    #[test]
    fn actual_python_service_matches_the_host_and_keeps_capture_unavailable() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let python = std::env::var_os("HANLY_TEST_PYTHON")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| {
                if cfg!(windows) {
                    root.join(".venv/Scripts/python.exe")
                } else {
                    root.join(".venv/bin/python")
                }
            });
        let profile =
            std::env::temp_dir().join(format!("hanly-service-contract-{}", std::process::id()));
        std::fs::create_dir_all(&profile).unwrap();
        let mut command = Command::new(python);
        command
            .args(["-m", "hanly_app.service", "--app-config"])
            .arg(profile.join("config.json"))
            .current_dir(root);
        let service = Service::launch(command, Arc::new(|_, _, _| {})).unwrap();
        let hello = service.request("host", "service.hello", json!({})).unwrap();
        crate::validate_handshake(hello).unwrap();
        let state = service
            .request("control-center", "get_state", json!({}))
            .unwrap();
        assert_eq!(state["app"]["capture_running"], false);
        assert_eq!(
            service
                .request("control-center", "start_capture", json!({}))
                .unwrap_err()
                .code,
            "unavailable"
        );
        service.stop();
        assert!(service.child.lock().unwrap().try_wait().unwrap().is_some());
        std::fs::remove_dir_all(profile).unwrap();
    }
}
