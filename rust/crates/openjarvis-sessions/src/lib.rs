//! OpenJarvis Sessions — cross-channel persistent session management.
//!
//! Port of `src/openjarvis/sessions/` from Python.
//! Provides SQLite-backed session storage with identity consolidation,
//! message decay, and cross-channel user linking.

use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};

fn now_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionIdentity {
    pub user_id: String,
    pub display_name: String,
    pub channel_ids: HashMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionMessage {
    pub role: String,
    pub content: String,
    pub channel: String,
    pub timestamp: f64,
    pub metadata: HashMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Session {
    pub session_id: String,
    pub identity: SessionIdentity,
    pub messages: Vec<SessionMessage>,
    pub created_at: f64,
    pub last_activity: f64,
    pub metadata: HashMap<String, serde_json::Value>,
}

// ---------------------------------------------------------------------------
// SessionStore
// ---------------------------------------------------------------------------

pub struct SessionStore {
    conn: Connection,
    max_age_hours: f64,
    consolidation_threshold: usize,
}

impl SessionStore {
    pub fn new(db_path: &str, max_age_hours: f64, consolidation_threshold: usize) -> Self {
        let conn = if db_path == ":memory:" {
            Connection::open_in_memory().expect("failed to open in-memory SQLite")
        } else {
            if let Some(parent) = std::path::Path::new(db_path).parent() {
                let _ = std::fs::create_dir_all(parent);
            }
            Connection::open(db_path).expect("failed to open SQLite database")
        };

        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS sessions (
                session_id   TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                display_name TEXT DEFAULT '',
                created_at   REAL NOT NULL,
                last_activity REAL NOT NULL,
                metadata_json TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS session_messages (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role      TEXT NOT NULL,
                content   TEXT NOT NULL,
                channel   TEXT DEFAULT '',
                timestamp REAL NOT NULL,
                metadata_json TEXT DEFAULT '{}',
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE TABLE IF NOT EXISTS channel_links (
                session_id      TEXT NOT NULL,
                channel         TEXT NOT NULL,
                channel_user_id TEXT NOT NULL,
                PRIMARY KEY (channel, channel_user_id),
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON session_messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_activity
                ON sessions(last_activity);",
        )
        .expect("failed to initialise session tables");

        Self {
            conn,
            max_age_hours,
            consolidation_threshold,
        }
    }

    /// Look up an existing session for the (channel, channel_user_id) pair,
    /// or create a fresh one.
    pub fn get_or_create(
        &self,
        user_id: &str,
        channel: &str,
        channel_user_id: &str,
        display_name: &str,
    ) -> Session {
        let existing: Option<String> = self
            .conn
            .query_row(
                "SELECT session_id FROM channel_links
                 WHERE channel = ?1 AND channel_user_id = ?2",
                params![channel, channel_user_id],
                |row| row.get(0),
            )
            .ok();

        if let Some(sid) = existing {
            return self.load_session(&sid);
        }

        let session_id = uuid::Uuid::new_v4().to_string();
        let now = now_secs();

        self.conn
            .execute(
                "INSERT INTO sessions (session_id, user_id, display_name, created_at, last_activity)
                 VALUES (?1, ?2, ?3, ?4, ?5)",
                params![session_id, user_id, display_name, now, now],
            )
            .expect("insert session");

        self.conn
            .execute(
                "INSERT OR REPLACE INTO channel_links (session_id, channel, channel_user_id)
                 VALUES (?1, ?2, ?3)",
                params![session_id, channel, channel_user_id],
            )
            .expect("insert channel link");

        self.load_session(&session_id)
    }

    /// Persist a single message into a session.
    pub fn save_message(
        &self,
        session_id: &str,
        role: &str,
        content: &str,
        channel: &str,
    ) -> Result<(), String> {
        let now = now_secs();

        self.conn
            .execute(
                "INSERT INTO session_messages (session_id, role, content, channel, timestamp)
                 VALUES (?1, ?2, ?3, ?4, ?5)",
                params![session_id, role, content, channel, now],
            )
            .map_err(|e| e.to_string())?;

        self.conn
            .execute(
                "UPDATE sessions SET last_activity = ?1 WHERE session_id = ?2",
                params![now, session_id],
            )
            .map_err(|e| e.to_string())?;

        Ok(())
    }

    /// Collapse older messages into a single summary placeholder when
    /// the message count exceeds `consolidation_threshold`.
    pub fn consolidate(&self, session_id: &str) {
        let count: i64 = self
            .conn
            .query_row(
                "SELECT COUNT(*) FROM session_messages WHERE session_id = ?1",
                params![session_id],
                |row| row.get(0),
            )
            .unwrap_or(0);

        if (count as usize) <= self.consolidation_threshold {
            return;
        }

        let keep = self.consolidation_threshold / 2;
        let remove_up_to = count as usize - keep;

        let _ = self.conn.execute(
            "DELETE FROM session_messages
             WHERE session_id = ?1
               AND id IN (
                   SELECT id FROM session_messages
                   WHERE session_id = ?1
                   ORDER BY timestamp ASC
                   LIMIT ?2
               )",
            params![session_id, remove_up_to as i64],
        );

        let summary = format!("[consolidated {} earlier messages]", remove_up_to);
        let now = now_secs();
        let _ = self.conn.execute(
            "INSERT INTO session_messages (session_id, role, content, channel, timestamp)
             VALUES (?1, 'system', ?2, '', ?3)",
            params![session_id, summary, now],
        );
    }

    /// Remove sessions (and their messages) older than `max_age_hours`.
    /// Returns the number of decayed sessions.
    pub fn decay(&self, max_age_hours: Option<f64>) -> usize {
        let hours = max_age_hours.unwrap_or(self.max_age_hours);
        let cutoff = now_secs() - hours * 3600.0;

        let expired: Vec<String> = {
            let mut stmt = self
                .conn
                .prepare(
                    "SELECT session_id FROM sessions WHERE last_activity < ?1",
                )
                .expect("prepare decay query");

            stmt.query_map(params![cutoff], |row| row.get::<_, String>(0))
                .expect("query decay")
                .filter_map(|r| r.ok())
                .collect()
        };

        let n = expired.len();
        for sid in &expired {
            let _ = self.conn.execute(
                "DELETE FROM session_messages WHERE session_id = ?1",
                params![sid],
            );
            let _ = self.conn.execute(
                "DELETE FROM channel_links WHERE session_id = ?1",
                params![sid],
            );
            let _ = self.conn.execute(
                "DELETE FROM sessions WHERE session_id = ?1",
                params![sid],
            );
        }
        n
    }

    /// Associate an additional channel identity with an existing session.
    pub fn link_channel(&self, session_id: &str, channel: &str, channel_user_id: &str) {
        let _ = self.conn.execute(
            "INSERT OR REPLACE INTO channel_links (session_id, channel, channel_user_id)
             VALUES (?1, ?2, ?3)",
            params![session_id, channel, channel_user_id],
        );
    }

    /// List sessions, optionally filtering to only those with recent activity.
    pub fn list_sessions(&self, active_only: bool, limit: usize) -> Vec<Session> {
        let query = if active_only {
            let cutoff = now_secs() - self.max_age_hours * 3600.0;
            format!(
                "SELECT session_id FROM sessions
                 WHERE last_activity >= {}
                 ORDER BY last_activity DESC LIMIT {}",
                cutoff, limit
            )
        } else {
            format!(
                "SELECT session_id FROM sessions
                 ORDER BY last_activity DESC LIMIT {}",
                limit
            )
        };

        let mut stmt = self.conn.prepare(&query).expect("prepare list query");
        let ids: Vec<String> = stmt
            .query_map([], |row| row.get::<_, String>(0))
            .expect("query list")
            .filter_map(|r| r.ok())
            .collect();

        ids.iter().map(|sid| self.load_session(sid)).collect()
    }

    /// Close the database connection (consumes self).
    pub fn close(self) {
        let _ = self.conn.close();
    }

    // ------------------------------------------------------------------
    // Internal helpers
    // ------------------------------------------------------------------

    fn load_session(&self, session_id: &str) -> Session {
        let (user_id, display_name, created_at, last_activity, metadata_json): (
            String,
            String,
            f64,
            f64,
            String,
        ) = self
            .conn
            .query_row(
                "SELECT user_id, display_name, created_at, last_activity, metadata_json
                 FROM sessions WHERE session_id = ?1",
                params![session_id],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                    ))
                },
            )
            .expect("session row must exist");

        let channel_ids = self.load_channel_ids(session_id);

        let messages = self.load_messages(session_id);

        let metadata: HashMap<String, serde_json::Value> =
            serde_json::from_str(&metadata_json).unwrap_or_default();

        Session {
            session_id: session_id.to_string(),
            identity: SessionIdentity {
                user_id,
                display_name,
                channel_ids,
            },
            messages,
            created_at,
            last_activity,
            metadata,
        }
    }

    fn load_channel_ids(&self, session_id: &str) -> HashMap<String, String> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT channel, channel_user_id FROM channel_links WHERE session_id = ?1",
            )
            .expect("prepare channel query");

        stmt.query_map(params![session_id], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })
        .expect("query channels")
        .filter_map(|r| r.ok())
        .collect()
    }

    fn load_messages(&self, session_id: &str) -> Vec<SessionMessage> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT role, content, channel, timestamp, metadata_json
                 FROM session_messages
                 WHERE session_id = ?1
                 ORDER BY timestamp ASC",
            )
            .expect("prepare message query");

        stmt.query_map(params![session_id], |row| {
            let md_str: String = row.get(4)?;
            let metadata: HashMap<String, serde_json::Value> =
                serde_json::from_str(&md_str).unwrap_or_default();
            Ok(SessionMessage {
                role: row.get(0)?,
                content: row.get(1)?,
                channel: row.get(2)?,
                timestamp: row.get(3)?,
                metadata,
            })
        })
        .expect("query messages")
        .filter_map(|r| r.ok())
        .collect()
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn mem_store() -> SessionStore {
        SessionStore::new(":memory:", 24.0, 10)
    }

    #[test]
    fn test_get_or_create_returns_same_session() {
        let store = mem_store();
        let s1 = store.get_or_create("u1", "slack", "U001", "Alice");
        let s2 = store.get_or_create("u1", "slack", "U001", "Alice");
        assert_eq!(s1.session_id, s2.session_id);
        assert_eq!(s1.identity.display_name, "Alice");
    }

    #[test]
    fn test_save_and_load_messages() {
        let store = mem_store();
        let s = store.get_or_create("u2", "whatsapp", "W002", "Bob");
        store
            .save_message(&s.session_id, "user", "hello", "whatsapp")
            .unwrap();
        store
            .save_message(&s.session_id, "assistant", "hi!", "whatsapp")
            .unwrap();

        let reloaded = store.get_or_create("u2", "whatsapp", "W002", "Bob");
        assert_eq!(reloaded.messages.len(), 2);
        assert_eq!(reloaded.messages[0].role, "user");
        assert_eq!(reloaded.messages[1].content, "hi!");
    }

    #[test]
    fn test_link_channel_and_identity() {
        let store = mem_store();
        let s = store.get_or_create("u3", "slack", "S003", "Carol");
        store.link_channel(&s.session_id, "discord", "D003");

        let reloaded = store.load_session(&s.session_id);
        assert_eq!(reloaded.identity.channel_ids.len(), 2);
        assert_eq!(
            reloaded.identity.channel_ids.get("slack").unwrap(),
            "S003"
        );
        assert_eq!(
            reloaded.identity.channel_ids.get("discord").unwrap(),
            "D003"
        );
    }

    #[test]
    fn test_consolidate_trims_old_messages() {
        let store = SessionStore::new(":memory:", 24.0, 6);
        let s = store.get_or_create("u4", "irc", "I004", "Dave");

        for i in 0..10 {
            store
                .save_message(&s.session_id, "user", &format!("msg {}", i), "irc")
                .unwrap();
        }

        let before = store.load_session(&s.session_id);
        assert_eq!(before.messages.len(), 10);

        store.consolidate(&s.session_id);

        let after = store.load_session(&s.session_id);
        assert!(after.messages.len() < 10);
        assert!(after.messages.iter().any(|m| m.content.contains("consolidated")));
    }

    #[test]
    fn test_decay_removes_old_sessions() {
        let store = mem_store();
        let s = store.get_or_create("u5", "slack", "S005", "Eve");
        store
            .save_message(&s.session_id, "user", "old", "slack")
            .unwrap();

        // Large max_age — nothing should be decayed
        let removed = store.decay(Some(9999.0));
        assert_eq!(removed, 0);
        assert_eq!(store.list_sessions(false, 100).len(), 1);

        // Back-date the session's last_activity so decay picks it up
        store
            .conn
            .execute(
                "UPDATE sessions SET last_activity = 0.0 WHERE session_id = ?1",
                params![s.session_id],
            )
            .unwrap();

        let removed = store.decay(Some(0.001));
        assert_eq!(removed, 1);
        assert!(store.list_sessions(false, 100).is_empty());
    }

    #[test]
    fn test_list_sessions() {
        let store = mem_store();
        store.get_or_create("u6", "slack", "S006", "Frank");
        store.get_or_create("u7", "slack", "S007", "Grace");

        let all = store.list_sessions(false, 100);
        assert_eq!(all.len(), 2);

        let limited = store.list_sessions(false, 1);
        assert_eq!(limited.len(), 1);
    }
}
