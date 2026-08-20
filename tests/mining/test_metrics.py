"""Tests for mining/_metrics.py — Prometheus → MiningStats adapter."""

from __future__ import annotations

from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "gateway_metrics_sample.txt"


def test_parse_gateway_metrics_full():
    from openjarvis.mining._metrics import parse_gateway_metrics

    text = FIXTURE.read_text()
    stats = parse_gateway_metrics(text, provider_id="vllm-pearl")
    assert stats.provider_id == "vllm-pearl"
    assert stats.shares_submitted == 12345
    assert stats.shares_accepted == 12300
    assert stats.blocks_found == 7
    assert stats.last_share_at == 1714867500.0
    # Uptime computed as now - process_start_time, but not asserted exactly.
    assert stats.uptime_seconds >= 0


def test_parse_gateway_metrics_missing_metrics_zero_fills():
    from openjarvis.mining._metrics import parse_gateway_metrics

    stats = parse_gateway_metrics("# empty exposition\n", provider_id="vllm-pearl")
    assert stats.shares_submitted == 0
    assert stats.shares_accepted == 0
    assert stats.blocks_found == 0
    assert stats.last_share_at is None


def test_parse_gateway_metrics_ignores_comment_lines():
    from openjarvis.mining._metrics import parse_gateway_metrics

    stats = parse_gateway_metrics(
        "# HELP something\n# TYPE something counter\nsomething 99\n",
        provider_id="vllm-pearl",
    )
    assert stats.shares_submitted == 0  # 'something' isn't a Pearl metric


def test_parse_vllm_metrics_reports_runtime_uptime():
    from openjarvis.mining._metrics import parse_vllm_metrics

    stats = parse_vllm_metrics(
        "process_start_time_seconds 1\n"
        'vllm:request_success_total{finished_reason="stop"} 1\n',
        provider_id="vllm-pearl",
    )
    assert stats.provider_id == "vllm-pearl"
    assert stats.uptime_seconds > 0
    assert stats.last_error is None
