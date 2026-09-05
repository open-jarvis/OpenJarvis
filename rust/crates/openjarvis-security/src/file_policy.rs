//! File sensitivity policy — block access to secrets, credentials, and keys.

use once_cell::sync::Lazy;
use std::collections::HashSet;
use std::path::{Path, PathBuf};

static SENSITIVE_PATTERNS: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    HashSet::from([
        ".env",
        ".secret",
        "id_rsa",
        "id_ed25519",
        ".htpasswd",
        ".pgpass",
        ".netrc",
    ])
});

static SENSITIVE_EXTENSIONS: Lazy<Vec<&'static str>> = Lazy::new(|| {
    vec![
        ".pem", ".key", ".p12", ".pfx", ".jks", ".secrets",
    ]
});

static SENSITIVE_PREFIXES: Lazy<Vec<&'static str>> = Lazy::new(|| {
    vec![".env.", "credentials."]
});

/// Resolve a path for policy checks without requiring the final target to exist.
///
/// `canonicalize` handles normal existing paths and symlink chains. When the
/// final target does not exist (for example, a write through `notes.txt ->
/// .env`), follow the link entries manually so the sensitive target name is
/// still checked.
fn path_for_policy(path: &Path) -> PathBuf {
    if let Ok(resolved) = std::fs::canonicalize(path) {
        return resolved;
    }

    let mut candidate = path.to_path_buf();
    for _ in 0..40 {
        let Ok(target) = std::fs::read_link(&candidate) else {
            break;
        };
        candidate = if target.is_absolute() {
            target
        } else {
            candidate
                .parent()
                .unwrap_or_else(|| Path::new(""))
                .join(target)
        };
    }
    candidate
}

/// Return `true` if path or its resolved target matches a sensitive pattern.
pub fn is_sensitive_file(path: &Path) -> bool {
    let checked_path = path_for_policy(path);
    let name = match checked_path.file_name().and_then(|n| n.to_str()) {
        Some(n) => n,
        None => return false,
    };

    if SENSITIVE_PATTERNS.contains(name) {
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
    fn test_sensitive_symlink_alias() {
        let dir = tempfile::tempdir().unwrap();
        let sensitive = dir.path().join(".env");
        std::fs::write(&sensitive, "SENSITIVE-SENTINEL").unwrap();
        let alias = dir.path().join("notes.txt");

        #[cfg(unix)]
        let link_result = std::os::unix::fs::symlink(&sensitive, &alias);
        #[cfg(windows)]
        let link_result = std::os::windows::fs::symlink_file(&sensitive, &alias);
        if link_result.is_err() {
            return;
        }

        assert!(is_sensitive_file(&alias));
    }

    #[test]
    fn test_sensitive_symlink_alias_to_missing_target() {
        let dir = tempfile::tempdir().unwrap();
        let alias = dir.path().join("notes.txt");
        let sensitive = dir.path().join(".env");

        #[cfg(unix)]
        let link_result = std::os::unix::fs::symlink(&sensitive, &alias);
        #[cfg(windows)]
        let link_result = std::os::windows::fs::symlink_file(&sensitive, &alias);
        if link_result.is_err() {
            return;
        }

        assert!(is_sensitive_file(&alias));
    }
}
