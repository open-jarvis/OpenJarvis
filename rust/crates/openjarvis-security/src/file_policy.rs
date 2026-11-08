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
        ".git-credentials",
        "credentials",
        "shadow",
        "gshadow",
        // Plain-text password files
        "pass.txt",
        "password.txt",
        "passwords.txt",
    ])
});

static SENSITIVE_EXTENSIONS: Lazy<Vec<&'static str>> =
    Lazy::new(|| vec![".pem", ".key", ".p12", ".pfx", ".jks", ".secrets"]);

static SENSITIVE_PREFIXES: Lazy<Vec<&'static str>> = Lazy::new(|| vec![".env.", "credentials."]);

/// Resolve a path for policy checks without requiring the final target to exist.
///
/// Preserve sensitive intermediate names before canonicalizing, including
/// dangling targets that `canonicalize` cannot resolve.
fn path_for_policy(path: &Path) -> PathBuf {
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
        if matches_sensitive_name(&candidate) {
            return candidate;
        }
    }
    std::fs::canonicalize(&candidate).unwrap_or(candidate)
}

/// Return `true` if path or its resolved target matches a sensitive pattern.
pub fn is_sensitive_file(path: &Path) -> bool {
    matches_sensitive_name(path) || matches_sensitive_name(&path_for_policy(path))
}

fn matches_sensitive_name(path: &Path) -> bool {
    let name = match path.file_name().and_then(|n| n.to_str()) {
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

    fn symlink_file(target: &Path, alias: &Path) -> bool {
        #[cfg(unix)]
        let result = std::os::unix::fs::symlink(target, alias);
        #[cfg(windows)]
        let result = std::os::windows::fs::symlink_file(target, alias);
        if let Err(error) = result {
            #[cfg(windows)]
            if error.kind() == std::io::ErrorKind::PermissionDenied {
                return false;
            }
            panic!("failed to create test symlink: {error}");
        }
        true
    }

    #[test]
    fn test_plaintext_password_files() {
        for name in [
            "pass.txt",
            "password.txt",
            "passwords.txt",
            "shadow",
            "gshadow",
            "credentials",
            ".git-credentials",
        ] {
            assert!(is_sensitive_file(Path::new(&format!("/srv/app/{name}"))));
        }
        assert!(!is_sensitive_file(Path::new("/home/user/notes.txt")));
    }

    #[test]
    fn test_sensitive_symlink_name_to_ordinary_target() {
        for sensitive_name in [".env", "credentials.json", "server.pem"] {
            for target_exists in [false, true] {
                let dir = tempfile::tempdir().unwrap();
                let target = dir.path().join("notes.txt");
                if target_exists {
                    std::fs::write(&target, "SENSITIVE-SENTINEL").unwrap();
                }
                let alias = dir.path().join(sensitive_name);
                if !symlink_file(Path::new("notes.txt"), &alias) {
                    return;
                }

                assert!(
                    is_sensitive_file(&alias),
                    "{sensitive_name}, exists={target_exists}"
                );
            }
        }
    }

    #[test]
    fn test_relative_symlink_chain() {
        for target_name in [".env", "notes.txt"] {
            for target_exists in [false, true] {
                let dir = tempfile::tempdir().unwrap();
                let target = dir.path().join(target_name);
                if target_exists {
                    std::fs::write(&target, "SENTINEL").unwrap();
                }
                let intermediate = dir.path().join("intermediate.txt");
                let alias = dir.path().join("alias.txt");
                if !symlink_file(Path::new(target_name), &intermediate)
                    || !symlink_file(Path::new("intermediate.txt"), &alias)
                {
                    return;
                }

                assert_eq!(is_sensitive_file(&alias), target_name == ".env");
            }
        }
    }

    #[test]
    fn test_sensitive_intermediate_symlink_to_ordinary_target() {
        for target_exists in [false, true] {
            let dir = tempfile::tempdir().unwrap();
            let target = dir.path().join("notes.txt");
            if target_exists {
                std::fs::write(&target, "SENTINEL").unwrap();
            }
            let intermediate = dir.path().join(".env");
            let alias = dir.path().join("alias.txt");
            if !symlink_file(Path::new("notes.txt"), &intermediate)
                || !symlink_file(Path::new(".env"), &alias)
            {
                return;
            }

            assert!(is_sensitive_file(&alias));
        }
    }

    #[test]
    fn test_sensitive_symlink_loop() {
        let dir = tempfile::tempdir().unwrap();
        let alias = dir.path().join(".env");
        if !symlink_file(Path::new(".env"), &alias) {
            return;
        }

        assert!(is_sensitive_file(&alias));
    }

    #[test]
    fn test_filter_sensitive_aliases() {
        let dir = tempfile::tempdir().unwrap();
        let target = dir.path().join("notes.txt");
        std::fs::write(&target, "SENTINEL").unwrap();
        let protected_alias = dir.path().join(".env");
        let ordinary_alias = dir.path().join("alias.txt");
        let secret = dir.path().join("server.pem");
        std::fs::write(&secret, "SENTINEL").unwrap();
        if !symlink_file(Path::new("notes.txt"), &protected_alias)
            || !symlink_file(Path::new("server.pem"), &ordinary_alias)
        {
            return;
        }

        let paths = [
            protected_alias.as_path(),
            ordinary_alias.as_path(),
            target.as_path(),
        ];
        assert_eq!(filter_sensitive_paths(&paths), vec![target.as_path()]);
    }

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
