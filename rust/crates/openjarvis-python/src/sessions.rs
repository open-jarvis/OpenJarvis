//! PyO3 bindings for session management.

use pyo3::prelude::*;

#[pyclass(name = "SessionStore", unsendable)]
pub struct PySessionStore {
    inner: openjarvis_sessions::SessionStore,
}

#[pymethods]
impl PySessionStore {
    #[new]
    #[pyo3(signature = (db_path=":memory:", max_age_hours=24.0, consolidation_threshold=100))]
    fn new(db_path: &str, max_age_hours: f64, consolidation_threshold: usize) -> Self {
        Self {
            inner: openjarvis_sessions::SessionStore::new(
                db_path,
                max_age_hours,
                consolidation_threshold,
            ),
        }
    }

    fn get_or_create(
        &self,
        user_id: &str,
        channel: &str,
        channel_user_id: &str,
        display_name: &str,
    ) -> String {
        let session = self
            .inner
            .get_or_create(user_id, channel, channel_user_id, display_name);
        serde_json::to_string(&session).unwrap_or_default()
    }

    fn save_message(
        &self,
        session_id: &str,
        role: &str,
        content: &str,
        channel: &str,
    ) -> PyResult<()> {
        self.inner
            .save_message(session_id, role, content, channel)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    fn consolidate(&self, session_id: &str) {
        self.inner.consolidate(session_id);
    }

    fn link_channel(&self, session_id: &str, channel: &str, channel_user_id: &str) {
        self.inner.link_channel(session_id, channel, channel_user_id);
    }

    fn list_sessions(&self, active_only: bool, limit: usize) -> String {
        let sessions = self.inner.list_sessions(active_only, limit);
        serde_json::to_string(&sessions).unwrap_or_default()
    }

    #[pyo3(signature = (max_age_hours=None))]
    fn decay(&self, max_age_hours: Option<f64>) -> usize {
        self.inner.decay(max_age_hours)
    }
}
