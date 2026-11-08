"""Tests for QueryTrace and TurnTrace data model."""

from __future__ import annotations

import pytest

from friday_ai.evals.core.trace import QueryTrace, TurnTrace


class TestTurnTrace:
    def test_defaults(self):
        t = TurnTrace(turn_index=0)
        assert t.input_tokens == 0
        assert t.output_tokens == 0
        assert t.tools_called == []
        assert t.gpu_energy_joules is None
        assert t.cost_usd is None

    def test_to_dict_roundtrip(self):
        t = TurnTrace(
            turn_index=1,
            input_tokens=100,
            output_tokens=50,
            tools_called=["calculator"],
            tool_latencies_s={"calculator": 0.5},
            wall_clock_s=1.2,
            gpu_energy_joules=10.0,
            cost_usd=0.001,
        )
        d = t.to_dict()
        t2 = TurnTrace.from_dict(d)
        assert t2.turn_index == 1
        assert t2.input_tokens == 100
        assert t2.output_tokens == 50
        assert t2.tools_called == ["calculator"]
        assert t2.tool_latencies_s == {"calculator": 0.5}
        assert t2.wall_clock_s == pytest.approx(1.2)
        assert t2.gpu_energy_joules == pytest.approx(10.0)
        assert t2.cost_usd == pytest.approx(0.001)

    def test_from_dict_missing_keys(self):
        d = {"turn_index": 0}
        t = TurnTrace.from_dict(d)
        assert t.input_tokens == 0
        assert t.tools_called == []
        assert t.error is None


class TestQueryTrace:
    def _make_trace(self, **kwargs):
        defaults = {
            "query_id": "q0001",
            "workload_type": "coding",
            "query_text": "Hello",
            "response_text": "World",
            "turns": [
                TurnTrace(
                    turn_index=0,
                    input_tokens=100,
                    output_tokens=50,
                    wall_clock_s=1.0,
                    gpu_energy_joules=5.0,
                    cost_usd=0.01,
                ),
                TurnTrace(
                    turn_index=1,
                    input_tokens=150,
                    output_tokens=75,
                    wall_clock_s=1.5,
                    gpu_energy_joules=7.5,
                    cost_usd=0.015,
                ),
            ],
            "total_wall_clock_s": 2.5,
            "completed": True,
        }
        defaults.update(kwargs)
        return QueryTrace(**defaults)

    def test_num_turns(self):
        t = self._make_trace()
        assert t.num_turns == 2

    def test_total_tokens(self):
        t = self._make_trace()
        assert t.total_input_tokens == 250
        assert t.total_output_tokens == 125
        assert t.total_tokens == 375

    def test_total_gpu_energy(self):
        t = self._make_trace()
        assert t.total_gpu_energy_joules == pytest.approx(12.5)

    def test_total_gpu_energy_fallback(self):
        t = self._make_trace(
            turns=[TurnTrace(turn_index=0)],
            query_gpu_energy_joules=20.0,
        )
        assert t.total_gpu_energy_joules == pytest.approx(20.0)

    def test_total_cost(self):
        t = self._make_trace()
        assert t.total_cost_usd == pytest.approx(0.025)

    def test_total_cost_none(self):
        t = self._make_trace(turns=[TurnTrace(turn_index=0)])
        assert t.total_cost_usd is None

    def test_throughput(self):
        t = self._make_trace()
        assert t.throughput_tokens_per_sec == pytest.approx(125 / 2.5)

    def test_energy_per_token(self):
        t = self._make_trace()
        assert t.energy_per_token_joules == pytest.approx(12.5 / 125)

    def test_avg_gpu_power(self):
        t = self._make_trace()
        # No per-turn power set, so falls back to query-level
        assert t.avg_gpu_power_watts is None

    def test_to_dict_roundtrip(self):
        t = self._make_trace(is_resolved=True)
        d = t.to_dict()
        t2 = QueryTrace.from_dict(d)
        assert t2.query_id == "q0001"
        assert t2.workload_type == "coding"
        assert t2.num_turns == 2
        assert t2.completed is True
        assert t2.is_resolved is True
        assert t2.total_input_tokens == 250

    def test_save_load_jsonl(self, tmp_path):
        t1 = self._make_trace(query_id="q0001")
        t2 = self._make_trace(query_id="q0002")
        path = tmp_path / "traces.jsonl"
        t1.save_jsonl(path)
        t2.save_jsonl(path)
        loaded = QueryTrace.load_jsonl(path)
        assert len(loaded) == 2
        assert loaded[0].query_id == "q0001"
        assert loaded[1].query_id == "q0002"

    def test_tool_call_count(self):
        t = self._make_trace(
            turns=[
                TurnTrace(turn_index=0, tools_called=["calc", "search"]),
                TurnTrace(turn_index=1, tools_called=["read"]),
            ]
        )
        assert t.total_tool_calls == 3
