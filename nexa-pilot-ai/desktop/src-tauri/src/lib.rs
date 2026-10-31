//! NexaPilot desktop shell.
//!
//! The shell owns the backend lifecycle: it reuses an already-running backend on
//! 127.0.0.1:8765 when one exists (useful in development), otherwise it launches
//! the packaged sidecar next to the executable, falling back to `uv run nexapilot`
//! inside a source checkout. The child process is terminated when the window
//! closes so the desktop app never leaves an orphaned server behind.

use std::{
    fs::{self, OpenOptions},
    io::Write,
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::Duration,
};

use tauri::{Manager, RunEvent};

pub const BACKEND_PORT: u16 = 8765;

#[derive(Default)]
struct BackendProcess(Mutex<Option<Child>>);

fn backend_addr() -> SocketAddr {
    SocketAddr::from(([127, 0, 0, 1], BACKEND_PORT))
}

fn backend_reachable() -> bool {
    TcpStream::connect_timeout(&backend_addr(), Duration::from_millis(300)).is_ok()
}

fn data_dir() -> Option<PathBuf> {
    #[cfg(windows)]
    let base = std::env::var_os("APPDATA").map(PathBuf::from);
    #[cfg(target_os = "macos")]
    let base = std::env::var_os("HOME")
        .map(|home| PathBuf::from(home).join("Library/Application Support"));
    #[cfg(all(unix, not(target_os = "macos")))]
    let base = std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".local/share")));
    base.map(|path| path.join("nexapilot"))
}

fn logs_dir() -> Option<PathBuf> {
    let dir = data_dir()?.join("logs");
    fs::create_dir_all(&dir).ok()?;
    Some(dir)
}

fn shell_log(message: &str) {
    eprintln!("nexapilot: {message}");
    if let Some(dir) = logs_dir() {
        if let Ok(mut file) = OpenOptions::new()
            .create(true)
            .append(true)
            .open(dir.join("shell.log"))
        {
            let _ = writeln!(file, "{message}");
        }
    }
}

fn backend_stdio() -> (Stdio, Stdio) {
    let Some(dir) = logs_dir() else {
        return (Stdio::null(), Stdio::null());
    };
    let path = dir.join("backend.log");
    let open = || OpenOptions::new().create(true).append(true).open(&path);
    match (open(), open()) {
        (Ok(out), Ok(err)) => (Stdio::from(out), Stdio::from(err)),
        _ => (Stdio::null(), Stdio::null()),
    }
}

fn watch_backend() {
    std::thread::spawn(|| {
        for attempt in 0..120 {
            if backend_reachable() {
                shell_log(&format!("backend reachable on 127.0.0.1:{BACKEND_PORT}"));
                return;
            }
            if attempt == 0 {
                shell_log("waiting for the backend to start...");
            }
            std::thread::sleep(Duration::from_millis(500));
        }
        shell_log("backend did not become reachable after 60s; see logs/backend.log");
    });
}

fn repo_root() -> Option<PathBuf> {
    if let Ok(value) = std::env::var("NEXAPILOT_REPO_ROOT") {
        let candidate = PathBuf::from(value);
        if candidate.join("backend/pyproject.toml").is_file() {
            return Some(candidate);
        }
    }
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd);
    }
    if let Ok(exe) = std::env::current_exe() {
        candidates.extend(exe.ancestors().map(Path::to_path_buf));
    }
    for start in candidates {
        for dir in start.ancestors() {
            if dir.join("backend/pyproject.toml").is_file() {
                return Some(dir.to_path_buf());
            }
        }
    }
    None
}

fn sidecar_path() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;
    let name = if cfg!(windows) {
        "nexapilot-server.exe"
    } else {
        "nexapilot-server"
    };
    let candidate = dir.join(name);
    candidate.is_file().then_some(candidate)
}

fn launch(command: &mut Command, label: &str) -> Option<Child> {
    let (stdout, stderr) = backend_stdio();
    command
        .env("NEXAPILOT_HOST", "127.0.0.1")
        .env("NEXAPILOT_PORT", BACKEND_PORT.to_string())
        .env("NEXAPILOT_ENVIRONMENT", "production")
        .stdin(Stdio::null())
        .stdout(stdout)
        .stderr(stderr);
    // The PyInstaller sidecar and `uv` are console programs on Windows; without
    // CREATE_NO_WINDOW they attach a black console window to the desktop app.
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    match command.spawn() {
        Ok(child) => {
            shell_log(&format!(
                "started backend via {label} (pid {})",
                child.id()
            ));
            Some(child)
        }
        Err(error) => {
            shell_log(&format!("failed to start backend via {label}: {error}"));
            None
        }
    }
}

fn spawn_backend() -> Option<Child> {
    if backend_reachable() {
        shell_log(&format!(
            "reusing backend already listening on 127.0.0.1:{BACKEND_PORT}"
        ));
        return None;
    }

    if let Ok(bin) = std::env::var("NEXAPILOT_BACKEND_BIN") {
        let path = PathBuf::from(bin);
        if path.is_file() {
            return launch(&mut Command::new(path), "NEXAPILOT_BACKEND_BIN");
        }
        shell_log(&format!(
            "NEXAPILOT_BACKEND_BIN is not a file: {}",
            path.display()
        ));
    }

    if let Some(sidecar) = sidecar_path() {
        return launch(&mut Command::new(sidecar), "bundled sidecar");
    }

    if let Some(root) = repo_root() {
        let backend_dir = root.join("backend");
        return launch(
            Command::new("uv").arg("run").arg("nexapilot").current_dir(&backend_dir),
            "uv (source checkout)",
        );
    }

    shell_log(
        "no backend found. Install the packaged app, set NEXAPILOT_BACKEND_BIN, \
         or run from a source checkout with `uv` on PATH.",
    );
    None
}

pub fn run() {
    let app = tauri::Builder::default()
        .setup(|app| {
            let child = spawn_backend();
            app.manage(BackendProcess(Mutex::new(child)));
            watch_backend();
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build NexaPilot desktop shell");

    app.run(|app_handle, event| {
        if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
            if let Some(state) = app_handle.try_state::<BackendProcess>() {
                if let Ok(mut guard) = state.0.lock() {
                    if let Some(mut child) = guard.take() {
                        shell_log(&format!("stopping backend (pid {})", child.id()));
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        }
    });
}
