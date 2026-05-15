"""Tests for mining/_discovery.py — capability detection matrix."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_detect_supported_on_h100(hopper_hw):
    from openjarvis.mining._discovery import detect_for_engine_model

    cap = detect_for_engine_model(
        hw=hopper_hw,
        engine_id="vllm",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
        provider_id="vllm-pearl",
    )
    assert cap.supported is True
    assert cap.reason is None


def test_detect_unsupported_on_ada_4090(ada_hw):
    from openjarvis.mining._discovery import detect_for_engine_model

    cap = detect_for_engine_model(
        hw=ada_hw,
        engine_id="vllm",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert "sm90" in cap.reason.lower() or "compute_capability" in cap.reason.lower()


def test_detect_unsupported_on_apple_engine(apple_hw):
    """Engine check rejects mlx before reaching the GPU vendor branch."""
    from openjarvis.mining._discovery import detect_for_engine_model

    cap = detect_for_engine_model(
        hw=apple_hw,
        engine_id="mlx",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert "mlx" in cap.reason.lower() or "engine" in cap.reason.lower()


def test_detect_unsupported_on_apple_gpu_vendor(apple_hw):
    """Apple Silicon GPU is rejected by the vendor branch (Spec B territory)."""
    from openjarvis.mining._discovery import detect_for_engine_model

    cap = detect_for_engine_model(
        hw=apple_hw,
        engine_id="vllm",  # bypass the engine check
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert "nvidia" in cap.reason.lower() or "hopper" in cap.reason.lower()


def test_detect_unsupported_for_non_vllm_engine(hopper_hw):
    from openjarvis.mining._discovery import detect_for_engine_model

    cap = detect_for_engine_model(
        hw=hopper_hw,
        engine_id="ollama",
        model="qwen3:8b",
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert "vllm" in cap.reason.lower() or "engine" in cap.reason.lower()


def test_detect_unsupported_for_non_pearl_model(hopper_hw):
    from openjarvis.mining._discovery import detect_for_engine_model

    cap = detect_for_engine_model(
        hw=hopper_hw,
        engine_id="vllm",
        model="meta-llama/Llama-3.3-70B-Instruct",  # NOT the -pearl variant
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert "pearl" in cap.reason.lower()


def test_detect_raw_planned_model_points_to_pearl_variant(hopper_hw):
    from openjarvis.mining._discovery import detect_for_engine_model

    cap = detect_for_engine_model(
        hw=hopper_hw,
        engine_id="vllm",
        model="google/gemma-4-31B-it",
        provider_id="vllm-pearl",
    )

    assert cap.supported is False
    assert "pearl-ai/Gemma-4-31B-it-pearl" in cap.reason


def test_detect_planned_pearl_model_is_not_enabled_yet(hopper_hw):
    from openjarvis.mining._discovery import detect_for_engine_model

    cap = detect_for_engine_model(
        hw=hopper_hw,
        engine_id="vllm",
        model="pearl-ai/Gemma-4-31B-it-pearl",
        provider_id="vllm-pearl",
    )

    assert cap.supported is False
    assert "planned" in cap.reason
    assert "validation" in cap.reason


def test_detect_unsupported_for_low_vram():
    from openjarvis.core.config import GpuInfo, HardwareInfo
    from openjarvis.mining._discovery import detect_for_engine_model

    hw = HardwareInfo(
        platform="linux",
        gpu=GpuInfo(
            vendor="nvidia",
            name="NVIDIA H100 PCIe-40GB",
            vram_gb=40.0,  # below 70 GB threshold
            compute_capability="9.0",
            count=1,
        ),
    )
    cap = detect_for_engine_model(
        hw=hw,
        engine_id="vllm",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert "vram" in cap.reason.lower() or "memory" in cap.reason.lower()


def test_check_docker_available_true():
    from openjarvis.mining._discovery import check_docker_available

    with patch("openjarvis.mining._discovery._docker_client") as fake:
        fake.return_value.ping.return_value = True
        fake.return_value.version.return_value = {"Version": "24.0.7"}
        ok, info = check_docker_available()
        assert ok is True
        assert "24.0.7" in info


def test_check_docker_available_false_when_daemon_down():
    from openjarvis.mining._discovery import check_docker_available

    with patch("openjarvis.mining._discovery._docker_client") as fake:
        fake.side_effect = Exception("Cannot connect to the Docker daemon")
        ok, info = check_docker_available()
        assert ok is False
        assert "daemon" in info.lower() or "connect" in info.lower()


def test_check_docker_available_false_when_sdk_missing():
    from openjarvis.mining._discovery import check_docker_available

    with patch("openjarvis.mining._discovery._docker_client") as fake:
        fake.side_effect = RuntimeError(
            "Docker SDK not installed; install with `uv sync --extra mining-pearl-vllm`"
        )
        ok, info = check_docker_available()
        assert ok is False
        assert "mining-pearl-vllm" in info


def test_check_disk_free_passes(tmp_path):
    from openjarvis.mining._discovery import check_disk_free

    with patch("openjarvis.mining._discovery.shutil.disk_usage") as du:
        # 500 GB free
        du.return_value = MagicMock(
            total=1_000_000_000_000,
            used=500_000_000_000,
            free=500_000_000_000,
        )
        ok, info = check_disk_free(tmp_path)
        assert ok is True


def test_check_disk_free_fails_below_threshold(tmp_path):
    from openjarvis.mining._discovery import check_disk_free

    with patch("openjarvis.mining._discovery.shutil.disk_usage") as du:
        du.return_value = MagicMock(
            total=1_000_000_000_000,
            used=950_000_000_000,
            free=50_000_000_000,
        )
        ok, info = check_disk_free(tmp_path)
        assert ok is False


def test_check_pearld_reachable_true():
    from openjarvis.mining._discovery import check_pearld_reachable

    with patch("openjarvis.mining._discovery.httpx.post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            "result": {"blocks": 442107, "headers": 442107}
        }
        ok, info = check_pearld_reachable("http://localhost:44107", "user", "pass")
        assert ok is True
        assert "442107" in info


def test_check_pearld_reachable_false_on_connection_error():
    import httpx

    from openjarvis.mining._discovery import check_pearld_reachable

    with patch("openjarvis.mining._discovery.httpx.post") as post:
        post.side_effect = httpx.ConnectError("connection refused")
        ok, info = check_pearld_reachable("http://localhost:44107", "user", "pass")
        assert ok is False


def test_check_wallet_address_format_valid():
    from openjarvis.mining._discovery import check_wallet_address_format

    ok, info = check_wallet_address_format("prl1qexampleaddress0123456789")
    assert ok is True


def test_check_wallet_address_format_valid_prl1p():
    from openjarvis.mining._discovery import check_wallet_address_format

    ok, info = check_wallet_address_format(
        "prl1pkf5s56dgm6jpg4z9z9qv5wua4jgs3h8q98rfh3gsqxp60eagmruqdnr3dp"
    )
    assert ok is True


def test_check_wallet_address_format_invalid():
    from openjarvis.mining._discovery import check_wallet_address_format

    ok, info = check_wallet_address_format("not-a-pearl-address")
    assert ok is False
