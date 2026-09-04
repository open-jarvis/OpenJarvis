use std::sync::Arc;
use std::time::Duration;
use tauri::menu::{MenuBuilder, MenuItemBuilder};
use tauri::tray::TrayIconBuilder;
use tauri::Manager;
use tauri_plugin_autostart::MacosLauncher;
use tokio::sync::Mutex;

const OLLAMA_PORT: u16 = 11434;
const JARVIS_PORT: u16 = 8000;
const DESKTOP_UV_SYNC_COMMAND: &str =
    "uv sync --extra desktop --extra inference-cloud --extra inference-google --group desktop-native";

/// Small, fast model used when startup needs a default Ollama tag.
const STARTUP_MODEL: &str = "qwen3.5:4b";

/// Tiny fallback model if even the startup model can't be pulled.
const FALLBACK_MODEL: &str = "qwen3:0.6b";

/// Qwen3.5 model variants, ordered smallest to largest.
/// Each entry is (ollama_tag, approximate_download_size_gb, min_ram_gb).
const QWEN35_MODELS: &[(&str, f64, f64)] = &[
    ("qwen3.5:0.8b", 1.0, 4.0),
    ("qwen3.5:2b", 2.7, 6.0),
    ("qwen3.5:4b", 3.4, 8.0),
    ("qwen3.5:9b", 6.6, 12.0),
    ("qwen3.5:27b", 17.0, 24.0),
    ("qwen3.5:35b", 24.0, 32.0),
    ("qwen3.5:122b", 81.0, 96.0),
];

/// Get total system RAM in GB.
fn total_ram_gb() -> f64 {
    #[cfg(target_os = "macos")]
    {
        use std::process::Command;
        if let Ok(output) = Command::new("sysctl").args(["-n", "hw.memsize"]).output() {
            if let Ok(s) = String::from_utf8(output.stdout) {
                if let Ok(bytes) = s.trim().parse::<u64>() {
                    return bytes as f64 / (1024.0 * 1024.0 * 1024.0);
                }
            }
        }
    }
    #[cfg(target_os = "linux")]
    {
        if let Ok(contents) = std::fs::read_to_string("/proc/meminfo") {
            for line in contents.lines() {
                if line.starts_with("MemTotal:") {
                    if let Some(kb_str) = line.split_whitespace().nth(1) {
                        if let Ok(kb) = kb_str.parse::<u64>() {
                            return kb as f64 / (1024.0 * 1024.0);
                        }
                    }
                }
            }
        }
    }
    #[cfg(target_os = "windows")]
    {
        use std::process::Command;
        // wmic returns TotalVisibleMemorySize in KB
        if let Ok(output) = Command::new("wmic")
            .args(["OS", "get", "TotalVisibleMemorySize", "/value"])
            .output()
        {
            if let Ok(s) = String::from_utf8(output.stdout) {
                for line in s.lines() {
                    if let Some(val) = line.strip_prefix("TotalVisibleMemorySize=") {
                        if let Ok(kb) = val.trim().parse::<u64>() {
                            return kb as f64 / (1024.0 * 1024.0);
                        }
                    }
                }
            }
        }
    }
    8.0
}

/// Return the Qwen3.5 models that fit in `ram_gb`, smallest first.
fn models_that_fit_in(ram_gb: f64) -> Vec<&'static str> {
    QWEN35_MODELS
        .iter()
        .filter(|(_, _, min_ram)| ram_gb >= *min_ram)
        .map(|(tag, _, _)| *tag)
        .collect()
}

/// The default local model: the second-largest Qwen3.5 model that fits in
/// `ram_gb`. Falls back to the only fitting model, or FALLBACK_MODEL if none
/// fit. Deliberately NOT the largest — leaves RAM headroom for the OS/app.
fn default_local_model(ram_gb: f64) -> &'static str {
    let fitting = models_that_fit_in(ram_gb);
    match fitting.len() {
        0 => FALLBACK_MODEL,
        1 => fitting[0],
        n => fitting[n - 2],
    }
}

/// A resolved boot plan derived purely from the inference config + RAM.
/// Pure and side-effect-free so it can be unit-tested without spawning
/// processes or touching the network.
#[derive(Debug, Clone, PartialEq, Eq)]
struct BootPlan {
    /// Whether to start and wait for the bundled Ollama.
    launch_ollama: bool,
    /// The preferred Ollama model (None for custom endpoints).
    model_to_pull: Option<String>,
    /// Optional `(engine_key, bare_host)` override for a custom endpoint,
    /// e.g. `("lmstudio", "http://localhost:1234")`. Written into
    /// ~/.openjarvis/config.toml so `jarvis serve` picks it up.
    engine_host: Option<(String, String)>,
    /// Args appended after `uv run jarvis serve --port <port>`.
    serve_args: Vec<String>,
}

/// Default OpenAI-compatible engine key used when a custom endpoint config
/// omits one (LM Studio is the canonical local server).
const CUSTOM_FALLBACK_ENGINE: &str = "lmstudio";

/// Decide what to launch/pull/serve from the inference config + system RAM.
/// Pure: no I/O, no spawning.
fn boot_plan(cfg: &InferenceConfig, ram_gb: f64) -> BootPlan {
    match cfg.kind {
        SourceKind::Ollama => {
            let model = cfg
                .model
                .clone()
                .unwrap_or_else(|| default_local_model(ram_gb).to_string());
            BootPlan {
                launch_ollama: true,
                model_to_pull: Some(model.clone()),
                engine_host: None,
                serve_args: vec![
                    "--engine".into(),
                    "ollama".into(),
                    "--model".into(),
                    model,
                    "--agent".into(),
                    "simple".into(),
                ],
            }
        }
        SourceKind::Custom => {
            let engine = cfg
                .engine
                .clone()
                .unwrap_or_else(|| CUSTOM_FALLBACK_ENGINE.to_string());
            // Record (engine_key, bare_host) only when a host is configured, so
            // boot can write `[engine.<key>] host = ...` into config.toml. An
            // empty host is dropped (no override).
            let engine_host = cfg
                .host
                .clone()
                .filter(|h| !h.is_empty())
                .map(|h| (engine.clone(), h));
            // `model` may be empty if the config is malformed; `jarvis serve`
            // surfaces a clear error then (there is no universal default model
            // for an arbitrary endpoint).
            let model = cfg.model.clone().unwrap_or_default();
            BootPlan {
                launch_ollama: false,
                model_to_pull: None,
                engine_host,
                serve_args: vec![
                    "--engine".into(),
                    engine,
                    "--model".into(),
                    model,
                    "--agent".into(),
                    "simple".into(),
                ],
            }
        }
    }
}

/// Get the user home directory, handling both Unix (HOME) and Windows (USERPROFILE).
fn home_dir() -> String {
    std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .unwrap_or_default()
}

/// Resolve full path to a binary by checking common locations.
/// macOS .app bundles don't inherit the shell PATH, so we probe manually.
fn resolve_bin(name: &str) -> String {
    let home = home_dir();

    #[cfg(not(target_os = "windows"))]
    let candidates = vec![
        format!("/opt/homebrew/bin/{name}"),
        format!("{home}/.local/bin/{name}"),
        format!("{home}/.cargo/bin/{name}"),
        format!("/usr/local/bin/{name}"),
        format!("/usr/bin/{name}"),
    ];

    #[cfg(target_os = "windows")]
    let candidates = {
        let localappdata = std::env::var("LOCALAPPDATA").unwrap_or_default();
        let programfiles = std::env::var("ProgramFiles").unwrap_or_default();
        let programfiles_x86 = std::env::var("ProgramFiles(x86)").unwrap_or_default();
        vec![
            // Git for Windows — standard install paths
            format!("{programfiles}\\Git\\cmd\\{name}.exe"),
            format!("{programfiles_x86}\\Git\\cmd\\{name}.exe"),
            format!("{localappdata}\\Programs\\Git\\cmd\\{name}.exe"),
            // Scoop package manager
            format!("{home}\\scoop\\shims\\{name}.exe"),
            // Cargo, local bin
            format!("{home}\\.cargo\\bin\\{name}.exe"),
            format!("{home}\\.local\\bin\\{name}.exe"),
            // Generic program locations
            format!("{localappdata}\\Programs\\{name}\\{name}.exe"),
            format!("{programfiles}\\{name}\\{name}.exe"),
            // Ollama installs to LOCALAPPDATA on Windows
            format!("{localappdata}\\Programs\\Ollama\\{name}.exe"),
            // uv installs via pip/pipx
            format!("{home}\\AppData\\Roaming\\Python\\Scripts\\{name}.exe"),
        ]
    };

    for path in &candidates {
        if std::path::Path::new(path).exists() {
            return path.clone();
        }
    }

    // Fallback: ask the OS to find it on PATH.
    // On Windows this uses `where.exe`, on Unix `which`.
    #[cfg(target_os = "windows")]
    {
        if let Ok(output) = std::process::Command::new("where")
            .arg(format!("{name}.exe"))
            .output()
        {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                if let Some(first_line) = stdout.lines().next() {
                    let p = first_line.trim();
                    if !p.is_empty() && std::path::Path::new(p).exists() {
                        return p.to_string();
                    }
                }
            }
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        if let Ok(output) = std::process::Command::new("which").arg(name).output() {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                if let Some(first_line) = stdout.lines().next() {
                    let p = first_line.trim();
                    if !p.is_empty() && std::path::Path::new(p).exists() {
                        return p.to_string();
                    }
                }
            }
        }
    }

    name.to_string()
}

/// Find the OpenJarvis project root (contains pyproject.toml).
/// Checks OPENJARVIS_ROOT env var, walks up from the executable, then
/// probes common clone locations.
fn find_project_root() -> Option<std::path::PathBuf> {
    // 1. Explicit env var override
    if let Ok(root) = std::env::var("OPENJARVIS_ROOT") {
        let path = std::path::PathBuf::from(&root);
        if path.join("pyproject.toml").exists() {
            return Some(path);
        }
    }

    // 2. Walk up from the running executable (works in dev and .app bundle)
    if let Ok(exe) = std::env::current_exe() {
        let mut dir = exe.parent().map(|p| p.to_path_buf());
        for _ in 0..8 {
            if let Some(ref d) = dir {
                if d.join("pyproject.toml").exists() {
                    return Some(d.clone());
                }
                dir = d.parent().map(|p| p.to_path_buf());
            }
        }
    }

    // 3. Fallback: well-known direct paths
    let home = home_dir();
    let direct = [
        format!("{home}/OpenJarvis"),
        format!("{home}/projects/hazy/OpenJarvis"),
        format!("{home}/projects/OpenJarvis"),
        format!("{home}/src/OpenJarvis"),
        format!("{home}/Documents/OpenJarvis"),
        format!("{home}/Desktop/OpenJarvis"),
        format!("{home}/Developer/OpenJarvis"),
        format!("{home}/dev/OpenJarvis"),
        format!("{home}/Code/OpenJarvis"),
        format!("{home}/code/OpenJarvis"),
        format!("{home}/repos/OpenJarvis"),
        format!("{home}/github/OpenJarvis"),
    ];
    for p in &direct {
        let path = std::path::PathBuf::from(p);
        if path.join("pyproject.toml").exists() {
            return Some(path);
        }
    }

    // 4. Shallow scan: look for OpenJarvis one level inside common parent dirs.
    //    This catches clones like ~/Documents/my-stuff/OpenJarvis without
    //    needing to enumerate every possible intermediate folder.
    let scan_parents = [
        format!("{home}/Documents"),
        format!("{home}/Desktop"),
        format!("{home}/Developer"),
        format!("{home}/projects"),
        format!("{home}/repos"),
        format!("{home}/src"),
        format!("{home}/Code"),
        format!("{home}/code"),
        format!("{home}/dev"),
        format!("{home}/github"),
    ];
    for parent in &scan_parents {
        let parent_path = std::path::PathBuf::from(parent);
        if let Ok(entries) = std::fs::read_dir(&parent_path) {
            for entry in entries.flatten() {
                let candidate = entry.path().join("OpenJarvis");
                if candidate.join("pyproject.toml").exists() {
                    return Some(candidate);
                }
                // Also check if the entry itself is OpenJarvis (case-insensitive match)
                if let Some(name) = entry.file_name().to_str() {
                    if name.eq_ignore_ascii_case("openjarvis")
                        && entry.path().join("pyproject.toml").exists()
                    {
                        return Some(entry.path());
                    }
                }
            }
        }
    }

    None
}

// ---------------------------------------------------------------------------
// BackendManager — owns the Ollama + Jarvis server child processes
// ---------------------------------------------------------------------------

struct ChildHandle {
    child: tokio::process::Child,
}

impl ChildHandle {
    async fn kill(&mut self) {
        let _ = self.child.kill().await;
    }
}

/// Spawn a subprocess whose lifetime cannot escape the async operation that
/// created it.  Tokio's default is `kill_on_drop(false)`, which means aborting
/// the boot task in the small window between `spawn()` and storing the child in
/// `BackendManager` would detach it.  The same default also lets one-shot boot
/// commands (`git clone`, `uv sync`, extension verification) continue after a
/// source reset.  Every subprocess on the boot path must opt in here (or call
/// `kill_on_drop(true)` before `output()`).
fn spawn_owned_child(cmd: &mut tokio::process::Command) -> std::io::Result<tokio::process::Child> {
    cmd.kill_on_drop(true);
    cmd.spawn()
}

/// Rolling buffer holding the most recent ~16 KB of jarvis stderr.
///
/// Populated by a background drainer task spawned at boot so the pipe
/// never fills and back-pressures `jarvis serve`; consumed by the boot
/// path when surfacing failure messages.
type StderrTail = Arc<Mutex<Vec<u8>>>;

const STDERR_TAIL_LIMIT: usize = 16 * 1024;

struct BackendManager {
    ollama: Option<ChildHandle>,
    jarvis: Option<ChildHandle>,
    jarvis_stderr_tail: StderrTail,
    boot_task: Option<tauri::async_runtime::JoinHandle<()>>,
}

impl Default for BackendManager {
    fn default() -> Self {
        Self {
            ollama: None,
            jarvis: None,
            jarvis_stderr_tail: Arc::new(Mutex::new(Vec::new())),
            boot_task: None,
        }
    }
}

impl BackendManager {
    async fn stop_all(&mut self) {
        if let Some(task) = self.boot_task.take() {
            task.abort();
            // `abort()` only requests cancellation.  Await it before touching
            // children or returning so the boot future has dropped any local,
            // not-yet-registered child and cannot write config after reset.
            let _ = task.await;
        }
        if let Some(ref mut h) = self.jarvis {
            h.kill().await;
        }
        self.jarvis = None;
        if let Some(ref mut h) = self.ollama {
            h.kill().await;
        }
        self.ollama = None;
    }
}

type SharedBackend = Arc<Mutex<BackendManager>>;

/// Spawn exactly one tracked boot task. Keeping its handle lets recovery
/// abort an in-flight endpoint check/model download before killing children.
async fn start_managed_boot(backend: SharedBackend, status: SharedStatus) {
    let mut manager = backend.lock().await;
    if let Some(task) = manager.boot_task.take() {
        task.abort();
        let _ = task.await;
    }
    let task_backend = backend.clone();
    let task = tauri::async_runtime::spawn(boot_backend(task_backend, status));
    manager.boot_task = Some(task);
}

// ---------------------------------------------------------------------------
// Setup status (reported to frontend)
// ---------------------------------------------------------------------------

#[derive(serde::Serialize, Clone)]
struct SetupStatus {
    phase: String,
    detail: String,
    ollama_ready: bool,
    server_ready: bool,
    model_ready: bool,
    error: Option<String>,
    /// "unconfigured" | "ollama" | "custom" — lets the setup UI choose
    /// between the consent screen and source-aware progress labels.
    source: String,
    /// A fresh desktop install must collect an explicit source choice before
    /// any inference process is allowed to start.
    requires_source: bool,
}

impl Default for SetupStatus {
    fn default() -> Self {
        Self {
            phase: "awaiting_source".into(),
            detail: "Choose where OpenJarvis should run models.".into(),
            ollama_ready: false,
            server_ready: false,
            model_ready: false,
            error: None,
            source: "unconfigured".into(),
            requires_source: true,
        }
    }
}

impl SetupStatus {
    fn starting(cfg: &InferenceConfig) -> Self {
        Self {
            phase: "starting".into(),
            detail: "Initializing...".into(),
            source: match cfg.kind {
                SourceKind::Ollama => "ollama",
                SourceKind::Custom => "custom",
            }
            .into(),
            requires_source: false,
            ..Self::default()
        }
    }
}

type SharedStatus = Arc<Mutex<SetupStatus>>;

// ---------------------------------------------------------------------------
// Health-check helpers
// ---------------------------------------------------------------------------

async fn wait_for_url(url: &str, timeout: Duration) -> bool {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .unwrap();
    let deadline = tokio::time::Instant::now() + timeout;
    while tokio::time::Instant::now() < deadline {
        if let Ok(resp) = client.get(url).send().await {
            if resp.status().is_success() {
                return true;
            }
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    false
}

/// True if a custom OpenAI-compatible endpoint answers at all (any HTTP
/// status counts — even a 404 proves the server is up). `host` is the bare
/// base URL; we probe `<host>/v1/models`.
async fn endpoint_reachable(host: &str, timeout: Duration) -> bool {
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(3))
        .build()
    {
        Ok(c) => c,
        Err(_) => return false,
    };
    let url = format!("{}/v1/models", host.trim_end_matches('/'));
    let deadline = tokio::time::Instant::now() + timeout;
    while tokio::time::Instant::now() < deadline {
        if client.get(&url).send().await.is_ok() {
            return true;
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    false
}

/// Outcome of waiting for `jarvis serve` to become healthy.
///
/// Unlike [`wait_for_url`] this differentiates "server is up but degraded"
/// (HTTP 503 — usually inference engine failed to load) from "server never
/// came up" and from "child process died before serving anything", because
/// each needs a different user-facing message.
#[derive(Debug)]
enum JarvisStartResult {
    /// `/health` returned 2xx.
    Ready,
    /// Server replied 503. The body is the actionable message (typically
    /// "engine not ready" or a model-load error).
    ServiceUnavailable(String),
    /// The `jarvis serve` child exited before `/health` returned 2xx.
    EarlyExit { code: Option<i32>, stderr: String },
    /// Deadline elapsed without ever seeing 2xx or an early exit.
    Timeout,
}

/// Spawn a detached task that continuously drains `jarvis serve`'s
/// stderr into a rolling tail buffer.
///
/// We MUST keep reading stderr for as long as the child runs — `jarvis
/// serve` is chatty (engine load progress, request logs), and the OS
/// pipe buffer is small (4 KB on Windows, 64 KB on Linux). Once full,
/// the child's next stderr write blocks indefinitely and the server
/// hangs mid-operation. The drainer reads in chunks and keeps only the
/// last `STDERR_TAIL_LIMIT` bytes — enough to surface a tail trace if
/// the child later dies, without unbounded memory growth.
///
/// Returns immediately after spawning the task; the task ends naturally
/// when the child closes stderr (i.e. exits).
fn spawn_jarvis_stderr_drainer(mut stderr: tokio::process::ChildStderr, tail: StderrTail) {
    use tokio::io::AsyncReadExt;
    tokio::spawn(async move {
        let mut buf = vec![0u8; 4096];
        loop {
            match stderr.read(&mut buf).await {
                Ok(0) => break,  // EOF — child closed stderr
                Err(_) => break, // pipe broke — also done
                Ok(n) => {
                    let mut t = tail.lock().await;
                    t.extend_from_slice(&buf[..n]);
                    if t.len() > STDERR_TAIL_LIMIT {
                        let drop_n = t.len() - STDERR_TAIL_LIMIT;
                        t.drain(..drop_n);
                    }
                }
            }
        }
    });
}

/// Read whatever the stderr drainer has buffered so far.
///
/// Safe to call at any time; returns an empty string before the
/// drainer has seen any bytes. Trimmed.
async fn read_jarvis_stderr_tail(backend: &SharedBackend) -> String {
    let tail = backend.lock().await.jarvis_stderr_tail.clone();
    let bytes = tail.lock().await.clone();
    String::from_utf8_lossy(&bytes).trim().to_string()
}

/// Poll `jarvis serve` health, watching the child process state so we
/// never wait 10 minutes for a process that crashed in the first second.
async fn wait_for_jarvis_health(
    url: &str,
    timeout: Duration,
    backend: &SharedBackend,
) -> JarvisStartResult {
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
    {
        Ok(c) => c,
        Err(_) => return JarvisStartResult::Timeout,
    };
    let deadline = tokio::time::Instant::now() + timeout;
    loop {
        // 1. Has the child already exited? `try_wait` is non-blocking; on
        // Windows where uv / python / the Rust extension can fail to load
        // very fast, this catches the crash within ~500ms instead of after
        // the full HTTP timeout window.
        let exit_status = {
            let mut mgr = backend.lock().await;
            match mgr.jarvis.as_mut() {
                Some(h) => h.child.try_wait().ok().flatten(),
                None => None,
            }
        };
        if let Some(status) = exit_status {
            let stderr = read_jarvis_stderr_tail(backend).await;
            return JarvisStartResult::EarlyExit {
                code: status.code(),
                stderr,
            };
        }

        // 2. Try the health endpoint.
        match client.get(url).send().await {
            Ok(resp) => {
                let status = resp.status();
                if status.is_success() {
                    return JarvisStartResult::Ready;
                }
                if status == reqwest::StatusCode::SERVICE_UNAVAILABLE {
                    // Server is up but the inference engine is not. This
                    // is a terminal-for-us state — polling won't change
                    // anything; the user has to fix their engine config.
                    let body = resp.text().await.unwrap_or_default();
                    return JarvisStartResult::ServiceUnavailable(body);
                }
                // Other non-2xx (e.g. 404 during a brief routing-table
                // warmup window) — fall through and keep polling.
            }
            Err(_) => {
                // Connection refused / DNS / timeout — server still
                // booting. Keep polling.
            }
        }

        if tokio::time::Instant::now() >= deadline {
            return JarvisStartResult::Timeout;
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}

async fn ollama_has_model(model: &str) -> bool {
    let models = ollama_model_names().await;
    matching_installed_model(&models, model).is_some()
}

fn parse_ollama_model_names(body: &serde_json::Value) -> Vec<String> {
    body.get("models")
        .and_then(|m| m.as_array())
        .map(|models| {
            models
                .iter()
                .filter_map(|m| {
                    m.get("name")
                        .or_else(|| m.get("model"))
                        .and_then(|n| n.as_str())
                })
                .filter(|name| !name.trim().is_empty())
                .map(|name| name.to_string())
                .collect()
        })
        .unwrap_or_default()
}

fn model_names_match(installed: &str, requested: &str) -> bool {
    installed == requested
        || installed.strip_suffix(":latest") == Some(requested)
        || requested.strip_suffix(":latest") == Some(installed)
}

fn matching_installed_model(models: &[String], requested: &str) -> Option<String> {
    models
        .iter()
        .find(|model| model_names_match(model, requested))
        .cloned()
}

fn model_name_looks_embedding_only(model: &str) -> bool {
    let name = model.to_ascii_lowercase();
    [
        "embed",
        "embedding",
        "rerank",
        "minilm",
        "bge-",
        "bge_",
        "e5-",
        "e5_",
    ]
    .iter()
    .any(|marker| name.contains(marker))
}

fn preferred_installed_model(models: &[String]) -> Option<String> {
    models
        .iter()
        .find(|model| !model.trim().is_empty() && !model_name_looks_embedding_only(model))
        .or_else(|| models.iter().find(|model| !model.trim().is_empty()))
        .cloned()
}

fn startup_installed_model(requested_model: &str, installed_models: &[String]) -> Option<String> {
    matching_installed_model(installed_models, requested_model)
        .or_else(|| preferred_installed_model(installed_models))
}

fn should_persist_resolved_model(cfg: &InferenceConfig) -> bool {
    cfg.model
        .as_deref()
        .map(|model| model.trim().is_empty())
        .unwrap_or(true)
}

async fn ollama_model_names() -> Vec<String> {
    let url = format!("http://127.0.0.1:{}/api/tags", OLLAMA_PORT);
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .unwrap();
    if let Ok(resp) = client.get(&url).send().await {
        if let Ok(body) = resp.json::<serde_json::Value>().await {
            return parse_ollama_model_names(&body);
        }
    }
    Vec::new()
}

async fn pull_model(model: &str) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{}/api/pull", OLLAMA_PORT);
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(600))
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client
        .post(&url)
        .json(&serde_json::json!({"name": model, "stream": false}))
        .send()
        .await
        .map_err(|e| format!("Pull request failed: {}", e))?;
    if !resp.status().is_success() {
        return Err(format!("Pull returned status {}", resp.status()));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// uv sync error formatting (pure helpers — unit-tested, see #331)
// ---------------------------------------------------------------------------

/// Last `max_chars` characters of a `uv sync` stderr stream, trimmed.
///
/// uv's actionable diagnostic almost always lands at the tail of the
/// stream, so when surfacing a failure to the user we show the end, not
/// the (usually noisy progress-spinner) beginning. Operates on `char`
/// boundaries so it never splits a multi-byte UTF-8 codepoint — important
/// because Windows consoles emit non-ASCII (cp9xx) bytes.
fn uv_sync_stderr_tail(stderr: &str, max_chars: usize) -> String {
    let total = stderr.chars().count();
    let skip = total.saturating_sub(max_chars);
    stderr
        .chars()
        .skip(skip)
        .collect::<String>()
        .trim()
        .to_string()
}

/// Error message shown when `uv sync` runs but exits non-zero (#331).
///
/// `exit_code` is `None` when the process was terminated by a signal with
/// no exit code (rendered as "unknown" rather than a misleading -1).
fn format_uv_sync_failure(root: &std::path::Path, exit_code: Option<i32>, stderr: &str) -> String {
    let code = exit_code
        .map(|c| c.to_string())
        .unwrap_or_else(|| "unknown".to_string());
    let tail = uv_sync_stderr_tail(stderr, 800);
    let rust_hint = if looks_like_rust_extension_build_error(stderr) {
        format!("\n\n{}", rust_toolchain_install_hint())
    } else {
        String::new()
    };
    format!(
        "`uv sync` failed in {} (exit {}). Last output:\n\n{}\n\n\
         Try opening a terminal in that directory and running \
         `{}` manually for the full output.{}",
        root.display(),
        code,
        tail,
        DESKTOP_UV_SYNC_COMMAND,
        rust_hint,
    )
}

/// Strip AppImage-injected environment from a subprocess command (#455).
///
/// When the OpenJarvis desktop binary is shipped as an AppImage, the AppImage
/// runtime sets `LD_LIBRARY_PATH` (and friends) to the extracted-to-/tmp
/// bundled lib dir. Any child we spawn inherits that env by default — but the
/// children we spawn (`uv`, `ollama`, `git`) live outside the AppImage and
/// must NOT load their shared libraries from the AppImage's bundle. The
/// classic symptom: `uv` finds `python3`, `python3` tries to `import numpy`,
/// numpy's `.so` files try to dlopen libstdc++/libssl/libcrypto, the linker
/// picks the AppImage's versions which were built against a different glibc
/// or libcrypto API, and python dies silently — before any startup log
/// reaches us. The user sees "API Server — starting server..." forever.
///
/// Fix: when we detect we're inside an AppImage (the AppImage runtime sets
/// `$APPIMAGE` to the original image path), strip the leaked env vars before
/// spawn. Conditional on `APPIMAGE` being set so regular Linux installs that
/// legitimately use `LD_LIBRARY_PATH` are untouched. Linux-only — the
/// `#[cfg]` makes this a no-op on macOS / Windows.
#[cfg_attr(not(target_os = "linux"), allow(unused_variables))]
fn prepare_subprocess_for_appimage(cmd: &mut tokio::process::Command) {
    #[cfg(target_os = "linux")]
    {
        if std::env::var_os("APPIMAGE").is_some() {
            cmd.env_remove("LD_LIBRARY_PATH");
            cmd.env_remove("LD_PRELOAD");
            cmd.env_remove("APPIMAGE");
            cmd.env_remove("APPIMAGE_UUID");
            cmd.env_remove("APPDIR");
            cmd.env_remove("ARGV0");
        }
    }
}

/// Error message shown when `uv sync` can't even be spawned (#331) —
/// e.g. the resolved `uv` binary doesn't exist or isn't executable.
fn format_uv_sync_spawn_error(root: &std::path::Path, uv_bin: &str, err: &str) -> String {
    format!(
        "Could not run `uv sync`: {}. Verify uv is installed at \
         `{}` and the OpenJarvis repo is at `{}`.",
        err,
        uv_bin,
        root.display(),
    )
}

fn rust_toolchain_install_hint() -> &'static str {
    "The desktop app needs the Rust toolchain to build `openjarvis_rust`. \
     Install Rust from https://rustup.rs. On Windows, also install Visual Studio \
     Build Tools with the C++ workload, then relaunch."
}

fn looks_like_rust_extension_build_error(stderr: &str) -> bool {
    let lower = stderr.to_ascii_lowercase();
    [
        "openjarvis-rust",
        "openjarvis_rust",
        "maturin",
        "cargo",
        "rustc",
        "link.exe",
        "visual studio",
    ]
    .iter()
    .any(|marker| lower.contains(marker))
}

fn format_missing_rust_toolchain() -> String {
    format!(
        "Could not find Rust's `cargo` command. {}\n\n\
         If Rust is already installed, close and relaunch the desktop app so \
         PATH includes `~/.cargo/bin`.",
        rust_toolchain_install_hint(),
    )
}

fn format_extension_import_failure(root: &std::path::Path, stderr: &str) -> String {
    let tail = uv_sync_stderr_tail(stderr, 4000);
    format!(
        "`openjarvis_rust` is still not importable after building. Last output:\n\n{}\n\n\
         Run these manually for the full build log:\n\n\
           cd {}\n\
           {}\n\
           uv run python -c \"import openjarvis_rust\"",
        if tail.is_empty() {
            "(no stderr output)"
        } else {
            &tail
        },
        root.display(),
        DESKTOP_UV_SYNC_COMMAND,
    )
}

fn add_cargo_bin_to_path(cmd: &mut tokio::process::Command) {
    let mut paths: Vec<std::path::PathBuf> = std::env::var_os("PATH")
        .map(|path| std::env::split_paths(&path).collect())
        .unwrap_or_default();
    paths.insert(
        0,
        std::path::PathBuf::from(home_dir())
            .join(".cargo")
            .join("bin"),
    );
    if let Ok(joined) = std::env::join_paths(paths) {
        cmd.env("PATH", joined);
    }
}

async fn verify_openjarvis_rust_extension(
    root: &std::path::Path,
    uv_bin: &str,
) -> Result<(), String> {
    let mut cmd = tokio::process::Command::new(uv_bin);
    cmd.args(["run", "python", "-c", "import openjarvis_rust"])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        .current_dir(root);
    prepare_subprocess_for_appimage(&mut cmd);
    add_cargo_bin_to_path(&mut cmd);
    cmd.kill_on_drop(true);

    match cmd.output().await {
        Ok(out) if out.status.success() => Ok(()),
        Ok(out) => {
            let stderr = String::from_utf8_lossy(&out.stderr);
            Err(format_extension_import_failure(root, &stderr))
        }
        Err(e) => Err(format!(
            "Could not verify `openjarvis_rust`: {}. Verify uv is installed at `{}`.",
            e, uv_bin
        )),
    }
}

fn port_owner_hint() -> String {
    if cfg!(target_os = "windows") {
        format!("netstat -ano | findstr :{}", JARVIS_PORT)
    } else {
        format!("lsof -i :{}", JARVIS_PORT)
    }
}

fn format_port_unavailable(port: u16, reason: &str) -> String {
    format!(
        "Port {} is not available: {}. Stop the process using that port or \
         change the OpenJarvis port, then relaunch.\n\nTo identify it:\n  {}",
        port,
        reason,
        port_owner_hint(),
    )
}

fn check_jarvis_port_available() -> Result<(), String> {
    match std::net::TcpListener::bind(("127.0.0.1", JARVIS_PORT)) {
        Ok(listener) => {
            drop(listener);
            Ok(())
        }
        Err(err) => Err(format_port_unavailable(JARVIS_PORT, &err.to_string())),
    }
}

// ---------------------------------------------------------------------------
// Backend boot sequence (runs in background after app launch)
// ---------------------------------------------------------------------------

async fn boot_backend(backend: SharedBackend, status: SharedStatus) {
    // Never infer consent from a missing or malformed config. A fresh desktop
    // install must persist an explicit source choice before this function can
    // launch Ollama, contact a custom endpoint, or download a model.
    let Some(mut cfg) = read_configured_inference_config() else {
        *status.lock().await = SetupStatus::default();
        return;
    };
    let mut pending_rollback = PendingInferenceRollback::new(&cfg);
    let plan = boot_plan(&cfg, total_ram_gb());
    {
        let mut s = status.lock().await;
        *s = SetupStatus::starting(&cfg);
        s.source = match cfg.kind {
            SourceKind::Ollama => "ollama",
            SourceKind::Custom => "custom",
        }
        .into();
    }

    // For the Ollama path, model resolution may fall back to FALLBACK_MODEL; we
    // record what is actually available here so the serve command below uses
    // it instead of the originally-planned tag. None on the custom path.
    let mut serve_model_override: Option<String> = None;

    if plan.launch_ollama {
        // Phase 1: Start Ollama
        {
            let mut s = status.lock().await;
            s.phase = "ollama".into();
            s.detail = "Starting inference engine...".into();
        }

        // Try the bundled sidecar first, fall back to system ollama
        let ollama_child = {
            let ollama_bin = resolve_bin("ollama");
            let mut sidecar_cmd = tokio::process::Command::new(&ollama_bin);
            sidecar_cmd
                .arg("serve")
                .env("OLLAMA_HOST", format!("127.0.0.1:{}", OLLAMA_PORT))
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null());
            // Avoid LD_LIBRARY_PATH leak when running inside an AppImage (#455).
            prepare_subprocess_for_appimage(&mut sidecar_cmd);
            match spawn_owned_child(&mut sidecar_cmd) {
                Ok(child) => Some(child),
                Err(_) => None,
            }
        };

        if let Some(child) = ollama_child {
            backend.lock().await.ollama = Some(ChildHandle { child });
        }

        let ollama_url = format!("http://127.0.0.1:{}/api/tags", OLLAMA_PORT);
        if !wait_for_url(&ollama_url, Duration::from_secs(30)).await {
            let mut s = status.lock().await;
            s.error = Some("Could not start Ollama. Install it from https://ollama.com".into());
            return;
        }

        {
            let mut s = status.lock().await;
            s.ollama_ready = true;
            s.detail = "Inference engine ready.".into();
        }

        // Phase 2: Resolve one model to serve. Prefer an installed model on
        // first run so startup does not depend on a download succeeding.
        let model = plan
            .model_to_pull
            .clone()
            .unwrap_or_else(|| STARTUP_MODEL.to_string());
        {
            let mut s = status.lock().await;
            s.phase = "model".into();
            s.detail = format!("Checking for {}...", model);
        }

        let installed_models = ollama_model_names().await;
        let resolved_model = if let Some(installed) =
            startup_installed_model(&model, &installed_models)
        {
            installed
        } else {
            {
                let mut s = status.lock().await;
                s.detail = format!("Downloading {}... (this may take a minute)", model);
            }
            match pull_model(&model).await {
                Ok(()) => model.clone(),
                Err(e) => {
                    eprintln!("Warning: failed to pull {}: {}", model, e);

                    // If a local model appeared while pulling, use it instead of
                    // making startup depend on another network pull.
                    if let Some(installed) = preferred_installed_model(&ollama_model_names().await)
                    {
                        installed
                    } else if ollama_has_model(FALLBACK_MODEL).await {
                        FALLBACK_MODEL.to_string()
                    } else {
                        {
                            let mut s = status.lock().await;
                            s.detail = format!("Downloading {}...", FALLBACK_MODEL);
                        }
                        if let Err(e2) = pull_model(FALLBACK_MODEL).await {
                            if let Some(installed) =
                                preferred_installed_model(&ollama_model_names().await)
                            {
                                installed
                            } else {
                                let mut s = status.lock().await;
                                s.error = Some(format!("Failed to download model: {}", e2));
                                return;
                            }
                        } else {
                            FALLBACK_MODEL.to_string()
                        }
                    }
                }
            }
        };

        if resolved_model != model {
            let mut s = status.lock().await;
            s.detail = format!("Using installed model {}.", resolved_model);
        }

        serve_model_override = Some(resolved_model.clone());

        // Persist only first-run/default resolution. If the user explicitly
        // configured a model, do not overwrite that choice with a temporary
        // fallback selected just to keep startup nonfatal.
        if should_persist_resolved_model(&cfg) {
            let mut persisted = cfg.clone();
            persisted.model = Some(resolved_model);
            if write_inference_config(&persisted).is_ok() {
                cfg = persisted;
            }
        }

        {
            let mut s = status.lock().await;
            s.model_ready = true;
            s.detail = "Model ready.".into();
        }
    } else {
        // Custom OpenAI-compatible endpoint: never start Ollama, never download.
        let host = plan
            .engine_host
            .as_ref()
            .map(|(_, v)| v.clone())
            .unwrap_or_default();
        {
            let mut s = status.lock().await;
            s.phase = "model".into();
            s.detail = format!("Connecting to {}...", host);
        }
        if host.is_empty() || !endpoint_reachable(&host, Duration::from_secs(15)).await {
            let mut s = status.lock().await;
            s.error = Some(format!(
                "Could not reach your custom inference server at {}. \
                 Start the server (e.g. LM Studio), or choose Change inference source below.",
                if host.is_empty() {
                    "(no URL set)"
                } else {
                    host.as_str()
                }
            ));
            return;
        }
        // Point `jarvis serve` at the user's endpoint by writing the engine
        // host into ~/.openjarvis/config.toml (the env var alone is shadowed by
        // the engine's non-empty default host in the Python layer).
        if let Some((engine, host)) = &plan.engine_host {
            if let Err(e) = set_engine_host_in_config(engine, host) {
                let mut s = status.lock().await;
                s.error = Some(format!("Could not write engine config: {}", e));
                return;
            }
        }
        {
            let mut s = status.lock().await;
            s.ollama_ready = true;
            s.model_ready = true;
            s.detail = "Connected to custom endpoint.".into();
        }
    }

    // Phase 3: Start jarvis serve
    {
        let mut s = status.lock().await;
        s.phase = "server".into();
        s.detail = "Starting API server...".into();
    }

    let uv_bin = resolve_bin("uv");

    // Verify uv is actually installed. Concrete per-OS instructions —
    // the generic "install it from astral.sh" was the #1 source of
    // confusion on the Discord support thread; users couldn't tell whether
    // to use winget, scoop, pip, or the official installer.
    if !std::path::Path::new(&uv_bin).exists() && uv_bin == "uv" {
        let mut s = status.lock().await;
        #[cfg(target_os = "windows")]
        let msg = "Could not find 'uv' (Python package manager). \
                   To install on Windows, open PowerShell and run:\n\n\
                   powershell -ExecutionPolicy Bypass -c \"irm https://astral.sh/uv/install.ps1 | iex\"\n\n\
                   Then close and relaunch this app. \
                   (If the install completes but the app still can't find uv, \
                   you may need to log out and back in so PATH refreshes.)";
        #[cfg(target_os = "macos")]
        let msg = "Could not find 'uv' (Python package manager). \
                   To install on macOS, open Terminal and run:\n\n\
                   curl -LsSf https://astral.sh/uv/install.sh | sh\n\n\
                   Then relaunch this app.";
        #[cfg(target_os = "linux")]
        let msg = "Could not find 'uv' (Python package manager). \
                   To install on Linux, open a terminal and run:\n\n\
                   curl -LsSf https://astral.sh/uv/install.sh | sh\n\n\
                   Then relaunch this app.";
        #[cfg(not(any(target_os = "windows", target_os = "macos", target_os = "linux")))]
        let msg = "Could not find 'uv' (Python package manager). \
                   Install it from https://astral.sh/uv then relaunch.";
        s.error = Some(msg.into());
        return;
    }

    let mut project_root = find_project_root();

    if project_root.is_none() {
        // Auto-clone on first launch
        let git_bin = resolve_bin("git");

        // Check that git is installed
        if !std::path::Path::new(&git_bin).exists() && git_bin == "git" {
            let mut s = status.lock().await;
            s.error = Some(
                "Could not find 'git'. \
                 Install it from https://git-scm.com then relaunch."
                    .into(),
            );
            return;
        }

        let target_path = std::path::PathBuf::from(home_dir()).join("OpenJarvis");
        let clone_target = target_path.display().to_string();

        // If the directory exists but is not a valid project, don't overwrite
        if target_path.exists() && !target_path.join("pyproject.toml").exists() {
            let mut s = status.lock().await;
            s.error = Some(format!(
                "{} exists but is not a valid OpenJarvis project. \
                 Remove it and relaunch, or set OPENJARVIS_ROOT to the correct path.",
                clone_target,
            ));
            return;
        }

        {
            let mut s = status.lock().await;
            s.detail = "Downloading OpenJarvis (first launch)...".into();
        }

        let mut clone_cmd = tokio::process::Command::new(&git_bin);
        clone_cmd
            .args([
                "clone",
                "--depth",
                "1",
                "https://github.com/open-jarvis/OpenJarvis.git",
                &clone_target,
            ])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::piped());
        prepare_subprocess_for_appimage(&mut clone_cmd);
        let clone_result = spawn_owned_child(&mut clone_cmd);

        match clone_result {
            Ok(child) => match child.wait_with_output().await {
                Ok(output) if output.status.success() => {
                    project_root = Some(target_path);
                }
                Ok(output) => {
                    let stderr = String::from_utf8_lossy(&output.stderr);
                    let mut s = status.lock().await;
                    s.error = Some(format!(
                        "Failed to download OpenJarvis: {}. \
                         Clone manually: git clone https://github.com/open-jarvis/OpenJarvis.git {}",
                        stderr.trim(),
                        clone_target,
                    ));
                    return;
                }
                Err(e) => {
                    let mut s = status.lock().await;
                    s.error = Some(format!(
                        "Failed to download OpenJarvis: {}. \
                         Clone manually: git clone https://github.com/open-jarvis/OpenJarvis.git {}",
                        e, clone_target,
                    ));
                    return;
                }
            },
            Err(e) => {
                let mut s = status.lock().await;
                s.error = Some(format!(
                    "Could not run git: {}. \
                     Install git from https://git-scm.com then relaunch.",
                    e,
                ));
                return;
            }
        }
    }

    // If something is already serving on our port, decide what to do based
    // on what it actually responds with — don't blindly kill it (#455).
    //
    // The OLD behaviour was: any HTTP response (even 404) → `fuser -k 8000/tcp`
    // / `taskkill /PID /F`. That broke the legitimate case where a user had
    // already started `jarvis serve` in a terminal and then launched the
    // desktop app — the app killed their server, then raced to spawn its
    // own, sometimes losing the race and hanging.
    //
    // New behaviour, by response shape:
    //   * 2xx /health        — healthy jarvis serve. Attach to it; skip the
    //                          uv-sync + spawn dance entirely. Done.
    //   * 503                — server is up but engine isn't ready. Surface
    //                          an actionable message; don't kill (matches
    //                          our wait_for_jarvis_health 503 contract).
    //   * any other status   — something else is listening on the port. Tell
    //                          the user via the error banner instead of
    //                          force-killing a foreign service.
    //   * Err (conn refused) — nothing is listening. Proceed to spawn.
    //
    // TODO(#455 follow-up): validate /health response body before attaching
    // so a multi-user host can't trivially spoof us. Also accept a port
    // override from config instead of hard-coding JARVIS_PORT.
    {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(2))
            .build()
            .unwrap();
        match client
            .get(format!("http://127.0.0.1:{}/health", JARVIS_PORT))
            .send()
            .await
        {
            Ok(resp) if resp.status().is_success() => {
                // Confirm with a second probe — the first might have caught
                // a flickering server (engine half-loaded, dying mid-stop,
                // etc.) and we don't want to claim ready off a 2-second
                // snapshot. Small sleep between to give the server room.
                tokio::time::sleep(Duration::from_millis(500)).await;
                let confirm = client
                    .get(format!("http://127.0.0.1:{}/health", JARVIS_PORT))
                    .send()
                    .await
                    .map(|r| r.status().is_success())
                    .unwrap_or(false);
                if !confirm {
                    // First probe was 2xx but the second wasn't — fall
                    // through to the spawn path. The server probably went
                    // away between probes.
                    // (No early return — we want to spawn our own.)
                } else {
                    // A newly staged key may only enter a child process that
                    // this desktop instance launched. A listener that merely
                    // answers /health could be a port squatter; never POST or
                    // otherwise disclose the pending secret to it.
                    match pending_rollback.staged_credential_present() {
                        Ok(true) => {
                            let mut s = status.lock().await;
                            s.error = Some(format!(
                                "An API server is already running on port {}, but OpenJarvis cannot securely apply your new inference API key to a server it did not start. Stop that server, then try setup again.",
                                JARVIS_PORT,
                            ));
                            return;
                        }
                        Err(err) => {
                            let mut s = status.lock().await;
                            s.error = Some(format!(
                                "Could not verify the staged inference API key: {}",
                                err
                            ));
                            return;
                        }
                        Ok(false) => {}
                    }
                    // Attach to the existing healthy server. Mark every
                    // pre-spawn step done so the setup UI doesn't show a
                    // half-progress bar (model_ready / ollama_ready stay
                    // false otherwise because we skipped those steps).
                    if let Err(err) = pending_rollback.confirm(&mut cfg) {
                        let mut s = status.lock().await;
                        s.error = Some(format!("Could not confirm inference setup: {}", err));
                        return;
                    }
                    let mut s = status.lock().await;
                    s.phase = "ready".into();
                    s.detail =
                        format!("Connected to existing API server on port {}.", JARVIS_PORT,);
                    s.server_ready = true;
                    s.model_ready = true;
                    s.ollama_ready = true;
                    return;
                }
            }
            Ok(resp) if resp.status() == reqwest::StatusCode::SERVICE_UNAVAILABLE => {
                let mut s = status.lock().await;
                s.error = Some(format!(
                    "An API server is already running on port {} but its \
                     inference engine isn't ready (HTTP 503). If this is your \
                     `jarvis serve`, wait for it to finish loading and relaunch. \
                     Otherwise, stop that service or change the port.",
                    JARVIS_PORT,
                ));
                return;
            }
            Ok(resp) => {
                // Something else (a different web server, a stale process,
                // a 4xx-returning instance) is on our port. Don't kill it —
                // give the user actionable info instead.
                let mut s = status.lock().await;
                s.error = Some(format!(
                    "Port {} is already in use by another service (it answered \
                     /health with HTTP {}). Stop that service or change the \
                     OpenJarvis port, then relaunch.\n\nTo identify it:\n  {}",
                    JARVIS_PORT,
                    resp.status(),
                    port_owner_hint(),
                ));
                return;
            }
            Err(_) => {
                // Nothing listening — proceed to the normal spawn path.
            }
        }
    }

    if let Err(err) = check_jarvis_port_available() {
        let mut s = status.lock().await;
        s.error = Some(err);
        return;
    }

    let root = project_root.as_ref().unwrap();

    let cargo_bin = resolve_bin("cargo");
    if !std::path::Path::new(&cargo_bin).exists() && cargo_bin == "cargo" {
        let mut s = status.lock().await;
        s.error = Some(format_missing_rust_toolchain());
        return;
    }

    // Install dependencies automatically (handles fresh clones).
    //
    // Previously we ran `uv sync` with both stdout AND stderr piped to
    // /dev/null and discarded the exit code (`let _ = …`). When `uv sync`
    // failed — Windows path issues, network problems, lockfile conflicts —
    // the user saw no error, the boot continued, `uv run jarvis serve`
    // then ran in an under-provisioned venv, and the user waited the full
    // 600s health-check window before getting "Jarvis server did not
    // become healthy in time" with no actionable detail (issue #331).
    //
    // Now: capture stderr, check the exit status, surface a useful error
    // to the user BEFORE the long server-start wait. The status detail
    // message also indicates this can take a couple of minutes on first
    // boot so users don't restart the app thinking it's stuck.
    {
        let mut s = status.lock().await;
        s.detail = "Installing dependencies (uv sync — may take 1-2 min on first boot)...".into();
    }
    let mut sync_cmd = tokio::process::Command::new(&uv_bin);
    sync_cmd
        .args([
            "sync",
            "--extra",
            "desktop",
            "--extra",
            "inference-cloud",
            "--extra",
            "inference-google",
            // openjarvis_rust lives in a uv dependency group (not the published
            // `desktop` extra) so pip installs from PyPI don't require it (#584).
            "--group",
            "desktop-native",
        ])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        .current_dir(root);
    // Avoid LD_LIBRARY_PATH leak when running inside an AppImage (#455).
    prepare_subprocess_for_appimage(&mut sync_cmd);
    add_cargo_bin_to_path(&mut sync_cmd);
    sync_cmd.kill_on_drop(true);
    let sync_output = sync_cmd.output().await;
    match sync_output {
        Ok(out) if !out.status.success() => {
            let stderr = String::from_utf8_lossy(&out.stderr);
            let mut s = status.lock().await;
            s.error = Some(format_uv_sync_failure(root, out.status.code(), &stderr));
            return;
        }
        Err(e) => {
            let mut s = status.lock().await;
            s.error = Some(format_uv_sync_spawn_error(root, &uv_bin, &e.to_string()));
            return;
        }
        Ok(_) => {} // success — fall through
    }

    {
        let mut s = status.lock().await;
        s.detail = "Verifying Rust extension (openjarvis_rust)...".into();
    }
    if let Err(err) = verify_openjarvis_rust_extension(root, &uv_bin).await {
        let mut s = status.lock().await;
        s.error = Some(err);
        return;
    }

    {
        let mut s = status.lock().await;
        s.detail = format!("Starting API server from {}...", root.display());
    }

    let mut cmd = tokio::process::Command::new(&uv_bin);
    let mut serve_argv: Vec<String> = vec![
        "run".into(),
        "jarvis".into(),
        "serve".into(),
        "--port".into(),
        JARVIS_PORT.to_string(),
    ];
    serve_argv.extend(plan.serve_args.iter().cloned());
    // If the Ollama pull fell back to a different tag than planned, serve the
    // tag that is actually present. boot_plan always emits `--model` followed
    // immediately by its value, so `i + 1` is in bounds.
    if let Some(m) = &serve_model_override {
        match serve_argv.iter().position(|a| a == "--model") {
            Some(i) if i + 1 < serve_argv.len() => serve_argv[i + 1] = m.clone(),
            _ => eprintln!(
                "Warning: resolved model {:?} could not be applied; \
                 '--model <value>' not found in serve args {:?}",
                m, serve_argv
            ),
        }
    }
    cmd.args(&serve_argv)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        .current_dir(root);
    // Avoid LD_LIBRARY_PATH leak when running inside an AppImage (#455) —
    // do this BEFORE cmd.env() calls below so our explicit cloud-key env
    // additions aren't accidentally stripped.
    prepare_subprocess_for_appimage(&mut cmd);

    // Inject cloud API keys from secure desktop storage.
    for (key, value) in cloud_keys_for_inference(&cfg) {
        cmd.env(&key, &value);
    }
    let jarvis_child = spawn_owned_child(&mut cmd);

    match jarvis_child {
        Ok(mut child) => {
            // Start draining stderr immediately. If we wait until the
            // health check returns we risk filling the 4 KB Windows pipe
            // buffer during startup logging and hanging the child before
            // it can bind its HTTP port — exactly the symptom in #309.
            let stderr_handle = child.stderr.take();
            let mut mgr = backend.lock().await;
            let tail = mgr.jarvis_stderr_tail.clone();
            mgr.jarvis = Some(ChildHandle { child });
            drop(mgr);
            if let Some(stderr) = stderr_handle {
                spawn_jarvis_stderr_drainer(stderr, tail);
            }
        }
        Err(e) => {
            let mut s = status.lock().await;
            s.error = Some(format!(
                "Could not start jarvis server: {}. \
                 Make sure uv is installed (https://astral.sh/uv) and the OpenJarvis repo is cloned at {}",
                e,
                root.display(),
            ));
            return;
        }
    }

    let server_url = format!("http://127.0.0.1:{}/health", JARVIS_PORT);
    match wait_for_jarvis_health(&server_url, Duration::from_secs(600), &backend).await {
        JarvisStartResult::Ready => {}
        JarvisStartResult::ServiceUnavailable(body) => {
            let mut s = status.lock().await;
            s.error = Some(format!(
                "Jarvis server is running but the inference engine is not available \
                 (HTTP 503). This usually means the configured model couldn't be loaded.\n\n\
                 Check the server logs, or run 'uv run jarvis serve --port {}{}' \
                 from {} to see the engine error.\n\n\
                 Server response:\n{}",
                JARVIS_PORT,
                // Show the args actually passed (after `serve --port <port>`),
                // including any post-fallback `--model` override.
                match serve_argv.get(5..) {
                    Some(rest) if !rest.is_empty() => format!(" {}", rest.join(" ")),
                    _ => String::new(),
                },
                root.display(),
                body.trim(),
            ));
            return;
        }
        JarvisStartResult::EarlyExit { code, stderr } => {
            // `None` here means the OS didn't expose an exit code — on
            // Unix that's a signal kill (SIGKILL/SIGSEGV/...), on Windows
            // it means the process was terminated externally (Task
            // Manager, parent-of-parent, AV). "unknown" covers both.
            let code_str = code
                .map(|c| c.to_string())
                .unwrap_or_else(|| "unknown".into());
            let mut s = status.lock().await;
            s.error = Some(if stderr.is_empty() {
                format!(
                    "Jarvis server exited (code {}) before becoming ready.\n\n\
                     No stderr output. Check that:\n\
                     1. uv is installed ({})\n\
                     2. The OpenJarvis repo is at {}\n\
                     3. 'uv sync' completes in that directory",
                    code_str,
                    uv_bin,
                    root.display(),
                )
            } else {
                format!(
                    "Jarvis server exited (code {}) before becoming ready.\n\nStderr:\n{}",
                    code_str, stderr,
                )
            });
            return;
        }
        JarvisStartResult::Timeout => {
            let stderr = read_jarvis_stderr_tail(&backend).await;
            let mut s = status.lock().await;
            s.error = Some(if stderr.is_empty() {
                format!(
                    "Jarvis server did not become ready within 10 minutes. Check that:\n\
                     1. uv is installed ({})\n\
                     2. The OpenJarvis repo is at {}\n\
                     3. Run 'uv sync' in that directory",
                    uv_bin,
                    root.display(),
                )
            } else {
                format!(
                    "Jarvis server did not become ready within 10 minutes.\n\nStderr:\n{}",
                    stderr,
                )
            });
            return;
        }
    }

    if let Err(err) = pending_rollback.confirm(&mut cfg) {
        let mut s = status.lock().await;
        s.error = Some(format!("Could not confirm inference setup: {}", err));
        return;
    }

    {
        let mut s = status.lock().await;
        s.server_ready = true;
        s.phase = "ready".into();
        s.detail = "All systems ready.".into();
    }

    // Phase 4: done. We intentionally do NOT auto-pull the rest of the
    // Qwen3.5 ladder here. The previous behavior walked every model that
    // "fit" in RAM (up to qwen3.5:122b ≈ 81 GB) and pulled each one in an
    // un-cancellable background task — so the app silently consumed tens of
    // gigabytes with no way to stop short of deleting it. The startup model
    // pulled in Phase 2 is enough to make the app fully usable; additional
    // models are now opt-in (Settings → "ollama pull <model>", or the
    // `pull_model` command invoked from the UI).
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

fn api_base() -> String {
    format!("http://127.0.0.1:{}", JARVIS_PORT)
}

#[tauri::command]
async fn get_setup_status(state: tauri::State<'_, SharedStatus>) -> Result<SetupStatus, String> {
    Ok(state.lock().await.clone())
}

#[tauri::command]
fn get_api_base() -> String {
    api_base()
}

#[tauri::command]
async fn start_backend(
    backend: tauri::State<'_, SharedBackend>,
    status: tauri::State<'_, SharedStatus>,
) -> Result<(), String> {
    if read_configured_inference_config().is_none() {
        *status.lock().await = SetupStatus::default();
        return Err("Choose an inference source before starting OpenJarvis.".into());
    }
    let b = backend.inner().clone();
    let s = status.inner().clone();
    start_managed_boot(b, s).await;
    Ok(())
}

#[tauri::command]
async fn stop_backend(backend: tauri::State<'_, SharedBackend>) -> Result<(), String> {
    backend.lock().await.stop_all().await;
    Ok(())
}

/// Abort startup, stop every child, discard an unworkable source, and return
/// the UI to the inert chooser. This is the recovery path for setup failures.
#[tauri::command]
async fn reset_inference_source(
    backend: tauri::State<'_, SharedBackend>,
    status: tauri::State<'_, SharedStatus>,
) -> Result<(), String> {
    backend.lock().await.stop_all().await;
    discard_pending_inference_setup()?;
    *status.lock().await = SetupStatus::default();
    Ok(())
}

#[tauri::command]
async fn check_health(api_url: String) -> Result<serde_json::Value, String> {
    let url = format!(
        "{}/health",
        if api_url.is_empty() {
            api_base()
        } else {
            api_url
        }
    );
    let resp = reqwest::get(&url)
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_energy(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/telemetry/energy", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_telemetry(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/telemetry/stats", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_traces(api_url: String, limit: u32) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/traces?limit={}", base, limit))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_trace(api_url: String, trace_id: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/traces/{}", base, trace_id))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_learning_stats(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/learning/stats", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_learning_policy(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/learning/policy", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_memory_stats(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/memory/stats", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn search_memory(
    api_url: String,
    query: String,
    top_k: u32,
) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let client = reqwest::Client::new();
    let resp = client
        .post(format!("{}/v1/memory/search", base))
        .json(&serde_json::json!({"query": query, "top_k": top_k}))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_agents(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/agents", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_models(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/models", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn run_jarvis_command(args: Vec<String>) -> Result<String, String> {
    let uv_bin = resolve_bin("uv");

    let mut cmd_args = vec!["run".to_string(), "jarvis".to_string()];
    cmd_args.extend(args.iter().cloned());

    let mut cmd = tokio::process::Command::new(&uv_bin);
    cmd.args(&cmd_args);
    // Run from the project root so `uv run jarvis` resolves the OpenJarvis
    // project regardless of the app's launch cwd. In a packaged install the
    // cwd isn't the checkout, so without this `jarvis` isn't found and the
    // backend never starts — the UI then shows "Failed to get response"
    // (see #531).
    if let Some(ref root) = find_project_root() {
        cmd.current_dir(root);
    }

    let is_serve = args.first().map(|a| a.as_str() == "serve").unwrap_or(false);

    if !is_serve {
        // Short-lived command (e.g. `stop`, `status`): wait for it and return
        // its captured output.
        let output = cmd
            .output()
            .await
            .map_err(|e| format!("Failed to launch jarvis: {}", e))?;
        return if output.status.success() {
            Ok(String::from_utf8_lossy(&output.stdout).to_string())
        } else {
            Err(String::from_utf8_lossy(&output.stderr).to_string())
        };
    }

    // `jarvis serve` is a long-running server that never exits. The old code
    // used `.output()`, which waits for the process to exit and so hung this
    // command forever — the "Start" button never resolved (#531). Spawn it
    // detached instead, drain stderr (a full 4 KB Windows pipe can otherwise
    // stall the child mid-startup, #309), and poll /health for readiness.
    cmd.stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped());
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("Failed to launch jarvis serve: {}", e))?;

    let tail: StderrTail = Arc::new(Mutex::new(Vec::new()));
    if let Some(stderr) = child.stderr.take() {
        spawn_jarvis_stderr_drainer(stderr, tail.clone());
    }

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| format!("Failed to build HTTP client: {}", e))?;
    let url = format!("http://127.0.0.1:{}/health", JARVIS_PORT);
    let deadline = tokio::time::Instant::now() + Duration::from_secs(120);

    loop {
        // Surface an early crash (bad venv, missing Rust ext, etc.) right away
        // instead of waiting out the full readiness timeout.
        if let Ok(Some(status)) = child.try_wait() {
            let stderr = String::from_utf8_lossy(tail.lock().await.as_slice()).into_owned();
            return Err(format!(
                "jarvis serve exited (code {:?}) before becoming healthy:\n{}",
                status.code(),
                stderr.trim()
            ));
        }
        if let Ok(resp) = client.get(&url).send().await {
            if resp.status().is_success() {
                // Leave the server running (the Child is detached on drop —
                // kill_on_drop defaults to false); `stop` tears it down.
                return Ok(format!(
                    "jarvis serve is ready on http://127.0.0.1:{}",
                    JARVIS_PORT
                ));
            }
        }
        if tokio::time::Instant::now() >= deadline {
            return Err(format!(
                "jarvis serve did not become healthy on port {} within 120s.",
                JARVIS_PORT
            ));
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}

#[tauri::command]
async fn fetch_savings(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/savings", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

/// Transcribe audio via the speech API endpoint.
#[tauri::command]
async fn transcribe_audio(
    api_url: String,
    audio_data: Vec<u8>,
    filename: String,
) -> Result<serde_json::Value, String> {
    let url = format!("{}/v1/speech/transcribe", api_url);
    let client = reqwest::Client::new();

    let part = reqwest::multipart::Part::bytes(audio_data)
        .file_name(filename)
        .mime_str("audio/webm")
        .map_err(|e| format!("Failed to create multipart: {}", e))?;

    let form = reqwest::multipart::Form::new().part("file", part);

    let resp = client
        .post(&url)
        .multipart(form)
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    let status = resp.status();
    let body = resp
        .text()
        .await
        .map_err(|e| format!("Invalid response: {}", e))?;
    if !status.is_success() {
        let detail = serde_json::from_str::<serde_json::Value>(&body)
            .ok()
            .and_then(|value| {
                value
                    .get("detail")
                    .and_then(|detail| detail.as_str())
                    .map(str::to_string)
            })
            .filter(|detail| !detail.is_empty())
            .unwrap_or(body);
        return Err(format!(
            "Transcription failed ({}): {}",
            status.as_u16(),
            detail
        ));
    }
    serde_json::from_str(&body).map_err(|e| format!("Invalid response: {}", e))
}

/// Submit savings to Supabase leaderboard.
#[tauri::command]
async fn submit_savings(
    supabase_url: String,
    supabase_key: String,
    payload: serde_json::Value,
) -> Result<bool, String> {
    if supabase_url.is_empty() || supabase_key.is_empty() {
        return Ok(false);
    }
    let client = reqwest::Client::new();
    let resp = client
        .post(format!(
            "{}/rest/v1/savings_entries?on_conflict=anon_id",
            supabase_url
        ))
        .header("Content-Type", "application/json")
        .header("apikey", &supabase_key)
        .header("Authorization", format!("Bearer {}", supabase_key))
        .header("Prefer", "resolution=merge-duplicates")
        .json(&payload)
        .send()
        .await
        .map_err(|e| format!("Supabase POST failed: {}", e))?;
    Ok(resp.status().is_success())
}

// ---------------------------------------------------------------------------
// Cloud API key management
// ---------------------------------------------------------------------------

const SECURE_KEY_SERVICE: &str = "OpenJarvis Cloud Keys";
// A first-run custom credential is kept in its own secure-storage slot until
// the managed backend has passed every readiness gate.  In particular, do not
// overwrite an existing <ENGINE>_API_KEY while setup can still be cancelled.
const PENDING_INFERENCE_API_KEY: &str = "OPENJARVIS_PENDING_INFERENCE_API_KEY";
const MANAGED_CLOUD_KEY_NAMES: &[&str] = &[
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "MINIMAX_API_KEY",
    "TAVILY_API_KEY",
];

/// Legacy path used by older desktop builds. New saves never write here.
fn legacy_cloud_keys_path() -> std::path::PathBuf {
    let home = home_dir();
    std::path::PathBuf::from(home)
        .join(".openjarvis")
        .join("cloud-keys.env")
}

fn validate_cloud_key_name(key_name: &str) -> Result<(), String> {
    let valid = !key_name.is_empty()
        && key_name.len() <= 128
        && key_name.ends_with("_API_KEY")
        && key_name
            .chars()
            .all(|ch| ch.is_ascii_uppercase() || ch.is_ascii_digit() || ch == '_');
    if valid {
        Ok(())
    } else {
        Err(format!("Invalid API key name: {}", key_name))
    }
}

fn engine_api_key_name(engine: &str) -> String {
    let normalized: String = engine
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() {
                ch.to_ascii_uppercase()
            } else {
                '_'
            }
        })
        .collect();
    let trimmed = normalized.trim_matches('_');
    let engine_name = if trimmed.is_empty() {
        CUSTOM_FALLBACK_ENGINE.to_ascii_uppercase()
    } else {
        trimmed.to_string()
    };
    format!("{}_API_KEY", engine_name)
}

fn managed_cloud_key_names() -> Vec<String> {
    let mut names: Vec<String> = MANAGED_CLOUD_KEY_NAMES
        .iter()
        .map(|name| (*name).to_string())
        .collect();

    let cfg = read_inference_config();
    if matches!(&cfg.kind, SourceKind::Custom) {
        let engine = cfg
            .engine
            .unwrap_or_else(|| CUSTOM_FALLBACK_ENGINE.to_string());
        let key_name = engine_api_key_name(&engine);
        if validate_cloud_key_name(&key_name).is_ok() {
            names.push(key_name);
        }
    }

    names.sort();
    names.dedup();
    names
}

fn secure_store_get(key_name: &str) -> Result<Option<String>, String> {
    validate_cloud_key_name(key_name)?;
    let entry = keyring::Entry::new(SECURE_KEY_SERVICE, key_name).map_err(|err| {
        format!(
            "Failed to open secure key storage for {}: {}",
            key_name, err
        )
    })?;
    match entry.get_password() {
        Ok(value) => Ok(Some(value)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(err) => Err(format!(
            "Failed to read {} from secure key storage: {}",
            key_name, err
        )),
    }
}

fn secure_store_set(key_name: &str, key_value: &str) -> Result<(), String> {
    validate_cloud_key_name(key_name)?;
    let entry = keyring::Entry::new(SECURE_KEY_SERVICE, key_name).map_err(|err| {
        format!(
            "Failed to open secure key storage for {}: {}",
            key_name, err
        )
    })?;
    if key_value.is_empty() {
        return match entry.delete_credential() {
            Ok(()) => Ok(()),
            Err(keyring::Error::NoEntry) => Ok(()),
            Err(err) => Err(format!(
                "Failed to remove {} from secure key storage: {}",
                key_name, err
            )),
        };
    }
    entry
        .set_password(key_value)
        .map_err(|err| format!("Failed to save {} in secure key storage: {}", key_name, err))
}

trait InferenceCredentialStore: Send + Sync {
    fn get(&self, key_name: &str) -> Result<Option<String>, String>;
    fn set(&self, key_name: &str, key_value: &str) -> Result<(), String>;
}

struct SystemInferenceCredentialStore;

impl InferenceCredentialStore for SystemInferenceCredentialStore {
    fn get(&self, key_name: &str) -> Result<Option<String>, String> {
        secure_store_get(key_name)
    }

    fn set(&self, key_name: &str, key_value: &str) -> Result<(), String> {
        secure_store_set(key_name, key_value)
    }
}

fn read_legacy_cloud_keys() -> Vec<(String, String)> {
    let path = legacy_cloud_keys_path();
    let mut keys = Vec::new();
    if let Ok(contents) = std::fs::read_to_string(&path) {
        for line in contents.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            if let Some((k, v)) = line.split_once('=') {
                keys.push((k.trim().to_string(), v.trim().to_string()));
            }
        }
    }
    keys
}

fn migrate_legacy_cloud_keys() {
    let path = legacy_cloud_keys_path();
    if !path.exists() {
        return;
    }

    let legacy_keys = read_legacy_cloud_keys();
    if legacy_keys.is_empty() {
        let _ = std::fs::remove_file(&path);
        return;
    }

    let mut migrated_all = true;
    for (key, value) in legacy_keys {
        if value.is_empty() {
            continue;
        }
        if secure_store_set(&key, &value).is_err() {
            migrated_all = false;
        }
    }

    if migrated_all {
        let _ = std::fs::remove_file(path);
    }
}

/// Read cloud keys from secure desktop storage and return key=value pairs.
fn read_cloud_keys() -> Vec<(String, String)> {
    migrate_legacy_cloud_keys();
    managed_cloud_key_names()
        .into_iter()
        .filter_map(|key| match secure_store_get(&key) {
            Ok(Some(value)) if !value.is_empty() => Some((key, value)),
            _ => None,
        })
        .collect()
}

/// Overlay a staged first-run credential onto the child-process environment.
/// The durable provider key remains untouched until setup is confirmed.
fn cloud_keys_for_inference(cfg: &InferenceConfig) -> Vec<(String, String)> {
    let mut keys = read_cloud_keys();
    let Some(credential) = PendingInferenceCredential::for_config(cfg) else {
        return keys;
    };
    let Ok(Some(staged)) = secure_store_get(PENDING_INFERENCE_API_KEY) else {
        return keys;
    };
    if staged.is_empty() {
        return keys;
    }
    keys.retain(|(name, _)| name != &credential.target_key);
    keys.push((credential.target_key, staged));
    keys
}

async fn reload_cloud_keys_at(reload_url: &str, keys: Vec<(String, String)>) {
    let key_map: serde_json::Map<String, serde_json::Value> = keys
        .into_iter()
        .map(|(key, value)| (key, serde_json::Value::String(value)))
        .collect();
    let _ = reqwest::Client::new()
        .post(reload_url)
        .json(&serde_json::json!({ "keys": key_map }))
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await;
}

/// Hot-reload only a live server process launched and owned by this desktop
/// process.  A healthy-looking loopback listener is not proof of ownership and
/// must never receive raw credentials.
async fn reload_cloud_keys_for_owned_backend(
    backend: &SharedBackend,
    status: &SharedStatus,
    keys: Vec<(String, String)>,
) {
    let reload_url = format!("http://127.0.0.1:{}/v1/cloud/reload", JARVIS_PORT);
    reload_cloud_keys_for_owned_backend_at(backend, status, keys, &reload_url).await;
}

async fn reload_cloud_keys_for_owned_backend_at(
    backend: &SharedBackend,
    status: &SharedStatus,
    keys: Vec<(String, String)>,
    reload_url: &str,
) {
    if !status.lock().await.server_ready {
        return;
    }

    // Keep the manager lock for the request so stop/reset cannot kill our
    // child and let an unrelated process claim the port between the ownership
    // check and the credential POST.
    let mut manager = backend.lock().await;
    let Some(handle) = manager.jarvis.as_mut() else {
        return;
    };
    if !matches!(handle.child.try_wait(), Ok(None)) {
        return;
    }
    reload_cloud_keys_at(reload_url, keys).await;
}

/// Save a single cloud API key to secure desktop storage.
#[tauri::command]
async fn save_cloud_key(
    key_name: String,
    key_value: String,
    backend: tauri::State<'_, SharedBackend>,
    status: tauri::State<'_, SharedStatus>,
) -> Result<(), String> {
    let key_value = key_value.trim().to_string();
    secure_store_set(&key_name, &key_value)?;

    // Tell only our own ready child to hot-reload its cloud engine.  Posting to
    // a merely responsive port would disclose the raw key to a port squatter.
    reload_cloud_keys_for_owned_backend(
        backend.inner(),
        status.inner(),
        vec![(key_name, key_value)],
    )
    .await;

    Ok(())
}

/// Get which cloud providers have keys configured (without exposing values).
#[tauri::command]
async fn get_cloud_key_status() -> Result<serde_json::Value, String> {
    migrate_legacy_cloud_keys();
    let status: Vec<serde_json::Value> = managed_cloud_key_names()
        .into_iter()
        .map(|key| {
            let set = matches!(secure_store_get(&key), Ok(Some(value)) if !value.is_empty());
            serde_json::json!({ "key": key, "set": set })
        })
        .collect();
    Ok(serde_json::json!(status))
}

/// Return the current inference-source config for the Settings UI.
#[tauri::command]
async fn get_inference_source() -> Result<InferenceConfig, String> {
    Ok(read_inference_config())
}

/// Persist the chosen inference source. `host` is normalized to a bare base
/// URL. For custom endpoints, an optional API key is stored in secure desktop
/// storage under `<ENGINE>_API_KEY`. Applies on next app launch.
#[tauri::command]
async fn set_inference_source(
    kind: String,
    model: Option<String>,
    host: Option<String>,
    engine: Option<String>,
    api_key: Option<String>,
    pending: Option<bool>,
) -> Result<(), String> {
    let kind = match kind.as_str() {
        "ollama" => SourceKind::Ollama,
        "custom" => SourceKind::Custom,
        other => return Err(format!("Unknown inference source kind: {:?}", other)),
    };
    let cfg = InferenceConfig {
        kind,
        confirmed: !pending.unwrap_or(false),
        model: model.filter(|m| !m.is_empty()),
        host: host.map(|h| normalize_host(&h)).filter(|h| !h.is_empty()),
        engine: engine.filter(|e| !e.is_empty()),
    };
    let api_key = api_key
        .map(|key| key.trim().to_string())
        .filter(|key| !key.is_empty());
    if let SourceKind::Custom = cfg.kind {
        if cfg.host.is_none() {
            return Err("A server URL is required for a custom endpoint.".into());
        }
        if cfg.model.as_deref().unwrap_or("").is_empty() {
            return Err("A model name is required for a custom endpoint.".into());
        }
    }

    let store = SystemInferenceCredentialStore;
    if cfg.confirmed {
        persist_confirmed_inference_config(&cfg, api_key.as_deref(), &store)
    } else {
        stage_pending_inference_config(&cfg, api_key.as_deref(), &store)
    }
}

/// Pull a model via Ollama (called from frontend download button).
#[tauri::command]
async fn pull_ollama_model(model_name: String) -> Result<serde_json::Value, String> {
    pull_model(&model_name)
        .await
        .map_err(|e| format!("Failed to pull {}: {}", model_name, e))?;
    Ok(serde_json::json!({"status": "ok", "model": model_name}))
}

/// Delete a model from Ollama.
#[tauri::command]
async fn delete_ollama_model(model_name: String) -> Result<serde_json::Value, String> {
    let url = format!("http://127.0.0.1:{}/api/delete", OLLAMA_PORT);
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client
        .delete(&url)
        .json(&serde_json::json!({"name": model_name}))
        .send()
        .await
        .map_err(|e| format!("Delete failed: {}", e))?;
    if !resp.status().is_success() {
        return Err(format!("Delete returned status {}", resp.status()));
    }
    Ok(serde_json::json!({"status": "deleted", "model": model_name}))
}

// ---------------------------------------------------------------------------
// Inference-source selection (~/.openjarvis/inference.json)
// ---------------------------------------------------------------------------

#[derive(serde::Serialize, serde::Deserialize, Clone, Copy, Debug, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
enum SourceKind {
    Ollama,
    Custom,
}

impl Default for SourceKind {
    fn default() -> Self {
        SourceKind::Ollama
    }
}

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, Default)]
struct InferenceConfig {
    #[serde(default)]
    kind: SourceKind,
    /// First-run choices stay pending until the complete backend reaches
    /// ready. Legacy configs predate this field and remain trusted.
    #[serde(default = "legacy_config_is_confirmed")]
    confirmed: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    model: Option<String>,
    /// Bare base URL (no trailing `/v1`), custom only.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    host: Option<String>,
    /// OpenAI-compatible engine key (e.g. "lmstudio"), custom only.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    engine: Option<String>,
}

fn legacy_config_is_confirmed() -> bool {
    true
}

/// Path to the inference-source config (~/.openjarvis/inference.json).
fn inference_config_path() -> std::path::PathBuf {
    std::path::PathBuf::from(home_dir())
        .join(".openjarvis")
        .join("inference.json")
}

fn remove_inference_config_at(path: &std::path::Path) -> Result<(), String> {
    match std::fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(err) => Err(format!("Failed to clear inference config: {}", err)),
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct PendingInferenceCredential {
    target_key: String,
}

impl PendingInferenceCredential {
    fn for_config(cfg: &InferenceConfig) -> Option<Self> {
        if cfg.confirmed || !matches!(cfg.kind, SourceKind::Custom) {
            return None;
        }
        let engine = cfg.engine.as_deref().unwrap_or(CUSTOM_FALLBACK_ENGINE);
        Some(Self {
            target_key: engine_api_key_name(engine),
        })
    }
}

fn restore_credential(
    store: &dyn InferenceCredentialStore,
    key_name: &str,
    previous: Option<&str>,
) -> Result<(), String> {
    store.set(key_name, previous.unwrap_or(""))
}

/// Persist a returning-user source and its optional credential as one logical
/// transaction. If the config write fails, restore the exact prior key.
fn persist_confirmed_inference_config(
    cfg: &InferenceConfig,
    api_key: Option<&str>,
    store: &dyn InferenceCredentialStore,
) -> Result<(), String> {
    persist_confirmed_inference_config_at(cfg, api_key, store, inference_config_path().as_path())
}

fn persist_confirmed_inference_config_at(
    cfg: &InferenceConfig,
    api_key: Option<&str>,
    store: &dyn InferenceCredentialStore,
    path: &std::path::Path,
) -> Result<(), String> {
    let Some(api_key) = api_key else {
        return write_inference_config_at(cfg, path);
    };
    let Some(target_key) = (matches!(cfg.kind, SourceKind::Custom))
        .then(|| engine_api_key_name(cfg.engine.as_deref().unwrap_or(CUSTOM_FALLBACK_ENGINE)))
    else {
        return write_inference_config_at(cfg, path);
    };

    let previous = store
        .get(&target_key)
        .map_err(|err| format!("Could not read the existing API key: {}", err))?;
    store
        .set(&target_key, api_key)
        .map_err(|err| format!("Could not store the API key: {}", err))?;
    if let Err(config_err) = write_inference_config_at(cfg, path) {
        return match restore_credential(store, &target_key, previous.as_deref()) {
            Ok(()) => Err(config_err),
            Err(restore_err) => Err(format!(
                "{}; additionally could not restore the previous API key: {}",
                config_err, restore_err
            )),
        };
    }
    Ok(())
}

/// Stage a first-run key in a dedicated secure slot. The real provider key is
/// not touched until the managed server is healthy and setup is confirmed.
fn stage_pending_inference_config(
    cfg: &InferenceConfig,
    api_key: Option<&str>,
    store: &dyn InferenceCredentialStore,
) -> Result<(), String> {
    stage_pending_inference_config_at(cfg, api_key, store, inference_config_path().as_path())
}

fn stage_pending_inference_config_at(
    cfg: &InferenceConfig,
    api_key: Option<&str>,
    store: &dyn InferenceCredentialStore,
    path: &std::path::Path,
) -> Result<(), String> {
    // A new choice supersedes any interrupted prior attempt. Fail closed if
    // secure storage cannot clear it: otherwise a stale secret could be bound
    // to the wrong engine when boot begins.
    store
        .set(PENDING_INFERENCE_API_KEY, "")
        .map_err(|err| format!("Could not clear a pending API key: {}", err))?;
    if matches!(cfg.kind, SourceKind::Custom) {
        if let Some(api_key) = api_key {
            store
                .set(PENDING_INFERENCE_API_KEY, api_key)
                .map_err(|err| format!("Could not stage the API key: {}", err))?;
        }
    }

    if let Err(config_err) = write_inference_config_at(cfg, path) {
        return match store.set(PENDING_INFERENCE_API_KEY, "") {
            Ok(()) => Err(config_err),
            Err(cleanup_err) => Err(format!(
                "{}; additionally could not discard the staged API key: {}",
                config_err, cleanup_err
            )),
        };
    }
    Ok(())
}

fn discard_pending_inference_setup() -> Result<(), String> {
    discard_pending_inference_setup_at(
        inference_config_path().as_path(),
        &SystemInferenceCredentialStore,
    )
}

fn discard_pending_inference_setup_at(
    path: &std::path::Path,
    store: &dyn InferenceCredentialStore,
) -> Result<(), String> {
    let key_result = store.set(PENDING_INFERENCE_API_KEY, "");
    let config_result = remove_inference_config_at(path);
    match (key_result, config_result) {
        (Ok(()), Ok(())) => Ok(()),
        (Err(key_err), Ok(())) => Err(format!("Failed to discard pending API key: {}", key_err)),
        (Ok(()), Err(config_err)) => Err(config_err),
        (Err(key_err), Err(config_err)) => Err(format!(
            "{}; additionally failed to discard pending API key: {}",
            config_err, key_err
        )),
    }
}

/// Rolls a first-run choice back whenever boot exits before confirmation.
/// Confirmed returning-user configs are never removed by a transient outage.
struct PendingInferenceRollback {
    path: Option<std::path::PathBuf>,
    credential: Option<PendingInferenceCredential>,
    credential_store: Option<Arc<dyn InferenceCredentialStore>>,
}

impl PendingInferenceRollback {
    fn new(cfg: &InferenceConfig) -> Self {
        Self {
            path: (!cfg.confirmed).then_some(inference_config_path()),
            credential: PendingInferenceCredential::for_config(cfg),
            credential_store: (!cfg.confirmed).then(|| {
                Arc::new(SystemInferenceCredentialStore) as Arc<dyn InferenceCredentialStore>
            }),
        }
    }

    #[cfg(test)]
    fn at_path(cfg: &InferenceConfig, path: std::path::PathBuf) -> Self {
        Self {
            path: (!cfg.confirmed).then_some(path),
            credential: None,
            credential_store: None,
        }
    }

    #[cfg(test)]
    fn at_path_with_store(
        cfg: &InferenceConfig,
        path: std::path::PathBuf,
        credential_store: Arc<dyn InferenceCredentialStore>,
    ) -> Self {
        Self {
            path: (!cfg.confirmed).then_some(path),
            credential: PendingInferenceCredential::for_config(cfg),
            credential_store: (!cfg.confirmed).then_some(credential_store),
        }
    }

    fn disarm(&mut self) {
        self.path = None;
        self.credential = None;
        self.credential_store = None;
    }

    fn staged_credential_present(&self) -> Result<bool, String> {
        let (Some(_), Some(store)) = (&self.credential, &self.credential_store) else {
            return Ok(false);
        };
        Ok(matches!(
            store.get(PENDING_INFERENCE_API_KEY)?,
            Some(value) if !value.is_empty()
        ))
    }

    /// Commit a staged first-run choice only after every readiness gate has
    /// succeeded.  Keeping this operation on the rollback guard makes all
    /// successful exits use the same write-then-disarm ordering: if the write
    /// fails (or the future is cancelled), `Drop` removes the staged file.
    fn confirm(&mut self, cfg: &mut InferenceConfig) -> Result<(), String> {
        if cfg.confirmed {
            self.disarm();
            return Ok(());
        }

        let path = self
            .path
            .as_ref()
            .ok_or_else(|| "Pending inference setup lost its rollback path.".to_string())?;
        let mut confirmed = cfg.clone();
        confirmed.confirmed = true;

        let mut promoted: Option<(String, Option<String>)> = None;
        if let (Some(credential), Some(store)) = (&self.credential, &self.credential_store) {
            if let Some(staged) = store.get(PENDING_INFERENCE_API_KEY)? {
                if !staged.is_empty() {
                    let previous = store.get(&credential.target_key)?;
                    store.set(&credential.target_key, &staged)?;
                    if let Err(cleanup_err) = store.set(PENDING_INFERENCE_API_KEY, "") {
                        let restore_result = restore_credential(
                            store.as_ref(),
                            &credential.target_key,
                            previous.as_deref(),
                        );
                        return match restore_result {
                            Ok(()) => Err(cleanup_err),
                            Err(restore_err) => Err(format!(
                                "{}; additionally could not restore the previous API key: {}",
                                cleanup_err, restore_err
                            )),
                        };
                    }
                    promoted = Some((credential.target_key.clone(), previous));
                }
            }
        }

        if let Err(config_err) = write_inference_config_at(&confirmed, path) {
            if let (Some((target_key, previous)), Some(store)) = (promoted, &self.credential_store)
            {
                return match restore_credential(store.as_ref(), &target_key, previous.as_deref()) {
                    Ok(()) => Err(config_err),
                    Err(restore_err) => Err(format!(
                        "{}; additionally could not restore the previous API key: {}",
                        config_err, restore_err
                    )),
                };
            }
            return Err(config_err);
        }
        *cfg = confirmed;
        self.disarm();
        Ok(())
    }
}

impl Drop for PendingInferenceRollback {
    fn drop(&mut self) {
        if let Some(path) = self.path.take() {
            let _ = std::fs::remove_file(path);
        }
        if self.credential.take().is_some() {
            if let Some(store) = self.credential_store.take() {
                let _ = store.set(PENDING_INFERENCE_API_KEY, "");
            }
        }
    }
}

/// Parse only an explicitly persisted source choice. Missing/invalid config is
/// intentionally `None`: callers on the boot path must wait for setup rather
/// than silently falling back to Ollama.
fn parse_configured_inference_config(text: &str) -> Option<InferenceConfig> {
    let value = serde_json::from_str::<serde_json::Value>(text).ok()?;
    if !value.as_object()?.contains_key("kind") {
        return None;
    }
    serde_json::from_value::<InferenceConfig>(value).ok()
}

fn read_configured_inference_config() -> Option<InferenceConfig> {
    std::fs::read_to_string(inference_config_path())
        .ok()
        .and_then(|text| parse_configured_inference_config(&text))
}

/// Read the on-disk inference config, or the Ollama default if absent.
fn read_inference_config() -> InferenceConfig {
    read_configured_inference_config().unwrap_or_default()
}

/// Write the inference config to disk (pretty JSON).
fn write_inference_config(cfg: &InferenceConfig) -> Result<(), String> {
    let path = inference_config_path();
    write_inference_config_at(cfg, &path)
}

fn write_inference_config_at(cfg: &InferenceConfig, path: &std::path::Path) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let json = serde_json::to_string_pretty(cfg).map_err(|e| e.to_string())?;
    std::fs::write(path, json + "\n").map_err(|e| format!("Failed to save inference config: {}", e))
}

/// Upsert `[engine.<engine>] host = "<host>"` into an existing config.toml
/// string, preserving all other content/formatting. Pure: string in, string out.
fn upsert_engine_host(existing: &str, engine: &str, host: &str) -> Result<String, String> {
    let mut doc = existing
        .parse::<toml_edit::DocumentMut>()
        .map_err(|e| format!("Invalid config.toml: {}", e))?;
    doc["engine"][engine]["host"] = toml_edit::value(host);
    Ok(doc.to_string())
}

/// Write the custom-endpoint host into ~/.openjarvis/config.toml so
/// `jarvis serve` (which reads that file via load_config) points at it.
/// The `<ENGINE>_HOST` env var is unreliable — it is shadowed by the engine's
/// non-empty default host in the Python layer — so config.toml is the override.
fn set_engine_host_in_config(engine: &str, host: &str) -> Result<(), String> {
    let path = std::path::PathBuf::from(home_dir())
        .join(".openjarvis")
        .join("config.toml");
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let existing = std::fs::read_to_string(&path).unwrap_or_default();
    let updated = upsert_engine_host(&existing, engine, host)?;
    std::fs::write(&path, updated).map_err(|e| format!("Failed to write config.toml: {}", e))
}

/// Normalize a user-entered server URL to a bare base host: trim whitespace,
/// drop a trailing `/v1` segment (the engine re-appends its own api prefix),
/// then drop any trailing slash.
fn normalize_host(raw: &str) -> String {
    let s = raw.trim().trim_end_matches('/');
    let s = s.strip_suffix("/v1").unwrap_or(s);
    s.trim_end_matches('/').to_string()
}

/// Check speech backend health.
#[tauri::command]
async fn speech_health(api_url: String) -> Result<serde_json::Value, String> {
    let url = format!("{}/v1/speech/health", api_url);
    let resp = reqwest::get(&url)
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    let body: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))?;
    Ok(body)
}

// ---------------------------------------------------------------------------
// Native macOS overlay — NSPanel + WKWebView, entirely bypassing Tauri's
// window management so we get proper always-on-top, transparency, non-
// activating panel behaviour and cross-Space support.
// ---------------------------------------------------------------------------

#[cfg(target_os = "macos")]
mod native_overlay {
    use objc::declare::ClassDecl;
    use objc::runtime::{Class, Object, Sel, BOOL, NO, YES};
    use objc::{class, msg_send, sel, sel_impl};
    use std::sync::atomic::{AtomicUsize, Ordering};

    /// Raw pointer to the NSPanel, stored as usize for atomicity.
    static PANEL_PTR: AtomicUsize = AtomicUsize::new(0);
    /// Raw pointer to the WKWebView inside the panel.
    static WEBVIEW_PTR: AtomicUsize = AtomicUsize::new(0);
    /// Raw pointer to the previously-frontmost NSRunningApplication.
    static PREV_APP: AtomicUsize = AtomicUsize::new(0);

    // CoreGraphics geometry types expected by AppKit.
    #[repr(C)]
    #[derive(Copy, Clone)]
    struct CGPoint {
        x: f64,
        y: f64,
    }
    #[repr(C)]
    #[derive(Copy, Clone)]
    struct CGSize {
        width: f64,
        height: f64,
    }
    #[repr(C)]
    #[derive(Copy, Clone)]
    struct CGRect {
        origin: CGPoint,
        size: CGSize,
    }

    /// Create an autoreleased NSString from a Rust &str.
    unsafe fn nsstring(s: &str) -> *mut Object {
        let obj: *mut Object = msg_send![class!(NSString), alloc];
        msg_send![obj,
            initWithBytes: s.as_ptr()
            length: s.len()
            encoding: 4usize  // NSUTF8StringEncoding
        ]
    }

    // ------------------------------------------------------------------
    // Conversation persistence
    // ------------------------------------------------------------------

    fn conversation_path() -> std::path::PathBuf {
        std::path::PathBuf::from(super::home_dir())
            .join(".openjarvis")
            .join("overlay-conversation.json")
    }

    pub fn load_conversation() -> String {
        std::fs::read_to_string(conversation_path()).unwrap_or_else(|_| "[]".into())
    }

    /// Read cloud API keys and return a JSON array of model IDs
    /// whose provider has a key configured.
    fn cloud_models_json() -> String {
        let keys = super::read_cloud_keys();
        let mut models: Vec<&str> = Vec::new();
        for (name, value) in &keys {
            if value.is_empty() {
                continue;
            }
            match name.as_str() {
                "OPENAI_API_KEY" => models.extend(["gpt-4o", "gpt-4o-mini"]),
                "ANTHROPIC_API_KEY" => {
                    models.extend(["claude-sonnet-4-20250514", "claude-haiku-4-20250414"])
                }
                "GEMINI_API_KEY" | "GOOGLE_API_KEY" => {
                    models.extend(["gemini-2.5-flash", "gemini-2.5-pro"])
                }
                _ => {}
            }
        }
        serde_json::to_string(&models).unwrap_or_else(|_| "[]".into())
    }

    fn save_conversation(json: &str) {
        let path = conversation_path();
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let _ = std::fs::write(&path, json);
    }

    /// Apply every transparency trick to the WKWebView.
    /// Called once at creation and again after the page finishes loading.
    unsafe fn force_transparent(wv: *mut Object) {
        let clear: *mut Object = msg_send![class!(NSColor), clearColor];
        let _: () = msg_send![wv, _setDrawsBackground: NO];
        let no_num: *mut Object = msg_send![class!(NSNumber), numberWithBool: NO];
        let _: () = msg_send![wv, setValue: no_num forKey: nsstring("drawsBackground")];
        let _: () = msg_send![wv, setUnderPageBackgroundColor: clear];
        // Also inject CSS to nuke any remaining background
        let js = nsstring(
            "document.documentElement.style.background='transparent';\
             document.body.style.background='transparent';",
        );
        let nil: *mut Object = std::ptr::null_mut();
        let _: () = msg_send![wv, evaluateJavaScript: js completionHandler: nil];
    }

    // ------------------------------------------------------------------
    // Public API (must be called on the main thread)
    // ------------------------------------------------------------------

    /// Build the native overlay panel.  Call once during app setup.
    pub unsafe fn create(html: &str, api_port: u16) {
        // --- Custom NSPanel subclass that accepts keyboard input ------
        if Class::get("JarvisOverlayPanel").is_none() {
            let sup = Class::get("NSPanel").unwrap();
            let mut decl = ClassDecl::new("JarvisOverlayPanel", sup).unwrap();
            extern "C" fn yes(_: &Object, _: Sel) -> BOOL {
                YES
            }
            decl.add_method(
                sel!(canBecomeKeyWindow),
                yes as extern "C" fn(&Object, Sel) -> BOOL,
            );
            decl.register();
        }

        // --- WKNavigationDelegate — re-apply transparency after load --
        if Class::get("JarvisOverlayNavDelegate").is_none() {
            let sup = Class::get("NSObject").unwrap();
            let mut decl = ClassDecl::new("JarvisOverlayNavDelegate", sup).unwrap();
            extern "C" fn did_finish(_: &Object, _: Sel, wv: *mut Object, _nav: *mut Object) {
                unsafe {
                    force_transparent(wv);
                }
            }
            decl.add_method(
                sel!(webView:didFinishNavigation:),
                did_finish as extern "C" fn(&Object, Sel, *mut Object, *mut Object),
            );
            decl.register();
        }

        // --- WKScriptMessageHandler so JS can call hide() ------------
        if Class::get("JarvisOverlayMsgHandler").is_none() {
            let sup = Class::get("NSObject").unwrap();
            let mut decl = ClassDecl::new("JarvisOverlayMsgHandler", sup).unwrap();
            extern "C" fn on_msg(_: &Object, _: Sel, _ctrl: *mut Object, msg: *mut Object) {
                unsafe {
                    let body: *mut Object = msg_send![msg, body];
                    if body.is_null() {
                        return;
                    }
                    let c: *const std::os::raw::c_char = msg_send![body, UTF8String];
                    if c.is_null() {
                        return;
                    }
                    if let Ok(s) = std::ffi::CStr::from_ptr(c).to_str() {
                        if s == "hide" {
                            hide();
                        } else if let Some(json) = s.strip_prefix("save:") {
                            save_conversation(json);
                        } else if let Some(coords) = s.strip_prefix("drag:") {
                            drag(coords);
                        }
                    }
                }
            }
            decl.add_method(
                sel!(userContentController:didReceiveScriptMessage:),
                on_msg as extern "C" fn(&Object, Sel, *mut Object, *mut Object),
            );
            decl.register();
        }

        // --- Create the NSPanel --------------------------------------
        let frame = CGRect {
            origin: CGPoint { x: 0.0, y: 0.0 },
            size: CGSize {
                width: 560.0,
                height: 400.0,
            },
        };
        // NSWindowStyleMaskNonactivatingPanel = 1 << 7
        let style: u64 = 1 << 7;

        let cls = Class::get("JarvisOverlayPanel").unwrap();
        let panel: *mut Object = msg_send![cls, alloc];
        let panel: *mut Object = msg_send![panel,
            initWithContentRect: frame
            styleMask: style
            backing: 2u64       // NSBackingStoreBuffered
            defer: NO
        ];

        // Window level — NSFloatingWindowLevel (3).
        let _: () = msg_send![panel, setLevel: 3_i64];
        // canJoinAllSpaces (1) | fullScreenAuxiliary (1<<8)
        let _: () = msg_send![panel, setCollectionBehavior: 257_u64];
        let _: () = msg_send![panel, setHidesOnDeactivate: NO];
        let _: () = msg_send![panel, setOpaque: NO];
        let _: () = msg_send![panel, setHasShadow: NO];
        let _: () = msg_send![panel, setMovableByWindowBackground: YES];

        let clear: *mut Object = msg_send![class!(NSColor), clearColor];
        let _: () = msg_send![panel, setBackgroundColor: clear];
        let _: () = msg_send![panel, center];

        // --- WKWebView -----------------------------------------------
        let cfg: *mut Object = msg_send![class!(WKWebViewConfiguration), alloc];
        let cfg: *mut Object = msg_send![cfg, init];

        // Attach message handler ("overlay" channel)
        let hcls = Class::get("JarvisOverlayMsgHandler").unwrap();
        let handler: *mut Object = msg_send![hcls, alloc];
        let handler: *mut Object = msg_send![handler, init];
        let uc: *mut Object = msg_send![cfg, userContentController];
        let _: () = msg_send![uc,
            addScriptMessageHandler: handler
            name: nsstring("overlay")
        ];

        let wv: *mut Object = msg_send![class!(WKWebView), alloc];
        let wv: *mut Object = msg_send![wv,
            initWithFrame: frame
            configuration: cfg
        ];

        // ---- Make the webview fully transparent ----
        force_transparent(wv);

        // Set navigation delegate so we re-apply after page loads
        let nav_cls = Class::get("JarvisOverlayNavDelegate").unwrap();
        let nav_del: *mut Object = msg_send![nav_cls, alloc];
        let nav_del: *mut Object = msg_send![nav_del, init];
        let _: () = msg_send![wv, setNavigationDelegate: nav_del];

        let _: () = msg_send![panel, setContentView: wv];
        WEBVIEW_PTR.store(wv as usize, Ordering::SeqCst);

        // Inject saved conversation into the HTML template, then load it.
        // Use the API server as the base URL so fetch() is same-origin.
        // Escape "</" so the JSON can't prematurely close the <script> tag.
        // ("\/" is valid JSON — resolves back to "/" when parsed.)
        let saved = load_conversation().replace("</", "<\\/");
        let cloud = cloud_models_json();
        let filled = html
            .replace("__SAVED_MESSAGES__", &saved)
            .replace("__CLOUD_MODELS__", &cloud);
        let base_str = nsstring(&format!("http://127.0.0.1:{}", api_port));
        let base_url: *mut Object = msg_send![class!(NSURL), URLWithString: base_str];
        let _: () = msg_send![wv,
            loadHTMLString: nsstring(&filled)
            baseURL: base_url
        ];

        PANEL_PTR.store(panel as usize, Ordering::SeqCst);
    }

    pub unsafe fn toggle() {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;
        let vis: BOOL = msg_send![panel, isVisible];
        if vis != NO {
            hide();
        } else {
            show();
        }
    }

    pub unsafe fn show() {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;

        // Re-apply transparency every time (the webview can reset it)
        let wv_ptr = WEBVIEW_PTR.load(Ordering::SeqCst);
        if wv_ptr != 0 {
            force_transparent(wv_ptr as *mut Object);
        }

        // Remember the currently-frontmost app so we can restore it.
        let ws: *mut Object = msg_send![class!(NSWorkspace), sharedWorkspace];
        let front: *mut Object = msg_send![ws, frontmostApplication];
        if !front.is_null() {
            let _: () = msg_send![front, retain];
            let old = PREV_APP.swap(front as usize, Ordering::SeqCst);
            if old != 0 {
                let _: () = msg_send![(old as *mut Object), release];
            }
        }

        // Activate our process so the panel receives keyboard input.
        let app: *mut Object = msg_send![class!(NSApplication), sharedApplication];
        let _: () = msg_send![app, activateIgnoringOtherApps: YES];
        let nil: *mut Object = std::ptr::null_mut();
        let _: () = msg_send![panel, makeKeyAndOrderFront: nil];

        // Focus the text field inside the webview.
        let wv: *mut Object = msg_send![panel, contentView];
        let js = nsstring("document.getElementById('input').focus()");
        let _: () = msg_send![wv, evaluateJavaScript: js completionHandler: nil];
    }

    /// Move the panel by a screen-space delta (called from JS drag handler).
    unsafe fn drag(coords: &str) {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;
        let Some((dxs, dys)) = coords.split_once(',') else {
            return;
        };
        let Ok(dx) = dxs.parse::<f64>() else { return };
        let Ok(dy) = dys.parse::<f64>() else { return };
        // NSWindow frame origin is bottom-left; screen Y increases upward,
        // but mouse screenY increases downward, so invert dy.
        let frame: CGRect = msg_send![panel, frame];
        let origin = CGPoint {
            x: frame.origin.x + dx,
            y: frame.origin.y - dy,
        };
        let _: () = msg_send![panel, setFrameOrigin: origin];
    }

    pub unsafe fn hide() {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;
        let nil: *mut Object = std::ptr::null_mut();
        let _: () = msg_send![panel, orderOut: nil];

        // Give focus back to whatever app was frontmost before.
        let prev = PREV_APP.swap(0, Ordering::SeqCst);
        if prev != 0 {
            let prev_app = prev as *mut Object;
            let _: BOOL = msg_send![prev_app, activateWithOptions: 2_u64];
            let _: () = msg_send![prev_app, release];
        }
    }
}

/// Dispatch a closure onto the main thread via GCD.
#[cfg(target_os = "macos")]
fn on_main_thread(f: impl FnOnce() + Send + 'static) {
    dispatch::Queue::main().exec_async(f);
}

// ---------------------------------------------------------------------------
// Overlay Tauri commands (thin wrappers that dispatch to the main thread)
// ---------------------------------------------------------------------------

#[tauri::command]
async fn get_overlay_conversation() -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        return Ok(native_overlay::load_conversation());
    }
    #[cfg(not(target_os = "macos"))]
    Ok("[]".into())
}

#[tauri::command]
async fn toggle_overlay() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    on_main_thread(|| unsafe { native_overlay::toggle() });
    Ok(())
}

#[tauri::command]
async fn hide_overlay() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    on_main_thread(|| unsafe { native_overlay::hide() });
    Ok(())
}

// ---------------------------------------------------------------------------
// App entry point
// ---------------------------------------------------------------------------

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend: SharedBackend = Arc::new(Mutex::new(BackendManager::default()));
    let configured_at_launch = match read_configured_inference_config() {
        Some(cfg) if cfg.confirmed => {
            // A confirmed source never consumes a staging slot. Clear any
            // remnant from a prior interrupted config write.
            let _ = secure_store_set(PENDING_INFERENCE_API_KEY, "");
            Some(cfg)
        }
        Some(_) => {
            // A prior first-run boot was interrupted or failed before it
            // reached ready. Never replay that unvalidated choice on launch.
            let _ = discard_pending_inference_setup();
            None
        }
        None => {
            // Clean up a stage left behind if the process exited between the
            // secure-store write and the pending config write.
            let _ = secure_store_set(PENDING_INFERENCE_API_KEY, "");
            None
        }
    };
    let initial_status = configured_at_launch
        .as_ref()
        .map(SetupStatus::starting)
        .unwrap_or_default();
    let status: SharedStatus = Arc::new(Mutex::new(initial_status));

    let boot_backend_ref = backend.clone();
    let boot_status_ref = status.clone();

    tauri::Builder::default()
        .manage(backend.clone())
        .manage(status.clone())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--hidden"]),
        ))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .setup(move |app| {
            // System tray
            let show = MenuItemBuilder::with_id("show", "Show / Hide").build(app)?;
            let health = MenuItemBuilder::with_id("health", "Health: starting...")
                .enabled(false)
                .build(app)?;
            let quit = MenuItemBuilder::with_id("quit", "Quit OpenJarvis").build(app)?;

            let menu = MenuBuilder::new(app)
                .item(&show)
                .separator()
                .item(&health)
                .separator()
                .item(&quit)
                .build()?;

            let _tray = TrayIconBuilder::with_id("main")
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("OpenJarvis")
                .menu(&menu)
                .on_menu_event(move |app, event| match event.id().as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            if window.is_visible().unwrap_or(false) {
                                let _ = window.hide();
                            } else {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;

            // Create native macOS overlay panel
            #[cfg(target_os = "macos")]
            unsafe {
                native_overlay::create(include_str!("overlay.html"), JARVIS_PORT);
            }

            // Register Cmd+Shift+Space to toggle the overlay
            {
                use tauri_plugin_global_shortcut::{
                    Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState,
                };
                let sc = Shortcut::new(Some(Modifiers::META | Modifiers::SHIFT), Code::Space);
                if let Err(e) = app.global_shortcut().on_shortcut(sc, |_app, _sc, ev| {
                    if ev.state == ShortcutState::Pressed {
                        #[cfg(target_os = "macos")]
                        unsafe {
                            native_overlay::toggle();
                        }
                    }
                }) {
                    eprintln!("Warning: could not register Cmd+Shift+Space: {e}");
                }
            }

            // Returning users keep automatic startup after they have persisted
            // a source. Fresh installs stay inert until the setup UI records
            // explicit consent and invokes `start_backend`.
            if configured_at_launch.is_some() {
                tauri::async_runtime::spawn(start_managed_boot(boot_backend_ref, boot_status_ref));
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_setup_status,
            get_api_base,
            start_backend,
            stop_backend,
            reset_inference_source,
            check_health,
            fetch_energy,
            fetch_telemetry,
            fetch_traces,
            fetch_trace,
            fetch_learning_stats,
            fetch_learning_policy,
            fetch_memory_stats,
            search_memory,
            fetch_agents,
            fetch_models,
            run_jarvis_command,
            fetch_savings,
            submit_savings,
            transcribe_audio,
            speech_health,
            pull_ollama_model,
            delete_ollama_model,
            save_cloud_key,
            get_cloud_key_status,
            get_inference_source,
            set_inference_source,
            toggle_overlay,
            hide_overlay,
            get_overlay_conversation,
        ])
        .build(tauri::generate_context!())
        .expect("error while building OpenJarvis Desktop")
        .run(move |_app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                let b = backend.clone();
                tauri::async_runtime::spawn(async move {
                    b.lock().await.stop_all().await;
                });
            }
        });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::{
        boot_plan, default_local_model, discard_pending_inference_setup_at,
        format_extension_import_failure, format_missing_rust_toolchain, format_port_unavailable,
        format_uv_sync_failure, format_uv_sync_spawn_error, matching_installed_model,
        model_names_match, normalize_host, parse_configured_inference_config,
        parse_ollama_model_names, persist_confirmed_inference_config_at, preferred_installed_model,
        reload_cloud_keys_for_owned_backend_at, should_persist_resolved_model, spawn_owned_child,
        stage_pending_inference_config_at, startup_installed_model, upsert_engine_host,
        uv_sync_stderr_tail, BackendManager, InferenceConfig, InferenceCredentialStore,
        PendingInferenceRollback, SetupStatus, SourceKind, DESKTOP_UV_SYNC_COMMAND,
        PENDING_INFERENCE_API_KEY,
    };
    use std::collections::HashMap;
    use std::path::Path;
    use std::sync::Mutex as StdMutex;

    #[derive(Default)]
    struct MemoryCredentialStore {
        values: StdMutex<HashMap<String, String>>,
    }

    impl MemoryCredentialStore {
        fn put(&self, key_name: &str, key_value: &str) {
            self.values
                .lock()
                .unwrap()
                .insert(key_name.to_string(), key_value.to_string());
        }

        fn value(&self, key_name: &str) -> Option<String> {
            self.values.lock().unwrap().get(key_name).cloned()
        }
    }

    impl InferenceCredentialStore for MemoryCredentialStore {
        fn get(&self, key_name: &str) -> Result<Option<String>, String> {
            Ok(self.value(key_name))
        }

        fn set(&self, key_name: &str, key_value: &str) -> Result<(), String> {
            let mut values = self.values.lock().unwrap();
            if key_value.is_empty() {
                values.remove(key_name);
            } else {
                values.insert(key_name.to_string(), key_value.to_string());
            }
            Ok(())
        }
    }

    fn unique_test_root(label: &str) -> std::path::PathBuf {
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "openjarvis-{}-{}-{}",
            label,
            std::process::id(),
            nonce
        ))
    }

    #[test]
    fn tail_returns_whole_string_when_shorter_than_limit() {
        assert_eq!(uv_sync_stderr_tail("short error", 800), "short error");
    }

    #[test]
    fn tail_keeps_the_end_not_the_beginning() {
        // uv's actionable line is at the end; the spinner noise is at the start.
        let s = format!("{}ACTUAL ERROR HERE", "spinner-noise ".repeat(200));
        let tail = uv_sync_stderr_tail(&s, 40);
        assert!(tail.ends_with("ACTUAL ERROR HERE"), "tail was: {tail:?}");
        assert!(!tail.contains("spinner-noise spinner-noise spinner-noise"));
        assert!(tail.chars().count() <= 40);
    }

    #[test]
    fn tail_trims_surrounding_whitespace() {
        assert_eq!(uv_sync_stderr_tail("  \n padded \n  ", 800), "padded");
    }

    #[test]
    fn tail_never_splits_a_multibyte_codepoint() {
        // Each "é" is 2 bytes / 1 char. A byte-based slice could panic or
        // produce invalid UTF-8; the char-based tail must not.
        let s = "é".repeat(500);
        let tail = uv_sync_stderr_tail(&s, 100);
        assert_eq!(tail.chars().count(), 100);
        assert!(tail.chars().all(|c| c == 'é'));
    }

    #[test]
    fn failure_message_includes_exit_code_and_tail_and_hint() {
        let msg = format_uv_sync_failure(
            Path::new("/home/u/.openjarvis/src"),
            Some(2),
            "error: failed to resolve numpy==2.1.3",
        );
        assert!(msg.contains("exit 2"));
        assert!(msg.contains("/home/u/.openjarvis/src"));
        assert!(msg.contains("failed to resolve numpy==2.1.3"));
        assert!(msg.contains(DESKTOP_UV_SYNC_COMMAND)); // actionable next step
    }

    #[test]
    fn failure_message_renders_missing_exit_code_as_unknown() {
        // Process killed by signal → no exit code. Must not show a misleading -1.
        let msg = format_uv_sync_failure(Path::new("/x"), None, "boom");
        assert!(msg.contains("exit unknown"));
        assert!(!msg.contains("exit -1"));
    }

    #[test]
    fn spawn_error_names_the_binary_and_root() {
        let msg = format_uv_sync_spawn_error(
            Path::new("/repo"),
            "C:\\Users\\me\\.local\\bin\\uv.exe",
            "No such file or directory (os error 2)",
        );
        assert!(msg.contains("C:\\Users\\me\\.local\\bin\\uv.exe"));
        assert!(msg.contains("/repo"));
        assert!(msg.contains("No such file or directory"));
    }

    #[test]
    fn missing_rust_toolchain_message_names_cargo_and_installer() {
        let msg = format_missing_rust_toolchain();
        assert!(msg.contains("cargo"));
        assert!(msg.contains("https://rustup.rs"));
        assert!(msg.contains("openjarvis_rust"));
        assert!(msg.contains("Visual Studio Build Tools"));
    }

    #[test]
    fn uv_sync_rust_failure_mentions_toolchain() {
        let msg = format_uv_sync_failure(
            Path::new("C:\\Users\\me\\OpenJarvis"),
            Some(1),
            "maturin failed: linker `link.exe` not found while building openjarvis-rust",
        );
        assert!(msg.contains("exit 1"));
        assert!(msg.contains("link.exe"));
        assert!(msg.contains("https://rustup.rs"));
        assert!(msg.contains("Visual Studio Build Tools"));
    }

    #[test]
    fn extension_import_failure_names_verification_command() {
        let msg = format_extension_import_failure(
            Path::new("C:\\Users\\me\\OpenJarvis"),
            "ModuleNotFoundError: No module named 'openjarvis_rust'",
        );
        assert!(msg.contains("openjarvis_rust"));
        assert!(msg.contains(DESKTOP_UV_SYNC_COMMAND));
        assert!(msg.contains("uv run python -c \"import openjarvis_rust\""));
        assert!(msg.contains("ModuleNotFoundError"));
    }

    #[test]
    fn port_unavailable_message_names_port_and_owner_hint() {
        let msg = format_port_unavailable(8000, "address already in use");
        assert!(msg.contains("Port 8000 is not available"));
        assert!(msg.contains("address already in use"));
        assert!(msg.contains("To identify it"));
        assert!(msg.contains("8000"));
    }

    #[test]
    fn default_local_model_picks_second_largest_that_fits() {
        // QWEN35_MODELS min_ram ladder: 4,6,8,12,24,32,96 GB
        assert_eq!(default_local_model(4.0), "qwen3.5:0.8b"); // only one fits
        assert_eq!(default_local_model(8.0), "qwen3.5:2b"); // fits 0.8/2/4 → 2nd-largest
        assert_eq!(default_local_model(16.0), "qwen3.5:4b"); // fits ..9b → 2nd-largest
        assert_eq!(default_local_model(32.0), "qwen3.5:27b"); // fits 0.8/2/4/9/27/35b → 2nd-largest is 27b
        assert_eq!(default_local_model(128.0), "qwen3.5:35b"); // fits all → 2nd-largest
    }

    #[test]
    fn default_local_model_falls_back_when_nothing_fits() {
        assert_eq!(default_local_model(1.0), super::FALLBACK_MODEL);
    }

    #[test]
    fn parse_ollama_model_names_reads_nonempty_names() {
        let body = serde_json::json!({
            "models": [
                {"name": "llama3.2:latest"},
                {"name": ""},
                {"name": "qwen3.5:4b"},
                {"model": "mistral:latest"}
            ]
        });
        assert_eq!(
            parse_ollama_model_names(&body),
            vec![
                "llama3.2:latest".to_string(),
                "qwen3.5:4b".to_string(),
                "mistral:latest".to_string()
            ]
        );
    }

    #[test]
    fn model_names_match_treats_latest_as_optional() {
        assert!(model_names_match("llama3.2:latest", "llama3.2"));
        assert!(model_names_match("llama3.2", "llama3.2:latest"));
        assert!(model_names_match("qwen3.5:4b", "qwen3.5:4b"));
        assert!(!model_names_match("llama3.2:latest", "qwen3.5:4b"));
    }

    #[test]
    fn installed_model_helpers_pick_matching_or_first_model() {
        let models = vec!["llama3.2:latest".to_string(), "qwen3.5:4b".to_string()];
        assert_eq!(
            matching_installed_model(&models, "llama3.2"),
            Some("llama3.2:latest".to_string())
        );
        assert_eq!(
            preferred_installed_model(&models),
            Some("llama3.2:latest".to_string())
        );
    }

    #[test]
    fn preferred_installed_model_skips_embedding_names_when_chat_model_exists() {
        let models = vec![
            "nomic-embed-text:latest".to_string(),
            "llama3.2:latest".to_string(),
        ];
        assert_eq!(
            preferred_installed_model(&models),
            Some("llama3.2:latest".to_string())
        );
    }

    #[test]
    fn startup_installed_model_uses_existing_model_for_defaults() {
        let models = vec!["llama3.2:latest".to_string()];
        assert_eq!(
            startup_installed_model("qwen3.5:4b", &models),
            Some("llama3.2:latest".to_string())
        );
    }

    #[test]
    fn startup_installed_model_uses_existing_model_when_configured_model_missing() {
        let models = vec!["llama3.2:latest".to_string()];
        assert_eq!(
            startup_installed_model("qwen3.5:4b", &models),
            Some("llama3.2:latest".to_string())
        );
    }

    #[test]
    fn resolved_model_is_only_persisted_when_no_model_was_configured() {
        let default_cfg = InferenceConfig {
            kind: SourceKind::Ollama,
            ..Default::default()
        };
        assert!(should_persist_resolved_model(&default_cfg));

        let empty_cfg = InferenceConfig {
            kind: SourceKind::Ollama,
            model: Some(" ".into()),
            ..Default::default()
        };
        assert!(should_persist_resolved_model(&empty_cfg));

        let user_cfg = InferenceConfig {
            kind: SourceKind::Ollama,
            model: Some("qwen3.5:9b".into()),
            ..Default::default()
        };
        assert!(!should_persist_resolved_model(&user_cfg));
    }

    #[test]
    fn startup_requires_an_explicit_valid_source_config() {
        assert!(parse_configured_inference_config("").is_none());
        assert!(parse_configured_inference_config("not json").is_none());
        assert!(parse_configured_inference_config("{}").is_none());

        let ollama = parse_configured_inference_config(r#"{"kind":"ollama"}"#).unwrap();
        assert!(matches!(ollama.kind, SourceKind::Ollama));
        assert!(ollama.confirmed, "legacy explicit configs remain trusted");

        let custom = parse_configured_inference_config(
            r#"{"kind":"custom","model":"m","host":"http://localhost:1234"}"#,
        )
        .unwrap();
        assert!(matches!(custom.kind, SourceKind::Custom));
        assert!(custom.confirmed);

        let pending = parse_configured_inference_config(
            r#"{"kind":"custom","confirmed":false,"model":"m","host":"http://localhost:1234"}"#,
        )
        .unwrap();
        assert!(!pending.confirmed);
    }

    #[test]
    fn initial_setup_status_is_inert_until_a_source_is_chosen() {
        let status = SetupStatus::default();
        assert!(status.requires_source);
        assert_eq!(status.phase, "awaiting_source");
        assert_eq!(status.source, "unconfigured");
        assert!(!status.ollama_ready);
        assert!(!status.model_ready);
        assert!(!status.server_ready);
    }

    #[test]
    fn persisted_source_status_can_enter_startup() {
        let cfg = InferenceConfig {
            kind: SourceKind::Custom,
            confirmed: true,
            model: Some("m".into()),
            host: Some("http://localhost:1234".into()),
            engine: Some("lmstudio".into()),
        };
        let status = SetupStatus::starting(&cfg);
        assert!(!status.requires_source);
        assert_eq!(status.phase, "starting");
        assert_eq!(status.source, "custom");
    }

    #[test]
    fn parse_reads_custom_endpoint() {
        let cfg = parse_configured_inference_config(
            r#"{"kind":"custom","model":"qwen2.5-7b","host":"http://localhost:1234","engine":"lmstudio"}"#,
        )
        .unwrap();
        assert!(matches!(cfg.kind, SourceKind::Custom));
        assert_eq!(cfg.model.as_deref(), Some("qwen2.5-7b"));
        assert_eq!(cfg.host.as_deref(), Some("http://localhost:1234"));
        assert_eq!(cfg.engine.as_deref(), Some("lmstudio"));
    }

    #[test]
    fn normalize_host_strips_trailing_slash_and_v1() {
        assert_eq!(
            normalize_host("http://localhost:1234/v1"),
            "http://localhost:1234"
        );
        assert_eq!(
            normalize_host("http://localhost:1234/v1/"),
            "http://localhost:1234"
        );
        assert_eq!(
            normalize_host("http://localhost:1234/"),
            "http://localhost:1234"
        );
        assert_eq!(normalize_host("http://host:8000"), "http://host:8000");
    }

    #[test]
    fn boot_plan_ollama_launches_and_pulls_one_model() {
        let cfg = InferenceConfig {
            kind: SourceKind::Ollama,
            ..Default::default()
        };
        let plan = boot_plan(&cfg, 16.0);
        assert!(plan.launch_ollama);
        assert_eq!(plan.model_to_pull.as_deref(), Some("qwen3.5:4b"));
        assert!(plan.engine_host.is_none());
        assert!(plan
            .serve_args
            .windows(2)
            .any(|w| w == ["--engine", "ollama"]));
        assert!(plan
            .serve_args
            .windows(2)
            .any(|w| w == ["--model", "qwen3.5:4b"]));
    }

    #[test]
    fn boot_plan_ollama_respects_pinned_model() {
        let cfg = InferenceConfig {
            kind: SourceKind::Ollama,
            model: Some("qwen3.5:9b".into()),
            ..Default::default()
        };
        let plan = boot_plan(&cfg, 16.0);
        assert_eq!(plan.model_to_pull.as_deref(), Some("qwen3.5:9b"));
    }

    #[test]
    fn boot_plan_custom_skips_ollama_and_sets_engine_host() {
        let cfg = InferenceConfig {
            kind: SourceKind::Custom,
            confirmed: true,
            model: Some("qwen2.5-7b".into()),
            host: Some("http://localhost:1234".into()),
            engine: Some("lmstudio".into()),
        };
        let plan = boot_plan(&cfg, 16.0);
        assert!(!plan.launch_ollama);
        assert!(plan.model_to_pull.is_none());
        assert_eq!(
            plan.engine_host,
            Some(("lmstudio".to_string(), "http://localhost:1234".to_string()))
        );
        assert!(plan
            .serve_args
            .windows(2)
            .any(|w| w == ["--engine", "lmstudio"]));
        assert!(plan
            .serve_args
            .windows(2)
            .any(|w| w == ["--model", "qwen2.5-7b"]));
    }

    #[test]
    fn boot_plan_custom_defaults_engine_to_lmstudio() {
        let cfg = InferenceConfig {
            kind: SourceKind::Custom,
            confirmed: true,
            model: Some("m".into()),
            host: Some("http://h:1".into()),
            engine: None,
        };
        let plan = boot_plan(&cfg, 16.0);
        assert_eq!(plan.engine_host.as_ref().unwrap().0, "lmstudio");
        assert!(plan
            .serve_args
            .windows(2)
            .any(|w| w == ["--engine", "lmstudio"]));
    }

    #[test]
    fn boot_plan_custom_omits_engine_host_when_no_host() {
        // No configured host → don't set engine_host (no override to write).
        let cfg = InferenceConfig {
            kind: SourceKind::Custom,
            confirmed: true,
            model: Some("m".into()),
            host: None,
            engine: Some("lmstudio".into()),
        };
        let plan = boot_plan(&cfg, 16.0);
        assert!(plan.engine_host.is_none());
    }

    #[test]
    fn pending_config_rolls_back_unless_boot_confirms_it() {
        let root = std::env::temp_dir().join(format!(
            "openjarvis-pending-inference-{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let pending_path = root.join("pending.json");
        std::fs::write(&pending_path, "pending").unwrap();
        let pending = InferenceConfig {
            kind: SourceKind::Custom,
            confirmed: false,
            model: Some("m".into()),
            host: Some("http://localhost:1".into()),
            engine: Some("lmstudio".into()),
        };

        {
            let _rollback = PendingInferenceRollback::at_path(&pending, pending_path.clone());
        }
        assert!(!pending_path.exists());

        let confirmed_path = root.join("confirmed.json");
        std::fs::write(&confirmed_path, "confirmed").unwrap();
        let mut confirmed = pending;
        confirmed.confirmed = true;
        {
            let _rollback = PendingInferenceRollback::at_path(&confirmed, confirmed_path.clone());
        }
        assert!(confirmed_path.exists());

        let committed_path = root.join("committed.json");
        std::fs::write(&committed_path, "pending").unwrap();
        let mut staged = InferenceConfig {
            kind: SourceKind::Ollama,
            confirmed: false,
            model: Some("qwen3.5:4b".into()),
            host: None,
            engine: None,
        };
        {
            let mut rollback = PendingInferenceRollback::at_path(&staged, committed_path.clone());
            rollback.confirm(&mut staged).unwrap();
        }
        assert!(staged.confirmed);
        assert!(committed_path.exists());
        let committed: InferenceConfig =
            serde_json::from_str(&std::fs::read_to_string(&committed_path).unwrap()).unwrap();
        assert!(committed.confirmed);
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn pending_custom_key_is_staged_without_overwriting_existing_key() {
        let root = unique_test_root("stage-inference-key");
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("inference.json");
        let store = MemoryCredentialStore::default();
        store.put("LMSTUDIO_API_KEY", "existing-key");
        let cfg = InferenceConfig {
            kind: SourceKind::Custom,
            confirmed: false,
            model: Some("m".into()),
            host: Some("http://localhost:1234".into()),
            engine: Some("lmstudio".into()),
        };

        stage_pending_inference_config_at(&cfg, Some("new-key"), &store, &path).unwrap();

        assert_eq!(
            store.value("LMSTUDIO_API_KEY").as_deref(),
            Some("existing-key")
        );
        assert_eq!(
            store.value(PENDING_INFERENCE_API_KEY).as_deref(),
            Some("new-key")
        );
        let staged: InferenceConfig =
            serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
        assert!(!staged.confirmed);
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn cancelled_pending_setup_discards_stage_and_preserves_existing_key() {
        let root = unique_test_root("cancel-inference-key");
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("inference.json");
        let store = std::sync::Arc::new(MemoryCredentialStore::default());
        store.put("LMSTUDIO_API_KEY", "existing-key");
        let cfg = InferenceConfig {
            kind: SourceKind::Custom,
            confirmed: false,
            model: Some("m".into()),
            host: Some("http://localhost:1234".into()),
            engine: Some("lmstudio".into()),
        };
        stage_pending_inference_config_at(&cfg, Some("new-key"), store.as_ref(), &path).unwrap();

        {
            let _rollback =
                PendingInferenceRollback::at_path_with_store(&cfg, path.clone(), store.clone());
        }

        assert!(!path.exists());
        assert_eq!(store.value(PENDING_INFERENCE_API_KEY), None);
        assert_eq!(
            store.value("LMSTUDIO_API_KEY").as_deref(),
            Some("existing-key")
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn successful_pending_setup_promotes_stage_only_at_confirmation() {
        let root = unique_test_root("confirm-inference-key");
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("inference.json");
        let store = std::sync::Arc::new(MemoryCredentialStore::default());
        store.put("LMSTUDIO_API_KEY", "existing-key");
        let mut cfg = InferenceConfig {
            kind: SourceKind::Custom,
            confirmed: false,
            model: Some("m".into()),
            host: Some("http://localhost:1234".into()),
            engine: Some("lmstudio".into()),
        };
        stage_pending_inference_config_at(&cfg, Some("new-key"), store.as_ref(), &path).unwrap();

        {
            let mut rollback =
                PendingInferenceRollback::at_path_with_store(&cfg, path.clone(), store.clone());
            rollback.confirm(&mut cfg).unwrap();
        }

        assert!(cfg.confirmed);
        assert_eq!(store.value(PENDING_INFERENCE_API_KEY), None);
        assert_eq!(store.value("LMSTUDIO_API_KEY").as_deref(), Some("new-key"));
        let confirmed: InferenceConfig =
            serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
        assert!(confirmed.confirmed);
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn failed_confirmation_restores_existing_key_and_leaves_no_stage() {
        let root = unique_test_root("failed-confirm-inference-key");
        let path = root.join("config-is-a-directory");
        std::fs::create_dir_all(&path).unwrap();
        let store = std::sync::Arc::new(MemoryCredentialStore::default());
        store.put("LMSTUDIO_API_KEY", "existing-key");
        store.put(PENDING_INFERENCE_API_KEY, "new-key");
        let mut cfg = InferenceConfig {
            kind: SourceKind::Custom,
            confirmed: false,
            model: Some("m".into()),
            host: Some("http://localhost:1234".into()),
            engine: Some("lmstudio".into()),
        };

        let result = {
            let mut rollback =
                PendingInferenceRollback::at_path_with_store(&cfg, path.clone(), store.clone());
            rollback.confirm(&mut cfg)
        };

        assert!(result.is_err());
        assert!(!cfg.confirmed);
        assert_eq!(store.value(PENDING_INFERENCE_API_KEY), None);
        assert_eq!(
            store.value("LMSTUDIO_API_KEY").as_deref(),
            Some("existing-key")
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn failed_pending_config_write_discards_new_stage() {
        let root = unique_test_root("failed-stage-inference-key");
        let path = root.join("config-is-a-directory");
        std::fs::create_dir_all(&path).unwrap();
        let store = MemoryCredentialStore::default();
        store.put("LMSTUDIO_API_KEY", "existing-key");
        let cfg = InferenceConfig {
            kind: SourceKind::Custom,
            confirmed: false,
            model: Some("m".into()),
            host: Some("http://localhost:1234".into()),
            engine: Some("lmstudio".into()),
        };

        let result = stage_pending_inference_config_at(&cfg, Some("new-key"), &store, &path);

        assert!(result.is_err());
        assert_eq!(store.value(PENDING_INFERENCE_API_KEY), None);
        assert_eq!(
            store.value("LMSTUDIO_API_KEY").as_deref(),
            Some("existing-key")
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn failed_confirmed_config_write_restores_existing_key() {
        let root = unique_test_root("failed-confirmed-inference-key");
        let path = root.join("config-is-a-directory");
        std::fs::create_dir_all(&path).unwrap();
        let store = MemoryCredentialStore::default();
        store.put("LMSTUDIO_API_KEY", "existing-key");
        let cfg = InferenceConfig {
            kind: SourceKind::Custom,
            confirmed: true,
            model: Some("m".into()),
            host: Some("http://localhost:1234".into()),
            engine: Some("lmstudio".into()),
        };

        let result = persist_confirmed_inference_config_at(&cfg, Some("new-key"), &store, &path);

        assert!(result.is_err());
        assert_eq!(
            store.value("LMSTUDIO_API_KEY").as_deref(),
            Some("existing-key")
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn reset_discards_pending_config_and_stage_without_touching_existing_key() {
        let root = unique_test_root("reset-inference-key");
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("inference.json");
        std::fs::write(&path, "pending").unwrap();
        let store = MemoryCredentialStore::default();
        store.put("LMSTUDIO_API_KEY", "existing-key");
        store.put(PENDING_INFERENCE_API_KEY, "new-key");

        discard_pending_inference_setup_at(&path, &store).unwrap();

        assert!(!path.exists());
        assert_eq!(store.value(PENDING_INFERENCE_API_KEY), None);
        assert_eq!(
            store.value("LMSTUDIO_API_KEY").as_deref(),
            Some("existing-key")
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[tokio::test]
    async fn ready_port_squatter_never_receives_cloud_key_without_owned_child() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let reload_url = format!("http://{}/v1/cloud/reload", listener.local_addr().unwrap());
        let backend = std::sync::Arc::new(tokio::sync::Mutex::new(BackendManager::default()));
        let mut setup_status = SetupStatus::default();
        setup_status.server_ready = true;
        let status = std::sync::Arc::new(tokio::sync::Mutex::new(setup_status));

        reload_cloud_keys_for_owned_backend_at(
            &backend,
            &status,
            vec![("OPENAI_API_KEY".into(), "must-not-leak".into())],
            &reload_url,
        )
        .await;

        let error = listener.accept().unwrap_err();
        assert_eq!(error.kind(), std::io::ErrorKind::WouldBlock);
    }

    #[tokio::test]
    async fn stopping_backend_aborts_the_tracked_boot_task() {
        use std::sync::atomic::{AtomicBool, Ordering};
        use std::sync::Arc;

        struct DropSignal(Arc<AtomicBool>);
        impl Drop for DropSignal {
            fn drop(&mut self) {
                self.0.store(true, Ordering::SeqCst);
            }
        }

        let dropped = Arc::new(AtomicBool::new(false));
        let signal = DropSignal(dropped.clone());
        let task = tokio::spawn(async move {
            let _signal = signal;
            std::future::pending::<()>().await;
        });
        tokio::task::yield_now().await;

        let mut manager = BackendManager::default();
        manager.boot_task = Some(tauri::async_runtime::JoinHandle::Tokio(task));
        manager.stop_all().await;

        assert!(manager.boot_task.is_none());
        assert!(
            dropped.load(Ordering::SeqCst),
            "stop_all must not return before the aborted boot future is dropped"
        );
    }

    #[test]
    fn owned_child_process_helper() {
        let Some(started) = std::env::var_os("OPENJARVIS_OWNED_CHILD_STARTED") else {
            return;
        };
        let completed = std::env::var_os("OPENJARVIS_OWNED_CHILD_COMPLETED").unwrap();
        std::fs::write(started, "started").unwrap();
        std::thread::sleep(std::time::Duration::from_millis(500));
        std::fs::write(completed, "completed").unwrap();
    }

    #[tokio::test]
    async fn aborting_boot_kills_child_before_manager_registration() {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "openjarvis-owned-child-{}-{unique}",
            std::process::id()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let started = root.join("started");
        let completed = root.join("completed");

        let (spawned_tx, spawned_rx) = tokio::sync::oneshot::channel();
        let started_for_child = started.clone();
        let completed_for_child = completed.clone();
        let task = tokio::spawn(async move {
            let mut cmd = tokio::process::Command::new(std::env::current_exe().unwrap());
            cmd.args([
                "--exact",
                "tests::owned_child_process_helper",
                "--nocapture",
            ])
            .env("OPENJARVIS_OWNED_CHILD_STARTED", started_for_child)
            .env("OPENJARVIS_OWNED_CHILD_COMPLETED", completed_for_child)
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null());
            let child = spawn_owned_child(&mut cmd).unwrap();
            spawned_tx.send(()).unwrap();
            let _unregistered_child = child;
            std::future::pending::<()>().await;
        });
        spawned_rx.await.unwrap();

        for _ in 0..100 {
            if started.exists() {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
        assert!(started.exists(), "helper process did not start");

        task.abort();
        let _ = task.await;
        tokio::time::sleep(std::time::Duration::from_millis(700)).await;

        assert!(
            !completed.exists(),
            "an aborted boot task left its not-yet-registered child running"
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn boot_plan_ollama_uses_fallback_model_on_low_ram() {
        // Below the smallest model's min_ram → default_local_model → FALLBACK_MODEL.
        let cfg = InferenceConfig {
            kind: SourceKind::Ollama,
            ..Default::default()
        };
        let plan = boot_plan(&cfg, 1.0);
        assert_eq!(plan.model_to_pull.as_deref(), Some(super::FALLBACK_MODEL));
    }

    #[test]
    fn upsert_engine_host_writes_into_empty_config() {
        let out = upsert_engine_host("", "lmstudio", "http://localhost:1234").unwrap();
        let doc: toml_edit::DocumentMut = out.parse().unwrap();
        assert_eq!(
            doc["engine"]["lmstudio"]["host"].as_str(),
            Some("http://localhost:1234")
        );
    }

    #[test]
    fn upsert_engine_host_preserves_existing_content() {
        let existing = "[intelligence]\ndefault_model = \"keep-me\"\n";
        let out = upsert_engine_host(existing, "vllm", "http://host:8000").unwrap();
        let doc: toml_edit::DocumentMut = out.parse().unwrap();
        assert_eq!(
            doc["intelligence"]["default_model"].as_str(),
            Some("keep-me")
        );
        assert_eq!(
            doc["engine"]["vllm"]["host"].as_str(),
            Some("http://host:8000")
        );
    }

    #[test]
    fn upsert_engine_host_updates_existing_host() {
        let existing = "[engine.lmstudio]\nhost = \"http://old:1\"\n";
        let out = upsert_engine_host(existing, "lmstudio", "http://new:2").unwrap();
        let doc: toml_edit::DocumentMut = out.parse().unwrap();
        assert_eq!(
            doc["engine"]["lmstudio"]["host"].as_str(),
            Some("http://new:2")
        );
    }

    // -----------------------------------------------------------------
    // #455 — AppImage subprocess env-strip helper
    // -----------------------------------------------------------------
    //
    // `prepare_subprocess_for_appimage` strips LD_LIBRARY_PATH (and the
    // related AppImage runtime variables) from a child `Command` ONLY
    // when the parent process is itself running inside an AppImage —
    // detected by the presence of the `APPIMAGE` env variable that the
    // AppImage runtime sets to the original .AppImage path. We can't
    // observe the env_remove calls directly through tokio's Command
    // API (it doesn't expose its env map publicly), so these tests
    // exercise the documented contract on each platform:
    //
    //   * on macOS / Windows: the function is a no-op regardless of env.
    //   * on Linux without $APPIMAGE: also a no-op.
    //   * on Linux with $APPIMAGE: it doesn't panic, doesn't return an
    //     error, and the calling code that follows succeeds. The
    //     observable behaviour test is the integration repro on a real
    //     AppImage build (covered in PR test plan).
    //
    // The Mutex serialises any test that touches the process-wide
    // `APPIMAGE` env var so cargo test's parallel runner can't race two
    // tests setting and unsetting it concurrently. `static Mutex` works
    // on a const path since Rust 1.63 (and Tauri's MSRV is well above).

    static APPIMAGE_ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    // Pick a binary that exists on every test target so the test body is
    // doing something other than constructing an obviously-broken command
    // path on Windows.
    #[cfg(target_os = "windows")]
    const HARMLESS_BIN: &str = "cmd";
    #[cfg(not(target_os = "windows"))]
    const HARMLESS_BIN: &str = "/bin/true";

    #[test]
    fn prepare_subprocess_for_appimage_no_appimage_is_safe() {
        let _guard = APPIMAGE_ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let prev = std::env::var_os("APPIMAGE");
        // SAFETY: APPIMAGE_ENV_LOCK serialises every test that touches
        // this env var, so the mutation is single-threaded for the
        // duration of the lock. The 2024-edition env mutation rules
        // require the `unsafe` block but the guard makes it sound.
        unsafe {
            std::env::remove_var("APPIMAGE");
        }
        let mut cmd = tokio::process::Command::new(HARMLESS_BIN);
        super::prepare_subprocess_for_appimage(&mut cmd);
        if let Some(v) = prev {
            unsafe {
                std::env::set_var("APPIMAGE", v);
            }
        }
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn prepare_subprocess_for_appimage_with_appimage_set_is_safe() {
        let _guard = APPIMAGE_ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let prev = std::env::var_os("APPIMAGE");
        unsafe {
            std::env::set_var("APPIMAGE", "/tmp/test.AppImage");
        }
        let mut cmd = tokio::process::Command::new(HARMLESS_BIN);
        super::prepare_subprocess_for_appimage(&mut cmd);
        unsafe {
            if let Some(v) = prev {
                std::env::set_var("APPIMAGE", v);
            } else {
                std::env::remove_var("APPIMAGE");
            }
        }
    }
}
