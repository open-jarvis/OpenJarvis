//! OpenJarvis Scheduler — task scheduling with cron, interval, and one-shot
//! triggers backed by SQLite persistence.

use chrono::{Datelike, Timelike};
use rusqlite::params;
use serde::{Deserialize, Serialize};
use serde_json::Value;

// ---------------------------------------------------------------------------
// Schedule / status enums
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ScheduleType {
    Cron,
    Interval,
    Once,
}

impl ScheduleType {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Cron => "cron",
            Self::Interval => "interval",
            Self::Once => "once",
        }
    }

    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "cron" => Some(Self::Cron),
            "interval" => Some(Self::Interval),
            "once" => Some(Self::Once),
            _ => None,
        }
    }
}

impl std::fmt::Display for ScheduleType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskStatus {
    Active,
    Paused,
    Cancelled,
    Completed,
}

impl TaskStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Paused => "paused",
            Self::Cancelled => "cancelled",
            Self::Completed => "completed",
        }
    }

    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "active" => Some(Self::Active),
            "paused" => Some(Self::Paused),
            "cancelled" => Some(Self::Cancelled),
            "completed" => Some(Self::Completed),
            _ => None,
        }
    }
}

impl std::fmt::Display for TaskStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

// ---------------------------------------------------------------------------
// Scheduled task
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScheduledTask {
    pub id: String,
    pub name: String,
    pub description: String,
    pub schedule_type: ScheduleType,
    pub schedule_value: String,
    pub status: TaskStatus,
    pub last_run: Option<f64>,
    pub next_run: Option<f64>,
    pub created_at: f64,
    pub metadata: Value,
}

// ---------------------------------------------------------------------------
// Cron expression parser (minute hour dom month dow)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy)]
enum CronField {
    Any,
    Specific(u32),
}

/// A parsed 5-field cron expression stored as a fixed-size array.
#[derive(Debug, Clone, Copy)]
struct CronExpr {
    fields: [CronField; 5],
}

fn parse_cron_field(s: &str) -> Option<CronField> {
    if s == "*" {
        Some(CronField::Any)
    } else {
        s.parse::<u32>().ok().map(CronField::Specific)
    }
}

fn cron_field_matches(field: CronField, value: u32) -> bool {
    match field {
        CronField::Any => true,
        CronField::Specific(v) => v == value,
    }
}

/// Parse a basic cron expression (`"min hour dom month dow"`) and return the
/// next occurrence after `after` (unix timestamp). Supports specific numbers
/// and `*` (any). Scans up to ~1 year of minutes.
pub fn parse_cron_next(expr: &str, after: f64) -> Option<f64> {
    let parts: Vec<&str> = expr.split_whitespace().collect();
    if parts.len() != 5 {
        return None;
    }

    let cron = CronExpr {
        fields: [
            parse_cron_field(parts[0])?,
            parse_cron_field(parts[1])?,
            parse_cron_field(parts[2])?,
            parse_cron_field(parts[3])?,
            parse_cron_field(parts[4])?,
        ],
    };

    let start_ts = (after as i64 / 60 + 1) * 60;

    for i in 0..525_960i64 {
        let ts = start_ts + i * 60;
        let dt = chrono::DateTime::from_timestamp(ts, 0)?;

        let matches = cron_field_matches(cron.fields[0], dt.minute())
            && cron_field_matches(cron.fields[1], dt.hour())
            && cron_field_matches(cron.fields[2], dt.day())
            && cron_field_matches(cron.fields[3], dt.month())
            && cron_field_matches(cron.fields[4], dt.weekday().num_days_from_sunday());

        if matches {
            return Some(ts as f64);
        }
    }

    None
}

// ---------------------------------------------------------------------------
// SQLite-backed scheduler store
// ---------------------------------------------------------------------------

fn now_timestamp() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

pub struct SchedulerStore {
    conn: rusqlite::Connection,
}

impl SchedulerStore {
    pub fn new(db_path: &str) -> Self {
        let conn = rusqlite::Connection::open(db_path).expect("Failed to open scheduler database");
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id             TEXT PRIMARY KEY,
                name           TEXT NOT NULL,
                description    TEXT NOT NULL DEFAULT '',
                schedule_type  TEXT NOT NULL,
                schedule_value TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'active',
                last_run       REAL,
                next_run       REAL,
                created_at     REAL NOT NULL,
                metadata       TEXT NOT NULL DEFAULT '{}'
            )",
        )
        .expect("Failed to create scheduled_tasks table");
        Self { conn }
    }

    pub fn create_task(
        &self,
        name: &str,
        schedule_type: ScheduleType,
        schedule_value: &str,
    ) -> ScheduledTask {
        let now = now_timestamp();
        let id = uuid::Uuid::new_v4().to_string();

        let next_run = match schedule_type {
            ScheduleType::Cron => parse_cron_next(schedule_value, now),
            ScheduleType::Interval => schedule_value.parse::<f64>().ok().map(|secs| now + secs),
            ScheduleType::Once => schedule_value.parse::<f64>().ok(),
        };

        self.conn
            .execute(
                "INSERT INTO scheduled_tasks
                    (id, name, schedule_type, schedule_value, status, next_run, created_at)
                 VALUES (?1, ?2, ?3, ?4, 'active', ?5, ?6)",
                params![id, name, schedule_type.as_str(), schedule_value, next_run, now],
            )
            .expect("Failed to insert task");

        ScheduledTask {
            id,
            name: name.into(),
            description: String::new(),
            schedule_type,
            schedule_value: schedule_value.into(),
            status: TaskStatus::Active,
            last_run: None,
            next_run,
            created_at: now,
            metadata: Value::Object(serde_json::Map::new()),
        }
    }

    pub fn get_task(&self, id: &str) -> Option<ScheduledTask> {
        self.conn
            .query_row(
                "SELECT id, name, description, schedule_type, schedule_value,
                        status, last_run, next_run, created_at, metadata
                 FROM scheduled_tasks WHERE id = ?1",
                params![id],
                |row| Ok(row_to_task(row)),
            )
            .ok()
    }

    pub fn list_tasks(&self) -> Vec<ScheduledTask> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT id, name, description, schedule_type, schedule_value,
                        status, last_run, next_run, created_at, metadata
                 FROM scheduled_tasks ORDER BY created_at",
            )
            .expect("Failed to prepare list query");

        stmt.query_map([], |row| Ok(row_to_task(row)))
            .expect("Failed to query tasks")
            .filter_map(|r| r.ok())
            .collect()
    }

    pub fn update_status(&self, id: &str, status: TaskStatus) -> bool {
        let changed = self
            .conn
            .execute(
                "UPDATE scheduled_tasks SET status = ?1 WHERE id = ?2",
                params![status.as_str(), id],
            )
            .unwrap_or(0);
        changed > 0
    }

    pub fn record_run(&self, id: &str, timestamp: f64) -> bool {
        let changed = self
            .conn
            .execute(
                "UPDATE scheduled_tasks SET last_run = ?1 WHERE id = ?2",
                params![timestamp, id],
            )
            .unwrap_or(0);
        changed > 0
    }

    pub fn delete_task(&self, id: &str) -> bool {
        let changed = self
            .conn
            .execute("DELETE FROM scheduled_tasks WHERE id = ?1", params![id])
            .unwrap_or(0);
        changed > 0
    }

    /// Return tasks matching a generic predicate.
    pub fn tasks_matching<F>(&self, predicate: F) -> Vec<ScheduledTask>
    where
        F: Fn(&ScheduledTask) -> bool,
    {
        self.list_tasks().into_iter().filter(predicate).collect()
    }
}

fn row_to_task(row: &rusqlite::Row<'_>) -> ScheduledTask {
    let type_str: String = row.get(3).unwrap_or_default();
    let status_str: String = row.get(5).unwrap_or_default();
    let meta_str: String = row.get(9).unwrap_or_default();

    ScheduledTask {
        id: row.get(0).unwrap_or_default(),
        name: row.get(1).unwrap_or_default(),
        description: row.get(2).unwrap_or_default(),
        schedule_type: ScheduleType::from_str(&type_str).unwrap_or(ScheduleType::Once),
        schedule_value: row.get(4).unwrap_or_default(),
        status: TaskStatus::from_str(&status_str).unwrap_or(TaskStatus::Active),
        last_run: row.get(6).ok(),
        next_run: row.get(7).ok(),
        created_at: row.get(8).unwrap_or(0.0),
        metadata: serde_json::from_str(&meta_str).unwrap_or(Value::Object(serde_json::Map::new())),
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_store() -> SchedulerStore {
        SchedulerStore::new(":memory:")
    }

    #[test]
    fn test_task_crud() {
        let store = temp_store();

        let task = store.create_task("backup", ScheduleType::Interval, "3600");
        assert_eq!(task.status, TaskStatus::Active);
        assert_eq!(task.schedule_type, ScheduleType::Interval);

        let fetched = store.get_task(&task.id).unwrap();
        assert_eq!(fetched.name, "backup");

        let all = store.list_tasks();
        assert_eq!(all.len(), 1);

        assert!(store.delete_task(&task.id));
        assert!(store.get_task(&task.id).is_none());
    }

    #[test]
    fn test_status_update_and_run_recording() {
        let store = temp_store();
        let task = store.create_task("check", ScheduleType::Once, "1700000000");

        assert!(store.update_status(&task.id, TaskStatus::Paused));
        assert_eq!(
            store.get_task(&task.id).unwrap().status,
            TaskStatus::Paused
        );

        assert!(store.record_run(&task.id, 1700000100.0));
        assert!(
            (store.get_task(&task.id).unwrap().last_run.unwrap() - 1700000100.0).abs() < 1e-3
        );

        assert!(!store.update_status("nonexistent", TaskStatus::Cancelled));
        assert!(!store.record_run("nonexistent", 0.0));
    }

    #[test]
    fn test_cron_parsing_every_day_at_nine() {
        // "0 9 * * *" = every day at 09:00
        let base = 1_700_000_000.0; // 2023-11-14 ~22:13 UTC
        let next = parse_cron_next("0 9 * * *", base).unwrap();
        let dt = chrono::DateTime::from_timestamp(next as i64, 0).unwrap();
        assert_eq!(dt.hour(), 9);
        assert_eq!(dt.minute(), 0);
        assert!(next > base);
    }

    #[test]
    fn test_cron_parsing_specific_time() {
        // "30 14 * * *" = every day at 14:30
        let base = 1_700_000_000.0;
        let next = parse_cron_next("30 14 * * *", base).unwrap();
        let dt = chrono::DateTime::from_timestamp(next as i64, 0).unwrap();
        assert_eq!(dt.hour(), 14);
        assert_eq!(dt.minute(), 30);
    }

    #[test]
    fn test_cron_invalid_expression() {
        assert!(parse_cron_next("bad", 0.0).is_none());
        assert!(parse_cron_next("* * *", 0.0).is_none());
        assert!(parse_cron_next("a b c d e", 0.0).is_none());
    }

    #[test]
    fn test_schedule_type_roundtrip() {
        for st in [ScheduleType::Cron, ScheduleType::Interval, ScheduleType::Once] {
            let json = serde_json::to_string(&st).unwrap();
            let parsed: ScheduleType = serde_json::from_str(&json).unwrap();
            assert_eq!(parsed, st);
        }
    }

    #[test]
    fn test_tasks_matching_generic() {
        let store = temp_store();
        store.create_task("daily-backup", ScheduleType::Cron, "0 2 * * *");
        store.create_task("hourly-check", ScheduleType::Interval, "3600");
        store.create_task("one-time-init", ScheduleType::Once, "1700000000");

        let cron_tasks = store.tasks_matching(|t| t.schedule_type == ScheduleType::Cron);
        assert_eq!(cron_tasks.len(), 1);
        assert_eq!(cron_tasks[0].name, "daily-backup");

        let all = store.tasks_matching(|_| true);
        assert_eq!(all.len(), 3);
    }
}
