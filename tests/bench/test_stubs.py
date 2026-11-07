"""Tests for benchmark stubs — BenchmarkResult, BaseBenchmark, BenchmarkSuite."""

from __future__ import annotations

import json

import pytest

from friday_ai.bench._stubs import BaseBenchmark, BenchmarkResult, BenchmarkSuite


class TestBenchmarkResult:
    def test_defaults(self):
        r = BenchmarkResult(benchmark_name="test", model="m1", engine="e1")
        assert r.benchmark_name == "test"
        assert r.model == "m1"
        assert r.engine == "e1"
        assert r.metrics == {}
        assert r.metadata == {}
        assert r.samples == 0
        assert r.errors == 0

    def test_full(self):
        r = BenchmarkResult(
            benchmark_name="latency",
            model="gpt-4",
            engine="vllm",
            metrics={"mean_latency": 0.5},
            metadata={"note": "test"},
            samples=10,
            errors=1,
        )
        assert r.metrics["mean_latency"] == 0.5
        assert r.samples == 10
        assert r.errors == 1


class TestBaseBenchmark:
    def test_abc_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BaseBenchmark()

    def test_concrete_subclass(self):
        class DummyBench(BaseBenchmark):
            @property
            def name(self):
                return "dummy"

            @property
            def description(self):
                return "A dummy benchmark"

            def run(self, engine, model, *, num_samples=10):
                return BenchmarkResult(
                    benchmark_name=self.name,
                    model=model,
                    engine=engine.engine_id,
                    samples=num_samples,
                )

        b = DummyBench()
        assert b.name == "dummy"
        assert b.description == "A dummy benchmark"


class TestBenchmarkSuite:
    def _make_bench(self, name="test"):
        class _Bench(BaseBenchmark):
            @property
            def name(self_inner):
                return name

            @property
            def description(self_inner):
                return f"{name} benchmark"

            def run(self_inner, engine, model, *, num_samples=10):
                return BenchmarkResult(
                    benchmark_name=name,
                    model=model,
                    engine="mock",
                    metrics={"value": 1.0},
                    samples=num_samples,
                )

        return _Bench()

    def test_run_all(self):
        suite = BenchmarkSuite([self._make_bench("a"), self._make_bench("b")])
        results = suite.run_all(None, "m1", num_samples=5)
        assert len(results) == 2
        assert results[0].benchmark_name == "a"
        assert results[1].benchmark_name == "b"

    def test_run_all_empty(self):
        suite = BenchmarkSuite([])
        results = suite.run_all(None, "m1")
        assert results == []

    def test_to_jsonl(self):
        suite = BenchmarkSuite([self._make_bench()])
        results = suite.run_all(None, "m1")
        jsonl = suite.to_jsonl(results)
        lines = jsonl.strip().split("\n")
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["benchmark_name"] == "test"

    def test_to_jsonl_valid_json(self):
        suite = BenchmarkSuite([self._make_bench("a"), self._make_bench("b")])
        results = suite.run_all(None, "m1")
        jsonl = suite.to_jsonl(results)
        for line in jsonl.strip().split("\n"):
            obj = json.loads(line)
            assert "benchmark_name" in obj

    def test_summary_format(self):
        suite = BenchmarkSuite([self._make_bench()])
        results = suite.run_all(None, "m1")
        summary = suite.summary(results)
        assert "benchmark_count" in summary
        assert "benchmarks" in summary

    def test_summary_count(self):
        suite = BenchmarkSuite([self._make_bench("a"), self._make_bench("b")])
        results = suite.run_all(None, "m1")
        summary = suite.summary(results)
        assert summary["benchmark_count"] == 2
        assert len(summary["benchmarks"]) == 2
