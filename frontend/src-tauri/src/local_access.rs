use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;
use std::{fs::OpenOptions, io::Write};
use tokio::process::Command;
use toml_edit::{value, Array, DocumentMut};

const MAX_FILE_BYTES: u64 = 1_048_576;
const MAX_COMMAND_OUTPUT_BYTES: usize = 20_000;
const SAFE_DOCUMENT_EXTENSIONS: &[&str] = &["md", "txt", "csv", "json"];
const SAFE_COMMANDS: &[&str] = &[
    "git status --short",
    "git diff --stat",
    "git diff --name-only",
    "git log --oneline -10",
    "git branch --show-current",
];

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct LocalAccessSettings {
    pub enabled: bool,
    pub allowed_dirs: Vec<String>,
    pub allowed_apps: Vec<String>,
    pub allowed_commands: Vec<String>,
}

impl Default for LocalAccessSettings {
    fn default() -> Self {
        Self {
            enabled: false,
            allowed_dirs: Vec::new(),
            allowed_apps: Vec::new(),
            allowed_commands: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LocalFileEntry {
    pub name: String,
    pub path: String,
    pub is_dir: bool,
    pub size_bytes: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CommandResult {
    pub stdout: String,
    pub stderr: String,
    pub success: bool,
    pub return_code: Option<i32>,
}

fn config_path() -> PathBuf {
    if let Some(path) = std::env::var_os("OPENJARVIS_CONFIG") {
        return resolve_config_path(PathBuf::from(path));
    }
    if let Some(home) = std::env::var_os("OPENJARVIS_HOME") {
        return resolve_config_path(PathBuf::from(home)).join("config.toml");
    }
    if let Some(data_home) = std::env::var_os("XDG_DATA_HOME") {
        return resolve_config_path(PathBuf::from(data_home))
            .join("openjarvis")
            .join("config.toml");
    }
    PathBuf::from(super::home_dir()).join(".openjarvis").join("config.toml")
}

fn resolve_config_path(path: PathBuf) -> PathBuf {
    let value = path.to_string_lossy().into_owned();
    let expanded = if value == "~" {
        PathBuf::from(super::home_dir())
    } else if let Some(relative) = value
        .strip_prefix("~/")
        .or_else(|| value.strip_prefix("~\\"))
    {
        PathBuf::from(super::home_dir()).join(relative)
    } else {
        path
    };
    if expanded.is_absolute() {
        expanded
    } else {
        std::env::current_dir()
            .unwrap_or_default()
            .join(expanded)
    }
}

fn read_settings(path: &Path) -> Result<LocalAccessSettings, String> {
    let text = match std::fs::read_to_string(path) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok(LocalAccessSettings::default());
        }
        Err(error) => return Err(format!("Cannot read OpenJarvis config: {error}")),
    };
    let document = text
        .parse::<DocumentMut>()
        .map_err(|error| format!("OpenJarvis config is invalid TOML: {error}"))?;
    let Some(table) = document.get("local_access").and_then(|item| item.as_table_like()) else {
        return Ok(LocalAccessSettings::default());
    };
    let enabled = table
        .get("enabled")
        .and_then(|item| item.as_bool())
        .unwrap_or(false);
    let read_list = |key: &str| -> Result<Vec<String>, String> {
        let Some(item) = table.get(key) else {
            return Ok(Vec::new());
        };
        let Some(array) = item.as_array() else {
            return Err(format!("local_access.{key} must be an array of strings"));
        };
        array
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .map(str::to_owned)
                    .ok_or_else(|| format!("local_access.{key} must contain only strings"))
            })
            .collect()
    };
    Ok(LocalAccessSettings {
        enabled,
        allowed_dirs: read_list("allowed_dirs")?,
        allowed_apps: read_list("allowed_apps")?,
        allowed_commands: read_list("allowed_commands")?,
    })
}

fn write_settings(path: &Path, settings: &LocalAccessSettings) -> Result<(), String> {
    validate_settings(settings)?;
    let text = match std::fs::read_to_string(path) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => String::new(),
        Err(error) => return Err(format!("Cannot read OpenJarvis config: {error}")),
    };
    let mut document = if text.is_empty() {
        DocumentMut::new()
    } else {
        text.parse::<DocumentMut>()
            .map_err(|error| format!("OpenJarvis config is invalid TOML: {error}"))?
    };
    if !document.contains_key("local_access") {
        document["local_access"] = toml_edit::table();
    }
    document["local_access"]["enabled"] = value(settings.enabled);
    document["local_access"]["allowed_dirs"] = value(to_array(&settings.allowed_dirs));
    document["local_access"]["allowed_apps"] = value(to_array(&settings.allowed_apps));
    document["local_access"]["allowed_commands"] = value(to_array(&settings.allowed_commands));
    let parent = path
        .parent()
        .ok_or_else(|| "OpenJarvis config has no parent directory".to_string())?;
    std::fs::create_dir_all(parent)
        .map_err(|error| format!("Cannot create config directory: {error}"))?;
    std::fs::write(path, document.to_string())
        .map_err(|error| format!("Cannot save OpenJarvis config: {error}"))
}

fn to_array(values: &[String]) -> Array {
    let mut array = Array::new();
    for item in values {
        array.push(item.as_str());
    }
    array
}

fn validate_settings(settings: &LocalAccessSettings) -> Result<(), String> {
    if settings.enabled && settings.allowed_dirs.is_empty() {
        return Err("Add at least one allowed folder before enabling local access.".into());
    }
    let mut resolved_dirs = Vec::new();
    for directory in &settings.allowed_dirs {
        if directory.trim().is_empty() {
            return Err("Allowed folders cannot be empty.".into());
        }
        let path = PathBuf::from(directory)
            .canonicalize()
            .map_err(|error| format!("Allowed folder is unavailable: {directory}: {error}"))?;
        if !path.is_dir() {
            return Err(format!("Allowed path is not a folder: {directory}"));
        }
        if !resolved_dirs.contains(&path) {
            resolved_dirs.push(path);
        }
    }
    for app in &settings.allowed_apps {
        validate_app(app)?;
    }
    for command in &settings.allowed_commands {
        validate_command(command)?;
    }
    Ok(())
}

fn validate_app(app: &str) -> Result<(), String> {
    if app.trim().is_empty() {
        return Err("Allowed app names cannot be empty.".into());
    }
    let name = app
        .rsplit(|character| character == '/' || character == '\\')
        .next()
        .unwrap_or(app)
        .to_ascii_lowercase();
    let stem = name.rsplit_once('.').map(|(stem, _)| stem).unwrap_or(&name);
    if matches!(
        stem,
        "cmd"
            | "powershell"
            | "pwsh"
            | "bash"
            | "sh"
            | "zsh"
            | "fish"
            | "terminal"
            | "iterm"
            | "iterm2"
            | "windows terminal"
            | "wt"
            | "xterm"
            | "x-terminal-emulator"
            | "gnome-terminal"
            | "konsole"
            | "kitty"
            | "alacritty"
            | "wezterm"
            | "terminator"
            | "python"
            | "python3"
            | "node"
            | "wscript"
            | "cscript"
    ) || matches!(
        Path::new(app)
            .extension()
            .and_then(|extension| extension.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase()
            .as_str(),
        "bat" | "cmd" | "ps1" | "sh" | "command" | "py"
    ) {
        return Err(format!(
            "Shells, script interpreters, and command scripts cannot be allowlisted: {app}"
        ));
    }
    Ok(())
}

fn allowed_roots(settings: &LocalAccessSettings) -> Result<Vec<PathBuf>, String> {
    if !settings.enabled {
        return Err("Local computer access is disabled. Enable it in Local Access settings.".into());
    }
    if settings.allowed_dirs.is_empty() {
        return Err("No allowed folders are configured.".into());
    }
    settings
        .allowed_dirs
        .iter()
        .map(|directory| {
            let path = PathBuf::from(directory)
                .canonicalize()
                .map_err(|error| format!("Allowed folder is unavailable: {directory}: {error}"))?;
            if !path.is_dir() {
                return Err(format!("Allowed path is not a folder: {directory}"));
            }
            Ok(path)
        })
        .collect()
}

fn resolve_allowed_path(path: &str, roots: &[PathBuf]) -> Result<PathBuf, String> {
    let requested = PathBuf::from(path);
    if !requested.is_absolute() {
        return Err("Use an absolute path selected from an allowed folder.".into());
    }
    let resolved = requested
        .canonicalize()
        .map_err(|error| format!("Path is unavailable: {error}"))?;
    if !roots.iter().any(|root| resolved.starts_with(root)) {
        return Err("Access denied: path is outside configured allowed folders.".into());
    }
    Ok(resolved)
}

fn resolve_new_file(path: &str, roots: &[PathBuf]) -> Result<PathBuf, String> {
    let requested = PathBuf::from(path);
    if !requested.is_absolute() || requested.file_name().is_none() {
        return Err("Choose a filename inside an allowed folder.".into());
    }
    let parent = requested
        .parent()
        .ok_or_else(|| "The selected file has no parent folder.".to_string())?
        .canonicalize()
        .map_err(|error| format!("Parent folder is unavailable: {error}"))?;
    if !roots.iter().any(|root| parent.starts_with(root)) {
        return Err("Access denied: path is outside configured allowed folders.".into());
    }
    let name = requested
        .file_name()
        .ok_or_else(|| "Choose a filename.".to_string())?;
    Ok(parent.join(name))
}

fn is_sensitive(path: &Path) -> bool {
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    name == ".env"
        || name.starts_with(".env.")
        || name.contains("credential")
        || name.contains("password")
        || name.contains("private_key")
        || name.contains("secret")
        || name.contains("token")
        || name.starts_with("id_rsa")
        || name.starts_with("id_ed25519")
        || name.ends_with(".pem")
        || name.ends_with(".key")
}

fn is_document(path: &Path) -> bool {
    path.extension()
        .and_then(|extension| extension.to_str())
        .map(|extension| {
            SAFE_DOCUMENT_EXTENSIONS
                .iter()
                .any(|safe| extension.eq_ignore_ascii_case(safe))
        })
        .unwrap_or(false)
}

fn validate_command(command: &str) -> Result<(), String> {
    if !SAFE_COMMANDS.iter().any(|safe| *safe == command) {
        return Err(format!(
            "Command is not in the built-in safe command set: {command}"
        ));
    }
    Ok(())
}

fn truncate_output(value: String) -> String {
    if value.len() <= MAX_COMMAND_OUTPUT_BYTES {
        return value;
    }
    let mut end = MAX_COMMAND_OUTPUT_BYTES;
    while !value.is_char_boundary(end) {
        end -= 1;
    }
    format!("{}… (output truncated)", &value[..end])
}

#[tauri::command]
pub async fn get_local_access_settings() -> Result<LocalAccessSettings, String> {
    read_settings(&config_path())
}

#[tauri::command]
pub async fn set_local_access_settings(
    settings: LocalAccessSettings,
) -> Result<LocalAccessSettings, String> {
    let path = config_path();
    write_settings(&path, &settings)?;
    read_settings(&path)
}

#[tauri::command]
pub async fn list_local_files(path: String) -> Result<Vec<LocalFileEntry>, String> {
    let settings = read_settings(&config_path())?;
    let roots = allowed_roots(&settings)?;
    let directory = resolve_allowed_path(&path, &roots)?;
    if !directory.is_dir() {
        return Err("Select a folder to browse.".into());
    }
    let entries = std::fs::read_dir(&directory)
        .map_err(|error| format!("Cannot browse folder: {error}"))?;
    let mut files = Vec::new();
    for entry in entries.take(1000) {
        let entry = entry.map_err(|error| format!("Cannot read folder entry: {error}"))?;
        let file_path = entry.path();
        let metadata = std::fs::symlink_metadata(&file_path)
            .map_err(|error| format!("Cannot inspect folder entry: {error}"))?;
        if metadata.file_type().is_symlink() || is_sensitive(&file_path) {
            continue;
        }
        let is_dir = metadata.is_dir();
        if !is_dir && !is_document(&file_path) {
            continue;
        }
        files.push(LocalFileEntry {
            name: entry.file_name().to_string_lossy().into_owned(),
            path: file_path.to_string_lossy().into_owned(),
            is_dir,
            size_bytes: if is_dir { 0 } else { metadata.len() },
        });
    }
    files.sort_by(|left, right| {
        right
            .is_dir
            .cmp(&left.is_dir)
            .then_with(|| left.name.to_lowercase().cmp(&right.name.to_lowercase()))
    });
    Ok(files)
}

#[tauri::command]
pub async fn read_local_file(path: String) -> Result<String, String> {
    let settings = read_settings(&config_path())?;
    let roots = allowed_roots(&settings)?;
    let file = resolve_allowed_path(&path, &roots)?;
    if is_sensitive(&file) {
        return Err("Access denied: sensitive filenames cannot be opened.".into());
    }
    if !file.is_file() || !is_document(&file) {
        return Err("Only Markdown, text, CSV, and JSON documents can be opened.".into());
    }
    let metadata = std::fs::metadata(&file)
        .map_err(|error| format!("Cannot inspect document: {error}"))?;
    if metadata.len() > MAX_FILE_BYTES {
        return Err(format!("Document exceeds the 1 MiB limit ({} bytes).", metadata.len()));
    }
    std::fs::read_to_string(file).map_err(|error| format!("Cannot read document: {error}"))
}

#[tauri::command]
pub async fn write_local_file(
    path: String,
    content: String,
    confirm_overwrite: bool,
) -> Result<(), String> {
    let settings = read_settings(&config_path())?;
    let roots = allowed_roots(&settings)?;
    let file = resolve_new_file(&path, &roots)?;
    if is_sensitive(&file) {
        return Err("Access denied: sensitive filenames cannot be edited.".into());
    }
    if !is_document(&file) {
        return Err("Only Markdown, text, CSV, and JSON documents can be created or edited.".into());
    }
    if content.len() > MAX_FILE_BYTES as usize {
        return Err("Document exceeds the 1 MiB write limit.".into());
    }
    let exists = match std::fs::symlink_metadata(&file) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            return Err("Editing symbolic links is not allowed.".into());
        }
        Ok(metadata) if metadata.is_file() => true,
        Ok(_) => return Err("The selected path is not a regular file.".into()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
        Err(error) => return Err(format!("Cannot inspect destination: {error}")),
    };
    if exists && !confirm_overwrite {
        return Err("Overwrite confirmation is required for an existing document.".into());
    }
    if !exists {
        let mut destination = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&file)
            .map_err(|error| format!("Cannot create document: {error}"))?;
        destination
            .write_all(content.as_bytes())
            .map_err(|error| format!("Cannot write document: {error}"))?;
    } else {
        std::fs::write(&file, content)
            .map_err(|error| format!("Cannot update document: {error}"))?;
    }
    Ok(())
}

#[tauri::command]
pub async fn launch_allowed_app(app_name: String, confirmed: bool) -> Result<(), String> {
    let settings = read_settings(&config_path())?;
    let _ = allowed_roots(&settings)?;
    validate_app(&app_name)?;
    if !settings.allowed_apps.iter().any(|app| app == &app_name) {
        return Err("Access denied: this application is not in the configured allowlist.".into());
    }
    if !confirmed {
        return Err("Application launch requires explicit confirmation.".into());
    }
    #[cfg(target_os = "macos")]
    let result = Command::new("open").arg("-a").arg(&app_name).spawn();
    #[cfg(not(target_os = "macos"))]
    let result = Command::new(&app_name).spawn();
    result
        .map(|_| ())
        .map_err(|error| format!("Cannot launch {app_name}: {error}"))
}

#[tauri::command]
pub async fn run_allowed_command(
    command: String,
    confirmed: bool,
) -> Result<CommandResult, String> {
    let settings = read_settings(&config_path())?;
    let roots = allowed_roots(&settings)?;
    validate_command(&command)?;
    if !settings.allowed_commands.iter().any(|allowed| allowed == &command) {
        return Err("Access denied: this command is not in the configured allowlist.".into());
    }
    if !confirmed {
        return Err("Command execution requires explicit confirmation.".into());
    }
    let mut child = Command::new("git");
    child
        .args(command.split_whitespace().skip(1))
        .current_dir(&roots[0])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    let output = tokio::time::timeout(Duration::from_secs(30), child.output())
        .await
        .map_err(|_| "Command timed out after 30 seconds.".to_string())?
        .map_err(|error| format!("Cannot run command: {error}"))?;
    Ok(CommandResult {
        stdout: truncate_output(String::from_utf8_lossy(&output.stdout).into_owned()),
        stderr: truncate_output(String::from_utf8_lossy(&output.stderr).into_owned()),
        success: output.status.success(),
        return_code: output.status.code(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn access_is_disabled_and_empty_by_default() {
        assert_eq!(LocalAccessSettings::default(), LocalAccessSettings {
            enabled: false,
            allowed_dirs: vec![],
            allowed_apps: vec![],
            allowed_commands: vec![],
        });
    }

    #[test]
    fn only_fixed_safe_commands_are_accepted() {
        assert!(validate_command("git status --short").is_ok());
        assert!(validate_command("git status; whoami").is_err());
        assert!(validate_command("powershell -Command Get-ChildItem").is_err());
        assert!(validate_command("git reset --hard").is_err());
    }

    #[test]
    fn shell_and_script_apps_cannot_be_allowlisted() {
        for app in [
            "cmd.exe",
            "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
            "/usr/bin/gnome-terminal",
            "run.ps1",
            "Terminal.app",
        ] {
            assert!(validate_app(app).is_err(), "{app} should be rejected");
        }
        assert!(validate_app("notepad.exe").is_ok());
    }

    #[test]
    fn sensitive_files_and_non_documents_are_not_supported() {
        assert!(is_sensitive(Path::new("credentials.json")));
        assert!(is_sensitive(Path::new(".env.local")));
        assert!(is_sensitive(Path::new("passwords.csv")));
        assert!(is_sensitive(Path::new("id_rsa.backup.txt")));
        assert!(!is_document(Path::new("photo.png")));
        assert!(is_document(Path::new("notes.md")));
    }

    #[test]
    fn configured_paths_cannot_escape_the_allowed_folder() {
        let root = std::env::temp_dir().join(format!(
            "openjarvis-local-access-{}",
            std::process::id()
        ));
        let allowed = root.join("allowed");
        let outside = root.join("outside");
        std::fs::create_dir_all(&allowed).unwrap();
        std::fs::create_dir_all(&outside).unwrap();
        let file = outside.join("note.md");
        std::fs::write(&file, "private").unwrap();

        assert!(resolve_allowed_path(file.to_str().unwrap(), &[allowed.clone()]).is_err());
        assert!(resolve_new_file(
            allowed.join("..").join("outside").join("new.md").to_str().unwrap(),
            &[root.join("allowed").canonicalize().unwrap()],
        )
        .is_err());

        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn settings_round_trip_preserves_other_config_sections() {
        let root = std::env::temp_dir().join(format!(
            "openjarvis-local-access-config-{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let config = root.join("config.toml");
        std::fs::write(&config, "[agent]\ndefault_agent = \"simple\"\n").unwrap();
        let settings = LocalAccessSettings {
            enabled: true,
            allowed_dirs: vec![root.to_string_lossy().into_owned()],
            allowed_apps: vec!["notepad".into()],
            allowed_commands: vec!["git status --short".into()],
        };

        write_settings(&config, &settings).unwrap();
        assert_eq!(read_settings(&config).unwrap(), settings);
        let saved = std::fs::read_to_string(&config).unwrap();
        assert!(saved.contains("default_agent = \"simple\""));

        std::fs::remove_dir_all(root).unwrap();
    }
}
