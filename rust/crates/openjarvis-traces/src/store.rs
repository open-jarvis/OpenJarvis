//! TraceStore — SQLite persistence for traces.

use openjarvis_core::{OpenJarvisError, Trace};
use parking_lot::Mutex;
use rusqlite::Connection;
use std::path::{Path, PathBuf};

pub struct TraceStore {
    conn: Mutex<Connection>,
    _db_path: PathBuf,
}

impl TraceStore {
    pub fn new(db_path: &Path) -> Result<Self, OpenJarvisError> {
        if let Some(parent) = db_path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(e))
            })?;
        }

        let conn = Connection::open(db_path).map_err(|e| {
            OpenJarvisError::Io(std::io::Error::other(e.to_string()))
        })?;

        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS traces (
                trace_id TEXT PRIMARY KEY,
                query TEXT DEFAULT '',
                agent TEXT DEFAULT '',
                model TEXT DEFAULT '',
                engine TEXT DEFAULT '',
                result TEXT DEFAULT '',
                outcome TEXT,
                feedback REAL,
                started_at REAL DEFAULT 0,
                ended_at REAL DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                total_latency_seconds REAL DEFAULT 0,
                steps_json TEXT DEFAULT '[]',
                metadata_json TEXT DEFAULT '{}'
            )",
        )
        .map_err(|e| {
            OpenJarvisError::Io(std::io::Error::other(e.to_string()))
        })?;

        Ok(Self {
            conn: Mutex::new(conn),
            _db_path: db_path.to_path_buf(),
        })
    }

    pub fn in_memory() -> Result<Self, OpenJarvisError> {
        Self::new(Path::new(":memory:"))
    }

    pub fn save(&self, trace: &Trace) -> Result<(), OpenJarvisError> {
        let steps_json = serde_json::to_string(&trace.steps).unwrap_or_default();
        let metadata_json = serde_json::to_string(&trace.metadata).unwrap_or_default();

        let conn = self.conn.lock();
        conn.execute(
            "INSERT OR REPLACE INTO traces
                (trace_id, query, agent, model, engine, result, outcome, feedback,
                 started_at, ended_at, total_tokens, total_latency_seconds,
                 steps_json, metadata_json)
            VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)",
            rusqlite::params![
                trace.trace_id,
                trace.query,
                trace.agent,
                trace.model,
                trace.engine,
                trace.result,
                trace.outcome,
                trace.feedback,
                trace.started_at,
                trace.ended_at,
                trace.total_tokens,
                trace.total_latency_seconds,
                steps_json,
                metadata_json,
            ],
        )
        .map_err(|e| {
            OpenJarvisError::Io(std::io::Error::other(e.to_string()))
        })?;

        Ok(())
    }

    pub fn get(&self, trace_id: &str) -> Result<Option<Trace>, OpenJarvisError> {
        let conn = self.conn.lock();
        let mut stmt = conn
            .prepare(
                "SELECT trace_id, query, agent, model, engine, result, outcome, feedback,
                        started_at, ended_at, total_tokens, total_latency_seconds,
                        steps_json, metadata_json
                 FROM traces WHERE trace_id = ?1",
            )
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;

        let result = stmt
            .query_row(rusqlite::params![trace_id], |row| {
                Ok(Trace {
                    trace_id: row.get(0)?,
                    query: row.get(1)?,
                    agent: row.get(2)?,
                    model: row.get(3)?,
                    engine: row.get(4)?,
                    result: row.get(5)?,
                    outcome: row.get(6)?,
                    feedback: row.get(7)?,
                    started_at: row.get(8)?,
                    ended_at: row.get(9)?,
                    total_tokens: row.get(10)?,
                    total_latency_seconds: row.get(11)?,
                    steps: row
                        .get::<_, String>(12)
                        .ok()
                        .and_then(|s| serde_json::from_str(&s).ok())
                        .unwrap_or_default(),
                    metadata: row
                        .get::<_, String>(13)
                        .ok()
                        .and_then(|s| serde_json::from_str(&s).ok())
                        .unwrap_or_default(),
                })
            })
            .ok();

        Ok(result)
    }

    pub fn list_traces(
        &self,
        limit: usize,
        offset: usize,
    ) -> Result<Vec<Trace>, OpenJarvisError> {
        let conn = self.conn.lock();
        let mut stmt = conn
            .prepare(
                "SELECT trace_id, query, agent, model, engine, result, outcome, feedback,
                        started_at, ended_at, total_tokens, total_latency_seconds,
                        steps_json, metadata_json
                 FROM traces ORDER BY started_at DESC LIMIT ?1 OFFSET ?2",
            )
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;

        let traces = stmt
            .query_map(rusqlite::params![limit as i64, offset as i64], |row| {
                Ok(Trace {
                    trace_id: row.get(0)?,
                    query: row.get(1)?,
                    agent: row.get(2)?,
                    model: row.get(3)?,
                    engine: row.get(4)?,
                    result: row.get(5)?,
                    outcome: row.get(6)?,
                    feedback: row.get(7)?,
                    started_at: row.get(8)?,
                    ended_at: row.get(9)?,
                    total_tokens: row.get(10)?,
                    total_latency_seconds: row.get(11)?,
                    steps: row
                        .get::<_, String>(12)
                        .ok()
                        .and_then(|s| serde_json::from_str(&s).ok())
                        .unwrap_or_default(),
                    metadata: row
                        .get::<_, String>(13)
                        .ok()
                        .and_then(|s| serde_json::from_str(&s).ok())
                        .unwrap_or_default(),
                })
            })
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?
            .filter_map(|r| r.ok())
            .collect();

        Ok(traces)
    }

    pub fn count(&self) -> Result<usize, OpenJarvisError> {
        let conn = self.conn.lock();
        let count: i64 = conn
            .query_row("SELECT COUNT(*) FROM traces", [], |row| row.get(0))
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;
        Ok(count as usize)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_trace_store_save_and_get() {
        let store = TraceStore::in_memory().unwrap();
        let trace = Trace {
            trace_id: "test123".into(),
            query: "What is 2+2?".into(),
            agent: "simple".into(),
            model: "qwen3:8b".into(),
            result: "4".into(),
            ..Default::default()
        };

        store.save(&trace).unwrap();
        let retrieved = store.get("test123").unwrap().unwrap();
        assert_eq!(retrieved.query, "What is 2+2?");
        assert_eq!(retrieved.result, "4");
    }

    #[test]
    fn test_trace_store_list() {
        let store = TraceStore::in_memory().unwrap();
        for i in 0..5 {
            let trace = Trace {
                trace_id: format!("t{i}"),
                query: format!("query {i}"),
                ..Default::default()
            };
            store.save(&trace).unwrap();
        }
        assert_eq!(store.count().unwrap(), 5);
        let list = store.list_traces(3, 0).unwrap();
        assert_eq!(list.len(), 3);
    }
}
