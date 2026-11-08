//! TelemetryStore — SQLite persistence for telemetry records.

use friday_ai_core::{FridayAIError, TelemetryRecord};
use parking_lot::Mutex;
use rusqlite::Connection;
use std::path::{Path, PathBuf};

pub struct TelemetryStore {
    conn: Mutex<Connection>,
    _db_path: PathBuf,
}

impl TelemetryStore {
    pub fn new(db_path: &Path) -> Result<Self, FridayAIError> {
        if let Some(parent) = db_path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                FridayAIError::Io(std::io::Error::other(e))
            })?;
        }

        let conn = Connection::open(db_path).map_err(|e| {
            FridayAIError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                model_id TEXT,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                latency_seconds REAL DEFAULT 0,
                ttft REAL DEFAULT 0,
                cost_usd REAL DEFAULT 0,
                energy_joules REAL DEFAULT 0,
                power_watts REAL DEFAULT 0,
                gpu_utilization_pct REAL DEFAULT 0,
                gpu_memory_used_gb REAL DEFAULT 0,
                gpu_temperature_c REAL DEFAULT 0,
                throughput_tok_per_sec REAL DEFAULT 0,
                is_streaming INTEGER DEFAULT 0,
                engine TEXT DEFAULT '',
                agent TEXT DEFAULT '',
                batch_id TEXT DEFAULT '',
                is_warmup INTEGER DEFAULT 0,
                metadata_json TEXT DEFAULT '{}'
            )",
        )
        .map_err(|e| {
            FridayAIError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        Ok(Self {
            conn: Mutex::new(conn),
            _db_path: db_path.to_path_buf(),
        })
    }

    pub fn in_memory() -> Result<Self, FridayAIError> {
        Self::new(Path::new(":memory:"))
    }

    pub fn record(&self, rec: &TelemetryRecord) -> Result<(), FridayAIError> {
        let metadata_json = serde_json::to_string(&rec.metadata).unwrap_or_default();
        let conn = self.conn.lock();
        conn.execute(
            "INSERT INTO telemetry
                (timestamp, model_id, prompt_tokens, completion_tokens, total_tokens,
                 latency_seconds, ttft, cost_usd, energy_joules, power_watts,
                 gpu_utilization_pct, gpu_memory_used_gb, gpu_temperature_c,
                 throughput_tok_per_sec, is_streaming, engine, agent, batch_id,
                 is_warmup, metadata_json)
            VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,?20)",
            rusqlite::params![
                rec.timestamp,
                rec.model_id,
                rec.prompt_tokens,
                rec.completion_tokens,
                rec.total_tokens,
                rec.latency_seconds,
                rec.ttft,
                rec.cost_usd,
                rec.energy_joules,
                rec.power_watts,
                rec.gpu_utilization_pct,
                rec.gpu_memory_used_gb,
                rec.gpu_temperature_c,
                rec.throughput_tok_per_sec,
                rec.is_streaming as i32,
                rec.engine,
                rec.agent,
                rec.batch_id,
                rec.is_warmup as i32,
                metadata_json,
            ],
        )
        .map_err(|e| {
            FridayAIError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;
        Ok(())
    }

    pub fn count(&self) -> Result<usize, FridayAIError> {
        let conn = self.conn.lock();
        let count: i64 = conn
            .query_row("SELECT COUNT(*) FROM telemetry", [], |row| row.get(0))
            .map_err(|e| {
                FridayAIError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;
        Ok(count as usize)
    }

    pub fn clear(&self) -> Result<(), FridayAIError> {
        let conn = self.conn.lock();
        conn.execute("DELETE FROM telemetry", []).map_err(|e| {
            FridayAIError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_telemetry_store() {
        let store = TelemetryStore::in_memory().unwrap();
        let rec = TelemetryRecord {
            timestamp: 1000.0,
            model_id: "qwen3:8b".into(),
            prompt_tokens: 10,
            completion_tokens: 20,
            total_tokens: 30,
            latency_seconds: 0.5,
            ..Default::default()
        };
        store.record(&rec).unwrap();
        assert_eq!(store.count().unwrap(), 1);
    }
}
