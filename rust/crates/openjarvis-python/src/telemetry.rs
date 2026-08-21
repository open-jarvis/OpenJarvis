//! PyO3 bindings for telemetry types.

use pyo3::prelude::*;
use std::sync::Arc;

#[pyclass(name = "TelemetryStore")]
pub struct PyTelemetryStore {
    pub inner: Arc<openjarvis_telemetry::TelemetryStore>,
}

#[pymethods]
impl PyTelemetryStore {
    #[new]
    #[pyo3(signature = (path=None))]
    fn new(path: Option<&str>) -> PyResult<Self> {
        let inner = match path {
            Some(p) => openjarvis_telemetry::TelemetryStore::new(std::path::Path::new(p)),
            None => openjarvis_telemetry::TelemetryStore::in_memory(),
        }
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    fn count(&self) -> PyResult<usize> {
        self.inner
            .count()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    fn clear(&self) -> PyResult<()> {
        self.inner
            .clear()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }
}

/// TelemetryAggregator computes aggregate stats from a TelemetryStore.
/// The Rust type is a unit struct with a static method.
#[pyclass(name = "TelemetryAggregator")]
pub struct PyTelemetryAggregator {
    store: Arc<openjarvis_telemetry::TelemetryStore>,
}

#[pymethods]
impl PyTelemetryAggregator {
    #[new]
    fn new(store: &PyTelemetryStore) -> Self {
        Self {
            store: Arc::clone(&store.inner),
        }
    }

    fn stats(&self) -> PyResult<String> {
        let stats = openjarvis_telemetry::TelemetryAggregator::stats(&self.store)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(serde_json::to_string(&stats).unwrap_or_default())
    }
}

#[pyclass(name = "InstrumentedEngine")]
pub struct PyInstrumentedEngine {
    inner: openjarvis_telemetry::InstrumentedEngine<openjarvis_engine::Engine>,
}

#[pymethods]
impl PyInstrumentedEngine {
    #[new]
    #[pyo3(signature = (engine_key="ollama", host="http://localhost:11434", store_path=None, agent_name="default"))]
    fn new(engine_key: &str, host: &str, store_path: Option<&str>, agent_name: &str) -> PyResult<Self> {
        let config = openjarvis_core::JarvisConfig::default();
        let engine = openjarvis_engine::get_engine_static(&config, Some(engine_key))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        let store = Arc::new(match store_path {
            Some(p) => openjarvis_telemetry::TelemetryStore::new(std::path::Path::new(p)),
            None => openjarvis_telemetry::TelemetryStore::in_memory(),
        }
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?);
        Ok(Self {
            inner: openjarvis_telemetry::InstrumentedEngine::new(
                engine,
                store,
                agent_name.to_string(),
            ),
        })
    }

    fn engine_id(&self) -> &str {
        use openjarvis_engine::InferenceEngine;
        self.inner.engine_id()
    }
}

// --- New telemetry session classes ---

/// Python wrapper for TelemetrySample.
#[pyclass(name = "TelemetrySample", from_py_object)]
#[derive(Clone)]
pub struct PyTelemetrySample {
    pub timestamp_ns: u64,
    pub gpu_power_w: f64,
    pub cpu_power_w: f64,
    pub gpu_energy_j: f64,
    pub cpu_energy_j: f64,
    pub gpu_util_pct: f64,
    pub gpu_temp_c: f64,
    pub gpu_mem_gb: f64,
}

#[pymethods]
impl PyTelemetrySample {
    #[new]
    #[pyo3(signature = (timestamp_ns, gpu_power_w=0.0, cpu_power_w=0.0, gpu_energy_j=0.0, cpu_energy_j=0.0, gpu_util_pct=0.0, gpu_temp_c=0.0, gpu_mem_gb=0.0))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        timestamp_ns: u64,
        gpu_power_w: f64,
        cpu_power_w: f64,
        gpu_energy_j: f64,
        cpu_energy_j: f64,
        gpu_util_pct: f64,
        gpu_temp_c: f64,
        gpu_mem_gb: f64,
    ) -> Self {
        Self {
            timestamp_ns,
            gpu_power_w,
            cpu_power_w,
            gpu_energy_j,
            cpu_energy_j,
            gpu_util_pct,
            gpu_temp_c,
            gpu_mem_gb,
        }
    }

    #[getter]
    fn timestamp_ns(&self) -> u64 {
        self.timestamp_ns
    }
    #[getter]
    fn gpu_power_w(&self) -> f64 {
        self.gpu_power_w
    }
    #[getter]
    fn cpu_power_w(&self) -> f64 {
        self.cpu_power_w
    }
    #[getter]
    fn gpu_energy_j(&self) -> f64 {
        self.gpu_energy_j
    }
    #[getter]
    fn cpu_energy_j(&self) -> f64 {
        self.cpu_energy_j
    }
    #[getter]
    fn gpu_util_pct(&self) -> f64 {
        self.gpu_util_pct
    }
    #[getter]
    fn gpu_temp_c(&self) -> f64 {
        self.gpu_temp_c
    }
    #[getter]
    fn gpu_mem_gb(&self) -> f64 {
        self.gpu_mem_gb
    }
}

/// Python wrapper for TelemetrySessionCore (ring buffer).
#[pyclass(name = "TelemetrySessionCore")]
pub struct PyTelemetrySessionCore {
    inner: openjarvis_telemetry::session::TelemetrySessionCore,
}

#[pymethods]
impl PyTelemetrySessionCore {
    #[new]
    #[pyo3(signature = (capacity=100000, sampling_interval_ms=100))]
    fn new(capacity: usize, sampling_interval_ms: u64) -> Self {
        Self {
            inner: openjarvis_telemetry::session::TelemetrySessionCore::new(
                capacity,
                sampling_interval_ms,
            ),
        }
    }

    fn add_sample(&self, sample: &PyTelemetrySample) {
        let s = openjarvis_telemetry::session::TelemetrySample {
            timestamp_ns: sample.timestamp_ns,
            gpu_power_w: sample.gpu_power_w,
            cpu_power_w: sample.cpu_power_w,
            gpu_energy_j: sample.gpu_energy_j,
            cpu_energy_j: sample.cpu_energy_j,
            gpu_util_pct: sample.gpu_util_pct,
            gpu_temp_c: sample.gpu_temp_c,
            gpu_mem_gb: sample.gpu_mem_gb,
        };
        self.inner.add_sample(s);
    }

    fn window(&self, start_ns: u64, end_ns: u64) -> Vec<PyTelemetrySample> {
        self.inner
            .window(start_ns, end_ns)
            .into_iter()
            .map(|s| PyTelemetrySample {
                timestamp_ns: s.timestamp_ns,
                gpu_power_w: s.gpu_power_w,
                cpu_power_w: s.cpu_power_w,
                gpu_energy_j: s.gpu_energy_j,
                cpu_energy_j: s.cpu_energy_j,
                gpu_util_pct: s.gpu_util_pct,
                gpu_temp_c: s.gpu_temp_c,
                gpu_mem_gb: s.gpu_mem_gb,
            })
            .collect()
    }

    fn compute_energy_delta(&self, start_ns: u64, end_ns: u64) -> (f64, f64) {
        self.inner.compute_energy_delta(start_ns, end_ns)
    }

    fn compute_avg_power(&self, start_ns: u64, end_ns: u64) -> (f64, f64) {
        self.inner.compute_avg_power(start_ns, end_ns)
    }

    fn len(&self) -> usize {
        self.inner.len()
    }

    fn clear(&self) {
        self.inner.clear();
    }
}

/// Python wrapper for ITL stats computation.
#[pyclass(name = "ItlStats")]
pub struct PyItlStats;

#[pymethods]
impl PyItlStats {
    #[new]
    fn new() -> Self {
        Self
    }

    #[staticmethod]
    fn compute(token_timestamps_ms: Vec<f64>) -> PyResult<pyo3::Py<pyo3::types::PyDict>> {
        let stats = openjarvis_telemetry::itl::compute_itl_stats(&token_timestamps_ms);
        pyo3::Python::attach(|py| {
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("p50_ms", stats.p50_ms)?;
            dict.set_item("p90_ms", stats.p90_ms)?;
            dict.set_item("p95_ms", stats.p95_ms)?;
            dict.set_item("p99_ms", stats.p99_ms)?;
            dict.set_item("mean_ms", stats.mean_ms)?;
            dict.set_item("min_ms", stats.min_ms)?;
            dict.set_item("max_ms", stats.max_ms)?;
            Ok(dict.into())
        })
    }
}

/// Python wrapper for FLOPs estimation.
#[pyclass(name = "FlopsEstimator")]
pub struct PyFlopsEstimator;

#[pymethods]
impl PyFlopsEstimator {
    #[new]
    fn new() -> Self {
        Self
    }

    #[staticmethod]
    fn estimate_flops(model: &str, input_tokens: u64, output_tokens: u64) -> (f64, f64) {
        openjarvis_telemetry::flops::estimate_flops(model, input_tokens, output_tokens)
    }

    #[staticmethod]
    #[pyo3(signature = (flops, duration_s, gpu_name, num_gpus=1))]
    fn compute_mfu(flops: f64, duration_s: f64, gpu_name: &str, num_gpus: u32) -> f64 {
        openjarvis_telemetry::flops::compute_mfu(flops, duration_s, gpu_name, num_gpus)
    }
}

/// Python wrapper for phase metrics.
#[pyclass(name = "PhaseMetrics")]
pub struct PyPhaseMetrics;

#[pymethods]
impl PyPhaseMetrics {
    #[new]
    fn new() -> Self {
        Self
    }

    #[staticmethod]
    fn compute(
        samples: Vec<PyTelemetrySample>,
        start_ns: u64,
        end_ns: u64,
        tokens: u64,
    ) -> PyResult<pyo3::Py<pyo3::types::PyDict>> {
        let rust_samples: Vec<openjarvis_telemetry::session::TelemetrySample> = samples
            .iter()
            .map(|s| openjarvis_telemetry::session::TelemetrySample {
                timestamp_ns: s.timestamp_ns,
                gpu_power_w: s.gpu_power_w,
                cpu_power_w: s.cpu_power_w,
                gpu_energy_j: s.gpu_energy_j,
                cpu_energy_j: s.cpu_energy_j,
                gpu_util_pct: s.gpu_util_pct,
                gpu_temp_c: s.gpu_temp_c,
                gpu_mem_gb: s.gpu_mem_gb,
            })
            .collect();
        let metrics =
            openjarvis_telemetry::phase::compute_phase_metrics(&rust_samples, start_ns, end_ns, tokens);
        pyo3::Python::attach(|py| {
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("energy_j", metrics.energy_j)?;
            dict.set_item("mean_power_w", metrics.mean_power_w)?;
            dict.set_item("duration_s", metrics.duration_s)?;
            dict.set_item("energy_per_token_j", metrics.energy_per_token_j)?;
            dict.set_item("tokens", metrics.tokens)?;
            Ok(dict.into())
        })
    }

    #[staticmethod]
    fn split_at_ttft(
        samples: Vec<PyTelemetrySample>,
        start_ns: u64,
        ttft_ns: u64,
        end_ns: u64,
        input_tokens: u64,
        output_tokens: u64,
    ) -> PyResult<(pyo3::Py<pyo3::types::PyDict>, pyo3::Py<pyo3::types::PyDict>)> {
        let rust_samples: Vec<openjarvis_telemetry::session::TelemetrySample> = samples
            .iter()
            .map(|s| openjarvis_telemetry::session::TelemetrySample {
                timestamp_ns: s.timestamp_ns,
                gpu_power_w: s.gpu_power_w,
                cpu_power_w: s.cpu_power_w,
                gpu_energy_j: s.gpu_energy_j,
                cpu_energy_j: s.cpu_energy_j,
                gpu_util_pct: s.gpu_util_pct,
                gpu_temp_c: s.gpu_temp_c,
                gpu_mem_gb: s.gpu_mem_gb,
            })
            .collect();
        let (prefill, decode) = openjarvis_telemetry::phase::split_at_ttft(
            &rust_samples,
            start_ns,
            ttft_ns,
            end_ns,
            input_tokens,
            output_tokens,
        );
        pyo3::Python::attach(|py| {
            let prefill_dict = pyo3::types::PyDict::new(py);
            prefill_dict.set_item("energy_j", prefill.energy_j)?;
            prefill_dict.set_item("mean_power_w", prefill.mean_power_w)?;
            prefill_dict.set_item("duration_s", prefill.duration_s)?;
            prefill_dict.set_item("energy_per_token_j", prefill.energy_per_token_j)?;
            prefill_dict.set_item("tokens", prefill.tokens)?;

            let decode_dict = pyo3::types::PyDict::new(py);
            decode_dict.set_item("energy_j", decode.energy_j)?;
            decode_dict.set_item("mean_power_w", decode.mean_power_w)?;
            decode_dict.set_item("duration_s", decode.duration_s)?;
            decode_dict.set_item("energy_per_token_j", decode.energy_per_token_j)?;
            decode_dict.set_item("tokens", decode.tokens)?;

            Ok((prefill_dict.into(), decode_dict.into()))
        })
    }
}
