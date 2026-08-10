//! File sensitivity policy — block access to secrets, credentials, and keys.

use std::ffi::OsString;
use std::io;
use std::path::{Path, PathBuf};

static SENSITIVE_PATTERNS: &[&str] = &[
    ".env",
    ".secret",
    "id_rsa",
    "id_ed25519",
    ".htpasswd",
    ".pgpass",
    ".netrc",
];

static SENSITIVE_EXTENSIONS: &[&str] =
    &[".env", ".pem", ".key", ".p12", ".pfx", ".jks", ".secrets"];

static SENSITIVE_PREFIXES: &[&str] = &[".env.", "credentials."];

fn matches_sensitive_name(path: &Path) -> bool {
    let name = match path.file_name().and_then(|n| n.to_str()) {
        Some(name) => name.to_lowercase(),
        None => return false,
    };

    if SENSITIVE_PATTERNS.contains(&name.as_str()) {
        return true;
    }

    for ext in SENSITIVE_EXTENSIONS.iter() {
        if name.ends_with(ext) {
            return true;
        }
    }

    for prefix in SENSITIVE_PREFIXES.iter() {
        if name.starts_with(prefix) {
            return true;
        }
    }

    false
}

fn resolve_allow_missing(path: &Path) -> io::Result<PathBuf> {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()?.join(path)
    };
    let mut current = absolute.as_path();
    let mut missing_parts: Vec<OsString> = Vec::new();

    loop {
        match std::fs::symlink_metadata(current) {
            Ok(_) => {
                let mut resolved = std::fs::canonicalize(current)?;
                for part in missing_parts.iter().rev() {
                    resolved.push(part);
                }
                return Ok(resolved);
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                let part = current.file_name().ok_or_else(|| {
                    io::Error::new(
                        io::ErrorKind::NotFound,
                        "path has no existing ancestor to resolve",
                    )
                })?;
                missing_parts.push(part.to_os_string());
                current = current.parent().ok_or_else(|| {
                    io::Error::new(
                        io::ErrorKind::NotFound,
                        "path has no existing ancestor to resolve",
                    )
                })?;
            }
            Err(error) => return Err(error),
        }
    }
}

/// Return `true` if a path or its resolved target is sensitive.
///
/// Missing leaf components are permitted for prospective writes. Other
/// resolution failures fail closed because the target cannot be established.
pub fn is_sensitive_file(path: &Path) -> bool {
    if matches_sensitive_name(path) {
        return true;
    }

    match resolve_allow_missing(path) {
        Ok(resolved) => matches_sensitive_name(&resolved),
        Err(_) => true,
    }
}

/// Return only non-sensitive paths.
pub fn filter_sensitive_paths<'a>(paths: &'a [&'a Path]) -> Vec<&'a Path> {
    paths
        .iter()
        .filter(|p| !is_sensitive_file(p))
        .copied()
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sensitive_files() {
        assert!(is_sensitive_file(Path::new(".env")));
        assert!(is_sensitive_file(Path::new(".env.local")));
        assert!(is_sensitive_file(Path::new("production.env")));
        assert!(is_sensitive_file(Path::new("server.key")));
        assert!(is_sensitive_file(Path::new("cert.pem")));
        assert!(is_sensitive_file(Path::new("id_rsa")));
        assert!(is_sensitive_file(Path::new("credentials.json")));
    }

    #[test]
    fn test_safe_files() {
        assert!(!is_sensitive_file(Path::new("main.py")));
        assert!(!is_sensitive_file(Path::new("README.md")));
        assert!(!is_sensitive_file(Path::new("config.toml")));
    }

    #[test]
    fn test_sensitive_files_are_case_insensitive() {
        for name in [".ENV", "Credentials.JSON", "PRIVATE.KEY", "ID_RSA"] {
            assert!(
                is_sensitive_file(Path::new(name)),
                "{name} should be sensitive"
            );
        }
    }

    #[cfg(unix)]
    #[test]
    fn test_sensitive_target_is_blocked_through_safe_named_symlink() {
        use std::os::unix::fs::symlink;
        use std::time::{SystemTime, UNIX_EPOCH};

        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock should be after Unix epoch")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "openjarvis-file-policy-{}-{unique}",
            std::process::id()
        ));
        std::fs::create_dir(&root).expect("test directory should be created");
        let target = root.join(".env");
        let alias = root.join("notes.txt");
        std::fs::write(&target, "SECRET=value").expect("target should be written");
        symlink(&target, &alias).expect("symlink should be created");

        assert!(is_sensitive_file(&alias));

        std::fs::remove_dir_all(root).expect("test directory should be removed");
    }
}
