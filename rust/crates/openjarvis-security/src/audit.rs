//! Audit logger — persist security events to SQLite with Merkle hash chain.

use crate::types::{ScanFinding, SecurityEvent, SecurityEventType};
use openjarvis_core::OpenJarvisError;
use rusqlite::Connection;
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};

pub struct AuditLogger {
    conn: Connection,
    _db_path: PathBuf,
}

impl AuditLogger {
    pub fn new(db_path: &Path) -> Result<Self, OpenJarvisError> {
        if let Some(parent) = db_path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(e))
            })?;
        }

        let conn = Connection::open(db_path).map_err(|e| {
            OpenJarvisError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS security_events (
                id          INTEGER PRIMARY KEY,
                timestamp   REAL,
                event_type  TEXT,
                findings_json TEXT,
                content_preview TEXT,
                action_taken TEXT,
                row_hash    TEXT DEFAULT '',
                prev_hash   TEXT DEFAULT ''
            )",
        )
        .map_err(|e| {
            OpenJarvisError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        Ok(Self {
            conn,
            _db_path: db_path.to_path_buf(),
        })
    }

    pub fn log(&self, event: &SecurityEvent) -> Result<(), OpenJarvisError> {
        let findings_json = serde_json::to_string(&event.findings).unwrap_or_default();
        let prev_hash = self.tail_hash();

        let hash_input = format!(
            "{}|{}|{:?}|{}|{}|{}",
            prev_hash,
            event.timestamp,
            event.event_type,
            findings_json,
            event.content_preview,
            event.action_taken
        );
        let row_hash = hex_sha256(&hash_input);

        self.conn
            .execute(
                "INSERT INTO security_events
                    (timestamp, event_type, findings_json, content_preview,
                     action_taken, row_hash, prev_hash)
                VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                rusqlite::params![
                    event.timestamp,
                    format!("{:?}", event.event_type),
                    findings_json,
                    event.content_preview,
                    event.action_taken,
                    row_hash,
                    prev_hash,
                ],
            )
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;

        Ok(())
    }

    pub fn tail_hash(&self) -> String {
        self.conn
            .query_row(
                "SELECT row_hash FROM security_events ORDER BY id DESC LIMIT 1",
                [],
                |row| row.get::<_, String>(0),
            )
            .unwrap_or_default()
    }

    /// Verify the Merkle hash chain integrity.
    /// Returns `(true, None)` if valid, or `(false, Some(row_id))` for first broken link.
    pub fn verify_chain(&self) -> Result<(bool, Option<i64>), OpenJarvisError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT id, timestamp, event_type, findings_json,
                        content_preview, action_taken, row_hash, prev_hash
                 FROM security_events ORDER BY id",
            )
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;

        let rows = stmt
            .query_map([], |row| {
                Ok((
                    row.get::<_, i64>(0)?,
                    row.get::<_, f64>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, Option<String>>(4)?,
                    row.get::<_, Option<String>>(5)?,
                    row.get::<_, String>(6)?,
                    row.get::<_, String>(7)?,
                ))
            })
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;

        let mut expected_prev = String::new();

        for row_result in rows {
            let (rid, ts, etype, fj, preview, action, stored_hash, stored_prev) =
                row_result.map_err(|e| {
                    OpenJarvisError::Io(std::io::Error::other(
                        e.to_string(),
                    ))
                })?;

            if stored_hash.is_empty() {
                continue;
            }

            if stored_prev != expected_prev {
                return Ok((false, Some(rid)));
            }

            let hash_input = format!(
                "{}|{}|{}|{}|{}|{}",
                stored_prev,
                ts,
                etype,
                fj,
                preview.unwrap_or_default(),
                action.unwrap_or_default()
            );
            let computed = hex_sha256(&hash_input);
            if computed != stored_hash {
                return Ok((false, Some(rid)));
            }
            expected_prev = stored_hash;
        }

        Ok((true, None))
    }

    pub fn count(&self) -> i64 {
        self.conn
            .query_row("SELECT COUNT(*) FROM security_events", [], |row| {
                row.get(0)
            })
            .unwrap_or(0)
    }

    pub fn query(
        &self,
        event_type: Option<&str>,
        since: Option<f64>,
        limit: usize,
    ) -> Result<Vec<SecurityEvent>, OpenJarvisError> {
        let mut sql = String::from(
            "SELECT timestamp, event_type, findings_json, content_preview, action_taken
             FROM security_events WHERE 1=1",
        );
        let mut params: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();

        if let Some(et) = event_type {
            sql.push_str(" AND event_type = ?");
            params.push(Box::new(et.to_string()));
        }
        if let Some(s) = since {
            sql.push_str(" AND timestamp >= ?");
            params.push(Box::new(s));
        }
        sql.push_str(" ORDER BY timestamp DESC LIMIT ?");
        params.push(Box::new(limit as i64));

        let param_refs: Vec<&dyn rusqlite::types::ToSql> =
            params.iter().map(|p| p.as_ref()).collect();

        let mut stmt = self.conn.prepare(&sql).map_err(|e| {
            OpenJarvisError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        let rows = stmt
            .query_map(param_refs.as_slice(), |row| {
                Ok((
                    row.get::<_, f64>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, Option<String>>(2)?,
                    row.get::<_, Option<String>>(3)?,
                    row.get::<_, Option<String>>(4)?,
                ))
            })
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;

        let mut events = Vec::new();
        for row_result in rows {
            let (ts, _etype, findings_json, preview, action) =
                row_result.map_err(|e| {
                    OpenJarvisError::Io(std::io::Error::other(
                        e.to_string(),
                    ))
                })?;

            let findings: Vec<ScanFinding> = findings_json
                .as_deref()
                .and_then(|s| serde_json::from_str(s).ok())
                .unwrap_or_default();

            events.push(SecurityEvent {
                event_type: SecurityEventType::SecretDetected,
                timestamp: ts,
                findings,
                content_preview: preview.unwrap_or_default(),
                action_taken: action.unwrap_or_default(),
            });
        }

        Ok(events)
    }
}

fn hex_sha256(input: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(input.as_bytes());
    format!("{:x}", hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::ThreatLevel;

    #[test]
    fn test_audit_log_and_verify() {
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("test_audit.db");
        let logger = AuditLogger::new(&db_path).unwrap();

        let event = SecurityEvent {
            event_type: SecurityEventType::SecretDetected,
            timestamp: 1000.0,
            findings: vec![ScanFinding {
                pattern_name: "openai_key".into(),
                matched_text: "sk-test123".into(),
                threat_level: ThreatLevel::Critical,
                start: 0,
                end: 10,
                description: "OpenAI API key".into(),
            }],
            content_preview: "test".into(),
            action_taken: "warn".into(),
        };
        logger.log(&event).unwrap();

        assert_eq!(logger.count(), 1);
        let (valid, _) = logger.verify_chain().unwrap();
        assert!(valid);
    }

    #[test]
    fn test_audit_chain_integrity() {
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("test_chain.db");
        let logger = AuditLogger::new(&db_path).unwrap();

        for i in 0..5 {
            let event = SecurityEvent {
                event_type: SecurityEventType::SecretDetected,
                timestamp: 1000.0 + i as f64,
                findings: vec![],
                content_preview: format!("event {i}"),
                action_taken: "warn".into(),
            };
            logger.log(&event).unwrap();
        }

        assert_eq!(logger.count(), 5);
        let (valid, _) = logger.verify_chain().unwrap();
        assert!(valid);
    }
}
