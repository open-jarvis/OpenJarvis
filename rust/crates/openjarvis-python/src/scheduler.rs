//! PyO3 bindings for task scheduler.

use pyo3::prelude::*;

#[pyclass(name = "SchedulerStore", unsendable)]
pub struct PySchedulerStore {
    inner: openjarvis_scheduler::SchedulerStore,
}

#[pymethods]
impl PySchedulerStore {
    #[new]
    #[pyo3(signature = (db_path=":memory:"))]
    fn new(db_path: &str) -> Self {
        Self {
            inner: openjarvis_scheduler::SchedulerStore::new(db_path),
        }
    }

    fn create_task(&self, name: &str, schedule_type: &str, schedule_value: &str) -> PyResult<String> {
        let st = openjarvis_scheduler::ScheduleType::from_str(schedule_type).ok_or_else(|| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "invalid schedule_type '{}', expected cron/interval/once",
                schedule_type
            ))
        })?;
        let task = self.inner.create_task(name, st, schedule_value);
        Ok(serde_json::to_string(&task).unwrap_or_default())
    }

    fn get_task(&self, id: &str) -> Option<String> {
        self.inner
            .get_task(id)
            .map(|t| serde_json::to_string(&t).unwrap_or_default())
    }

    fn list_tasks(&self) -> String {
        serde_json::to_string(&self.inner.list_tasks()).unwrap_or_default()
    }

    fn update_status(&self, id: &str, status: &str) -> PyResult<bool> {
        let s = openjarvis_scheduler::TaskStatus::from_str(status).ok_or_else(|| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "invalid status '{}', expected active/paused/cancelled/completed",
                status
            ))
        })?;
        Ok(self.inner.update_status(id, s))
    }

    fn record_run(&self, id: &str, timestamp: f64) -> bool {
        self.inner.record_run(id, timestamp)
    }

    fn delete_task(&self, id: &str) -> bool {
        self.inner.delete_task(id)
    }
}

#[pyfunction]
pub fn parse_cron_next(expr: &str, after: f64) -> Option<f64> {
    openjarvis_scheduler::parse_cron_next(expr, after)
}
