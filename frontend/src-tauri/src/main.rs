#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    fmt,
    io::{self, Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

use tauri::Manager;

const BACKEND_ADDRESS: &str = "127.0.0.1:8000";
const HEALTH_PATH: &str = "/api/health";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(15);
const POLL_INTERVAL: Duration = Duration::from_millis(100);
const IO_TIMEOUT: Duration = Duration::from_millis(500);

struct BackendPaths {
    backend: PathBuf,
    python: PathBuf,
}

struct BackendCommand {
    executable: PathBuf,
    working_directory: PathBuf,
    arguments: [&'static str; 7],
}

struct BackendSupervisor {
    child: Mutex<Option<Child>>,
    shutting_down: AtomicBool,
}

impl BackendSupervisor {
    fn new() -> Self {
        Self {
            child: Mutex::new(None),
            shutting_down: AtomicBool::new(false),
        }
    }

    fn start_and_wait(&self) -> Result<(), StartupError> {
        ensure_port_is_available()?;
        let paths = resolve_backend_paths(Path::new(env!("CARGO_MANIFEST_DIR")))?;
        let command_spec = backend_command(&paths);
        let mut child = spawn_backend(&command_spec).map_err(|source| StartupError::Spawn {
            executable: command_spec.executable,
            source,
        })?;

        {
            let mut owned = self
                .child
                .lock()
                .map_err(|_| StartupError::SupervisorState)?;
            if owned.is_some() {
                let _ = child.kill();
                let _ = child.wait();
                return Err(StartupError::DuplicateSpawn);
            }
            *owned = Some(child);
        }

        let deadline = Instant::now() + STARTUP_TIMEOUT;
        while Instant::now() < deadline {
            if self.shutting_down.load(Ordering::SeqCst) {
                self.terminate_child();
                return Err(StartupError::Cancelled);
            }

            self.ensure_child_is_running()?;
            if health_check() {
                // Confirm the owned child survived its bind/startup sequence. This prevents
                // accepting a foreign service that won a last-moment race for port 8000.
                thread::sleep(POLL_INTERVAL);
                self.ensure_child_is_running()?;
                return Ok(());
            }
            thread::sleep(POLL_INTERVAL);
        }

        self.terminate_child();
        Err(StartupError::HealthTimeout(STARTUP_TIMEOUT))
    }

    fn ensure_child_is_running(&self) -> Result<(), StartupError> {
        let mut owned = self
            .child
            .lock()
            .map_err(|_| StartupError::SupervisorState)?;
        let child = owned.as_mut().ok_or(StartupError::SupervisorState)?;
        match child.try_wait() {
            Ok(None) => Ok(()),
            Ok(Some(status)) => {
                *owned = None;
                Err(StartupError::EarlyExit(status.code()))
            }
            Err(source) => Err(StartupError::ChildStatus(source)),
        }
    }

    fn shutdown(&self) {
        self.shutting_down.store(true, Ordering::SeqCst);
        self.terminate_child();
    }

    fn terminate_child(&self) {
        let child = self.child.lock().ok().and_then(|mut owned| owned.take());
        if let Some(mut child) = child {
            match child.try_wait() {
                Ok(Some(_)) => {}
                Ok(None) | Err(_) => {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        }
    }
}

#[derive(Debug)]
enum StartupError {
    PortConflict,
    RepositoryLayout(String),
    MissingPython(PathBuf),
    Spawn {
        executable: PathBuf,
        source: io::Error,
    },
    DuplicateSpawn,
    EarlyExit(Option<i32>),
    ChildStatus(io::Error),
    HealthTimeout(Duration),
    SupervisorState,
    Cancelled,
}

impl fmt::Display for StartupError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::PortConflict => write!(
                formatter,
                "Port 8000 is already in use by a process Glacial did not start. Stop that process and restart Glacial."
            ),
            Self::RepositoryLayout(reason) => write!(
                formatter,
                "Glacial could not resolve its backend from the repository layout: {reason}"
            ),
            Self::MissingPython(path) => write!(
                formatter,
                "Glacial's backend Python executable was not found at {}.",
                path.display()
            ),
            Self::Spawn { executable, source } => write!(
                formatter,
                "Glacial could not start {}: {source}",
                executable.display()
            ),
            Self::DuplicateSpawn => write!(formatter, "Glacial refused a duplicate backend start."),
            Self::EarlyExit(Some(code)) => write!(
                formatter,
                "The Glacial backend exited before becoming healthy (exit code {code})."
            ),
            Self::EarlyExit(None) => write!(
                formatter,
                "The Glacial backend exited before becoming healthy."
            ),
            Self::ChildStatus(source) => write!(
                formatter,
                "Glacial could not inspect the backend process: {source}"
            ),
            Self::HealthTimeout(timeout) => write!(
                formatter,
                "The Glacial backend did not pass /api/health within {} seconds.",
                timeout.as_secs()
            ),
            Self::SupervisorState => write!(
                formatter,
                "Glacial could not safely access its backend process state."
            ),
            Self::Cancelled => write!(formatter, "Glacial shut down during backend startup."),
        }
    }
}

fn main() {
    let backend = Arc::new(BackendSupervisor::new());
    let setup_backend = Arc::clone(&backend);

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .setup(move |app| {
            let app_handle = app.handle().clone();
            let startup_backend = Arc::clone(&setup_backend);
            thread::spawn(move || {
                let startup = startup_backend.start_and_wait();
                if matches!(startup, Err(StartupError::Cancelled)) {
                    return;
                }
                if startup.is_err() {
                    startup_backend.terminate_child();
                }

                let error_message = startup.err().map(|error| {
                    let message = error.to_string();
                    eprintln!("Glacial desktop startup failed: {message}");
                    message
                });
                let window_backend = Arc::clone(&startup_backend);
                let main_thread_handle = app_handle.clone();
                if app_handle
                    .run_on_main_thread(move || {
                        if let Err(error) =
                            create_main_window(&main_thread_handle, error_message.as_deref())
                        {
                            eprintln!("Glacial could not create its main window: {error}");
                            window_backend.shutdown();
                            main_thread_handle.exit(1);
                        }
                    })
                    .is_err()
                {
                    startup_backend.shutdown();
                    app_handle.exit(1);
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Glacial desktop application");

    app.run(move |app_handle, event| match event {
        tauri::RunEvent::WindowEvent {
            label,
            event: tauri::WindowEvent::Destroyed,
            ..
        } if label == "main" => {
            backend.shutdown();
            app_handle.exit(0);
        }
        tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit => backend.shutdown(),
        _ => {}
    });
}

fn resolve_backend_paths(manifest_dir: &Path) -> Result<BackendPaths, StartupError> {
    let manifest_dir = manifest_dir.canonicalize().map_err(|error| {
        StartupError::RepositoryLayout(format!("desktop directory is unavailable: {error}"))
    })?;
    let frontend = manifest_dir.parent().ok_or_else(|| {
        StartupError::RepositoryLayout("desktop directory has no frontend parent".to_string())
    })?;
    let repository = frontend
        .parent()
        .ok_or_else(|| {
            StartupError::RepositoryLayout("frontend has no repository parent".to_string())
        })?
        .canonicalize()
        .map_err(|error| {
            StartupError::RepositoryLayout(format!("repository is unavailable: {error}"))
        })?;

    let backend = repository.join("backend");
    let backend = backend.canonicalize().map_err(|error| {
        StartupError::RepositoryLayout(format!("backend directory is unavailable: {error}"))
    })?;
    if !backend.starts_with(&repository) {
        return Err(StartupError::RepositoryLayout(
            "backend directory resolves outside the repository".to_string(),
        ));
    }

    let expected_python = backend.join(".venv").join("Scripts").join("python.exe");
    if !expected_python.is_file() {
        return Err(StartupError::MissingPython(expected_python));
    }
    let python = expected_python.canonicalize().map_err(|error| {
        StartupError::RepositoryLayout(format!("backend Python could not be resolved: {error}"))
    })?;
    if !python.starts_with(&backend) {
        return Err(StartupError::RepositoryLayout(
            "backend Python resolves outside the backend directory".to_string(),
        ));
    }

    Ok(BackendPaths { backend, python })
}

fn backend_command(paths: &BackendPaths) -> BackendCommand {
    BackendCommand {
        executable: paths.python.clone(),
        working_directory: paths.backend.clone(),
        arguments: [
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
    }
}

fn spawn_backend(spec: &BackendCommand) -> io::Result<Child> {
    let mut command = Command::new(&spec.executable);
    command
        .args(spec.arguments)
        .current_dir(&spec.working_directory)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    command.spawn()
}

fn ensure_port_is_available() -> Result<(), StartupError> {
    TcpListener::bind(BACKEND_ADDRESS)
        .map(drop)
        .map_err(|_| StartupError::PortConflict)
}

fn health_check() -> bool {
    let address: SocketAddr = match BACKEND_ADDRESS.parse() {
        Ok(address) => address,
        Err(_) => return false,
    };
    let mut stream = match TcpStream::connect_timeout(&address, IO_TIMEOUT) {
        Ok(stream) => stream,
        Err(_) => return false,
    };
    if stream.set_read_timeout(Some(IO_TIMEOUT)).is_err()
        || stream.set_write_timeout(Some(IO_TIMEOUT)).is_err()
    {
        return false;
    }

    let request = format!(
        "GET {HEALTH_PATH} HTTP/1.1\r\nHost: {BACKEND_ADDRESS}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }

    let mut response = Vec::new();
    if stream.read_to_end(&mut response).is_err() {
        return false;
    }
    valid_health_response(&response)
}

fn valid_health_response(response: &[u8]) -> bool {
    let response = match std::str::from_utf8(response) {
        Ok(response) => response,
        Err(_) => return false,
    };
    let Some((headers, body)) = response.split_once("\r\n\r\n") else {
        return false;
    };
    let Some(status_line) = headers.lines().next() else {
        return false;
    };
    status_line.starts_with("HTTP/1.1 200 ")
        && body
            .chars()
            .filter(|character| !character.is_whitespace())
            .collect::<String>()
            == r#"{"status":"ok"}"#
}

fn create_main_window(app: &tauri::AppHandle, startup_error: Option<&str>) -> tauri::Result<()> {
    let mut window_config = app
        .config()
        .app
        .windows
        .iter()
        .find(|window| window.label == "main")
        .expect("main window configuration is missing")
        .clone();
    if let Some(message) = startup_error {
        window_config.url = tauri::WebviewUrl::App(startup_error_url(message).into());
    }
    tauri::WebviewWindowBuilder::from_config(app, &window_config)?.build()?;
    Ok(())
}

fn startup_error_url(message: &str) -> String {
    let mut url = String::from("startup-error.html?message=");
    for byte in message.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'~') {
            url.push(char::from(byte));
        } else {
            use fmt::Write as _;
            let _ = write!(url, "%{byte:02X}");
        }
    }
    url
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_only_the_expected_health_response() {
        assert!(valid_health_response(
            b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n\r\n{\"status\":\"ok\"}"
        ));
        assert!(!valid_health_response(
            b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n\r\n{\"status\":\"wrong\"}"
        ));
        assert!(!valid_health_response(
            b"HTTP/1.1 503 Service Unavailable\r\n\r\n{\"status\":\"ok\"}"
        ));
    }

    #[test]
    fn backend_command_uses_structured_exact_arguments() {
        let paths = BackendPaths {
            backend: PathBuf::from(r"Z:\repo\backend"),
            python: PathBuf::from(r"Z:\repo\backend\.venv\Scripts\python.exe"),
        };
        let spec = backend_command(&paths);
        assert_eq!(spec.executable, paths.python);
        assert_eq!(spec.working_directory, paths.backend);
        assert_eq!(
            spec.arguments,
            [
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ]
        );
    }

    #[test]
    fn startup_diagnostics_are_percent_encoded_and_use_text_content() {
        let url = startup_error_url("bad </script> & \"quoted\"");
        assert_eq!(
            url,
            "startup-error.html?message=bad%20%3C%2Fscript%3E%20%26%20%22quoted%22"
        );
        let script = include_str!("../../public/startup-error.js");
        assert!(script.contains("detail.textContent"));
        assert!(!script.contains("innerHTML"));
    }

    #[test]
    fn repository_paths_resolve_from_the_tauri_manifest() {
        let paths = resolve_backend_paths(Path::new(env!("CARGO_MANIFEST_DIR"))).unwrap();
        assert!(paths.backend.ends_with("backend"));
        assert!(paths
            .python
            .ends_with(Path::new(r".venv\Scripts\python.exe")));
    }
}
