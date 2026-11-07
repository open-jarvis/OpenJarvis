# Benchmarks

The benchmarking framework measures inference engine performance with reproducible, standardized tests. It includes built-in benchmarks for latency and throughput, a suite runner for batch execution, and support for custom benchmarks.

## Overview

FridayAI ships with two benchmarks:

| Benchmark     | Registry Key   | Measures                                      |
|---------------|----------------|-----------------------------------------------|
| **Latency**   | `latency`      | Per-call inference latency (mean, p50, p95, min, max) |
| **Throughput**| `throughput`    | Tokens per second throughput                  |

---

## BaseBenchmark ABC

All benchmarks implement the `BaseBenchmark` abstract base class.

```python
from abc import ABC, abstractmethod
from friday_ai.bench._stubs import BenchmarkResult
from friday_ai.engine._stubs import InferenceEngine

class BaseBenchmark(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this benchmark."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this benchmark measures."""

    @abstractmethod
    def run(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        num_samples: int = 10,
    ) -> BenchmarkResult:
        """Execute the benchmark and return results."""
```

### BenchmarkResult

Each benchmark run produces a `BenchmarkResult`:

| Field            | Type             | Description                              |
|------------------|------------------|------------------------------------------|
| `benchmark_name` | `str`            | Name of the benchmark                    |
| `model`          | `str`            | Model used                               |
| `engine`         | `str`            | Engine backend used                      |
| `metrics`        | `dict[str, float]` | Key-value pairs of measured metrics    |
| `metadata`       | `dict[str, Any]` | Additional metadata                      |
| `samples`        | `int`            | Number of samples run                    |
| `errors`         | `int`            | Number of errors encountered             |

---

## Built-in Benchmarks

### Latency Benchmark

Measures per-call inference latency using short, fixed prompts. Each sample sends a simple prompt to the engine and measures wall-clock time.

**Prompts used:** The benchmark rotates through a set of short canned prompts ("Hello", "What is 2+2?", "Explain gravity in one sentence") to keep input variation consistent across runs.

**Metrics produced:**

| Metric          | Description                                         |
|-----------------|-----------------------------------------------------|
| `mean_latency`  | Average latency across all successful samples       |
| `p50_latency`   | Median latency (50th percentile)                    |
| `p95_latency`   | 95th percentile latency (tail performance)          |
| `min_latency`   | Fastest single call                                 |
| `max_latency`   | Slowest single call                                 |

**Example output:**

```
latency (10 samples, 0 errors)
  mean_latency: 0.2345
  p50_latency:  0.2100
  p95_latency:  0.3800
  min_latency:  0.1500
  max_latency:  0.4200
```

### Throughput Benchmark

Measures inference throughput in tokens per second. Each sample sends a longer prompt ("Write a short paragraph about artificial intelligence") and measures both the time taken and the number of completion tokens generated.

**Metrics produced:**

| Metric                | Description                                    |
|-----------------------|------------------------------------------------|
| `tokens_per_second`   | Total completion tokens / total time           |
| `total_tokens`        | Total completion tokens across all samples     |
| `total_time_seconds`  | Total wall-clock time across all samples       |

**Example output:**

```
throughput (10 samples, 0 errors)
  tokens_per_second:  45.6789
  total_tokens:       1250.0000
  total_time_seconds: 27.3600
```

---

## Interpreting Results

### Latency Metrics

- **mean_latency:** The average response time. Use this for general performance comparison.
- **p50_latency (median):** The typical response time. Less affected by outliers than the mean.
- **p95_latency:** The worst-case response time for 95% of requests. Critical for user experience -- if this is too high, some users will experience noticeable delays.
- **min/max_latency:** The best and worst individual calls. A large gap between min and max indicates inconsistent performance.

!!! tip "What to look for"
    A healthy setup has `p95 / p50 < 2`. If the p95 is much higher than the median, investigate whether the engine is experiencing contention, thermal throttling, or memory pressure.

### Throughput Metrics

- **tokens_per_second:** The main throughput indicator. Higher is better. Typical ranges:
    - CPU-only: 5-20 tokens/second
    - Consumer GPU (RTX 3060-4090): 30-100 tokens/second
    - Data-center GPU (A100, H100): 100-500+ tokens/second
- **total_tokens / total_time:** The raw data behind the throughput calculation. Useful for verifying that the engine is generating meaningful output (not returning empty responses).

---

## BenchmarkSuite

The `BenchmarkSuite` class runs a collection of benchmarks and provides aggregation and serialization utilities.

```python
from friday_ai.bench._stubs import BenchmarkSuite
from friday_ai.bench.latency import LatencyBenchmark
from friday_ai.bench.throughput import ThroughputBenchmark

suite = BenchmarkSuite([LatencyBenchmark(), ThroughputBenchmark()])

# Run all benchmarks
results = suite.run_all(engine, model, num_samples=20)

# Serialize to JSONL (one JSON object per line)
jsonl = suite.to_jsonl(results)

# Get a summary dict
summary = suite.summary(results)
```

### Methods

| Method                  | Returns            | Description                              |
|-------------------------|--------------------|--------------------------------------------|
| `run_all(engine, model, num_samples=10)` | `list[BenchmarkResult]` | Run all benchmarks sequentially |
| `to_jsonl(results)`     | `str`              | Serialize results to JSONL format        |
| `summary(results)`      | `dict[str, Any]`   | Create a summary dictionary              |

### JSONL Format

Each line in the JSONL output is a JSON object:

```json
{"benchmark_name": "latency", "model": "qwen3:8b", "engine": "ollama", "metrics": {"mean_latency": 0.234, "p50_latency": 0.21, "p95_latency": 0.38, "min_latency": 0.15, "max_latency": 0.42}, "metadata": {}, "samples": 10, "errors": 0}
{"benchmark_name": "throughput", "model": "qwen3:8b", "engine": "ollama", "metrics": {"tokens_per_second": 45.67, "total_tokens": 1250.0, "total_time_seconds": 27.36}, "metadata": {}, "samples": 10, "errors": 0}
```

### Summary Format

```json
{
  "benchmark_count": 2,
  "benchmarks": [
    {
      "name": "latency",
      "model": "qwen3:8b",
      "engine": "ollama",
      "metrics": {"mean_latency": 0.234, ...},
      "samples": 10,
      "errors": 0
    },
    {
      "name": "throughput",
      "model": "qwen3:8b",
      "engine": "ollama",
      "metrics": {"tokens_per_second": 45.67, ...},
      "samples": 10,
      "errors": 0
    }
  ]
}
```

---

## CLI Usage

```bash
# Run all benchmarks with default settings (10 samples)
friday bench run

# Run with more samples for better statistical accuracy
friday bench run -n 50

# Run only the latency benchmark
friday bench run -b latency

# Run only the throughput benchmark with 20 samples
friday bench run -b throughput -n 20

# Specify model and engine
friday bench run -m qwen3:8b -e ollama

# Output JSON summary to stdout
friday bench run --json

# Write JSONL results to a file
friday bench run -o results.jsonl

# Combine options
friday bench run -b latency -n 100 -m qwen3:8b --json -o latency.jsonl
```

| Option                     | Type   | Default | Description                              |
|----------------------------|--------|---------|------------------------------------------|
| `-m`, `--model MODEL`      | string | auto    | Model to benchmark                       |
| `-e`, `--engine ENGINE`    | string | auto    | Engine backend                           |
| `-n`, `--samples N`        | int    | `10`    | Number of samples per benchmark          |
| `-b`, `--benchmark NAME`   | string | all     | Specific benchmark to run (`latency` or `throughput`) |
| `-o`, `--output PATH`      | path   | none    | Write JSONL results to file              |
| `--json`                   | flag   | off     | Output JSON summary to stdout            |

---

## Adding Custom Benchmarks

Create a custom benchmark by subclassing `BaseBenchmark` and registering it with the `BenchmarkRegistry`.

### Step 1: Implement the Benchmark

```python
import time
from friday_ai.bench._stubs import BaseBenchmark, BenchmarkResult
from friday_ai.core.registry import BenchmarkRegistry
from friday_ai.core.types import Message, Role
from friday_ai.engine._stubs import InferenceEngine


class ContextLengthBenchmark(BaseBenchmark):
    """Measures how latency scales with input length."""

    @property
    def name(self) -> str:
        return "context_length"

    @property
    def description(self) -> str:
        return "Measures latency scaling with increasing input length"

    def run(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        num_samples: int = 10,
    ) -> BenchmarkResult:
        latencies = {}
        errors = 0

        for length in [100, 500, 1000, 2000]:
            prompt = "x " * length
            messages = [Message(role=Role.USER, content=prompt)]

            t0 = time.time()
            try:
                engine.generate(messages, model=model)
                latencies[f"latency_{length}_tokens"] = time.time() - t0
            except Exception:
                errors += 1

        return BenchmarkResult(
            benchmark_name=self.name,
            model=model,
            engine=engine.engine_id,
            metrics=latencies,
            samples=len(latencies),
            errors=errors,
        )
```

### Step 2: Register the Benchmark

Use the `ensure_registered()` pattern to survive registry clearing in tests:

```python
def ensure_registered() -> None:
    """Register the benchmark if not already present."""
    if not BenchmarkRegistry.contains("context_length"):
        BenchmarkRegistry.register_value("context_length", ContextLengthBenchmark)
```

Alternatively, use the decorator at class definition time:

```python
@BenchmarkRegistry.register("context_length")
class ContextLengthBenchmark(BaseBenchmark):
    ...
```

!!! info "The `ensure_registered()` Pattern"
    The `ensure_registered()` function is preferred over the decorator for benchmark modules because it survives registry clearing during testing. The built-in `latency` and `throughput` benchmarks both use this pattern. The benchmark CLI command calls `ensure_registered()` before looking up benchmarks.

### Step 3: Use Your Benchmark

Once registered, your benchmark is available through the CLI:

```bash
friday bench run -b context_length
```

And through the `BenchmarkSuite`:

```python
from friday_ai.core.registry import BenchmarkRegistry

bench_cls = BenchmarkRegistry.get("context_length")
bench = bench_cls()
result = bench.run(engine, model, num_samples=5)
```
