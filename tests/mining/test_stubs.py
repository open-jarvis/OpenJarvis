"""Tests for mining/_stubs.py — ABC contract, dataclass invariants, sidecar IO."""

from __future__ import annotations

import json

import pytest


def test_mining_capabilities_default_unsupported():
    from openjarvis.mining._stubs import MiningCapabilities

    cap = MiningCapabilities(supported=False, reason="needs sm90")
    assert cap.supported is False
    assert cap.reason == "needs sm90"
    assert cap.estimated_hashrate is None


def test_solo_target_dataclass():
    from openjarvis.mining._stubs import SoloTarget

    t = SoloTarget(pearld_rpc_url="http://localhost:44107")
    assert t.pearld_rpc_url == "http://localhost:44107"


def test_pool_target_dataclass():
    from openjarvis.mining._stubs import PoolTarget

    t = PoolTarget(url="https://pool.example/submit", worker_id="rig01")
    assert t.url == "https://pool.example/submit"
    assert t.worker_id == "rig01"


def test_mining_config_v1_defaults():
    from openjarvis.mining._stubs import MiningConfig, SoloTarget

    cfg = MiningConfig(
        provider="vllm-pearl",
        wallet_address="prl1qexample",
        submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
    )
    assert cfg.fee_bps == 0
    assert cfg.fee_payout_address is None
    assert cfg.extra == {}


def test_mining_stats_v1_defaults():
    from openjarvis.mining._stubs import MiningStats

    s = MiningStats(provider_id="vllm-pearl")
    assert s.shares_submitted == 0
    assert s.shares_accepted == 0
    assert s.fees_owed == 0
    assert s.payout_target == "solo"


def test_mining_provider_is_abstract():
    from openjarvis.mining._stubs import MiningProvider

    with pytest.raises(TypeError):
        MiningProvider()  # cannot instantiate ABC


def test_sidecar_write_then_read_roundtrip(sidecar_path, sample_sidecar_payload):
    from openjarvis.mining._stubs import Sidecar

    Sidecar.write(sidecar_path, sample_sidecar_payload)
    payload = Sidecar.read(sidecar_path)
    assert payload == sample_sidecar_payload


def test_sidecar_read_missing_returns_none(sidecar_path):
    from openjarvis.mining._stubs import Sidecar

    assert Sidecar.read(sidecar_path) is None


def test_sidecar_remove_is_idempotent(sidecar_path):
    from openjarvis.mining._stubs import Sidecar

    Sidecar.remove(sidecar_path)  # missing file — should not raise
    sidecar_path.write_text(json.dumps({"x": 1}))
    Sidecar.remove(sidecar_path)
    assert not sidecar_path.exists()
