"""Tests for the ``jarvis mine`` CLI."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.mining import Sidecar


def test_mine_help() -> None:
    result = CliRunner().invoke(cli, ["mine", "--help"])

    assert result.exit_code == 0
    assert "Configure and run Pearl mining" in result.output
    assert "init" in result.output
    assert "start" in result.output
    assert "doctor" in result.output


def test_mine_models_lists_validated_and_planned_models() -> None:
    result = CliRunner().invoke(cli, ["mine", "models"])

    assert result.exit_code == 0
    assert "Pearl Mining Models" in result.output
    assert "pearl-ai/Llama-3.3-70B-Instruct-pearl" in result.output
    assert "pearl-ai/Qwen3.5-9B-pearl" in result.output
    assert "validated" in result.output
    assert "planned" in result.output


def test_mine_inspect_model_validated_artifact_passes(monkeypatch) -> None:
    model = "pearl-ai/Llama-3.3-70B-Instruct-pearl"

    def fake_hf_json(path: str, *, token: str = "", timeout: float = 10.0):
        if path.endswith("/tree/main?recursive=false"):
            return [
                {"path": "config.json"},
                {"path": "tokenizer.json"},
                {"path": "model.safetensors"},
            ]
        return {
            "config": {
                "architectures": ["LlamaForCausalLM"],
                "quantization_config": {"quant_method": "pearl"},
            }
        }

    monkeypatch.setattr("openjarvis.cli.mine_cmd._hf_json", fake_hf_json)

    result = CliRunner().invoke(cli, ["mine", "inspect-model", "--model", model])

    assert result.exit_code == 0
    assert "Artifact inspection passed" in result.output
    assert "Pearl quantization" in result.output


def test_mine_inspect_model_gemma4_requires_processor_metadata(monkeypatch) -> None:
    model = "pearl-ai/Gemma-4-31B-it-pearl"

    def fake_hf_json(path: str, *, token: str = "", timeout: float = 10.0):
        if path.endswith("/tree/main?recursive=false"):
            return [
                {"path": "config.json"},
                {"path": "processor_config.json"},
                {"path": "tokenizer.json"},
                {"path": "model.safetensors"},
            ]
        return {
            "config": {
                "architectures": ["Gemma4ForConditionalGeneration"],
                "quantization_config": {"quant_method": "pearl"},
            }
        }

    monkeypatch.setattr("openjarvis.cli.mine_cmd._hf_json", fake_hf_json)

    result = CliRunner().invoke(
        cli,
        ["mine", "inspect-model", "--model", model, "--allow-planned"],
    )

    assert result.exit_code != 0
    assert "Gemma4 processor metadata" in result.output
    assert "missing preprocessor_config.json" in result.output


def test_mine_inspect_model_accepts_local_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "qwen-pearl"
    artifact.mkdir()
    (artifact / "config.json").write_text(
        json.dumps(
            {
                "architectures": ["Qwen3_5ForConditionalGeneration"],
                "quantization_config": {"quant_method": "pearl"},
            }
        )
    )
    (artifact / "tokenizer.json").write_text("{}")
    (artifact / "model.safetensors").write_text("placeholder")

    result = CliRunner().invoke(
        cli,
        ["mine", "inspect-model", "--model", str(artifact)],
    )

    assert result.exit_code == 0
    assert "local artifact" in result.output
    assert "Artifact inspection passed" in result.output


def test_mine_init_writes_mining_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    result = CliRunner().invoke(
        cli,
        [
            "mine",
            "init",
            "--provider",
            "cpu-pearl",
            "--wallet-address",
            "prl1qtestingaddr",
            "--pearld-rpc-url",
            "http://127.0.0.1:44107",
            "--pearld-rpc-user",
            "rpcuser",
            "--pearld-rpc-password-env",
            "TEST_PEARLD_PASSWORD",
        ],
        env={"OPENJARVIS_CONFIG": str(config_path)},
    )

    assert result.exit_code == 0
    content = config_path.read_text()
    assert "[mining]" in content
    assert 'provider = "cpu-pearl"' in content
    assert 'wallet_address = "prl1qtestingaddr"' in content
    assert 'pearld_rpc_password_env = "TEST_PEARLD_PASSWORD"' in content


def test_mine_init_writes_cuda_visible_devices_for_vllm(
    tmp_path: Path,
) -> None:
    from openjarvis.mining._stubs import MiningCapabilities

    config_path = tmp_path / "config.toml"

    with (
        patch("openjarvis.cli.mine_cmd._detect_hardware"),
        patch(
            "openjarvis.cli.mine_cmd.detect_for_engine_model",
            return_value=MiningCapabilities(supported=True),
        ),
        patch(
            "openjarvis.cli.mine_cmd.check_docker_available",
            return_value=(True, ""),
        ),
        patch("openjarvis.cli.mine_cmd.check_disk_free", return_value=(True, "")),
        patch("openjarvis.cli.mine_cmd._docker_from_env", return_value=MagicMock()),
        patch(
            "openjarvis.cli.mine_cmd.PearlDockerLauncher.ensure_image",
            return_value="openjarvis/pearl-miner:master",
        ),
    ):
        result = CliRunner().invoke(
            cli,
            [
                "mine",
                "init",
                "--provider",
                "vllm-pearl",
                "--wallet-address",
                "prl1qtestingaddr",
                "--pearld-rpc-url",
                "http://127.0.0.1:44107",
                "--pearld-rpc-user",
                "rpcuser",
                "--pearld-rpc-password-env",
                "TEST_PEARLD_PASSWORD",
                "--cuda-visible-devices",
                "0,1",
            ],
            env={"OPENJARVIS_CONFIG": str(config_path)},
        )

    assert result.exit_code == 0
    content = config_path.read_text()
    assert 'provider = "vllm-pearl"' in content
    assert 'cuda_visible_devices = "0,1"' in content


def test_mine_init_writes_local_model_path_for_vllm(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    local_model = tmp_path / "converted-qwen"
    local_model.mkdir()

    with (
        patch("openjarvis.cli.mine_cmd._detect_hardware"),
        patch(
            "openjarvis.cli.mine_cmd.check_docker_available",
            return_value=(True, ""),
        ),
        patch("openjarvis.cli.mine_cmd.check_disk_free", return_value=(True, "")),
        patch("openjarvis.cli.mine_cmd._docker_from_env", return_value=MagicMock()),
        patch(
            "openjarvis.cli.mine_cmd.PearlDockerLauncher.ensure_image",
            return_value="openjarvis/pearl-miner:master",
        ),
    ):
        result = CliRunner().invoke(
            cli,
            [
                "mine",
                "init",
                "--provider",
                "vllm-pearl",
                "--wallet-address",
                "prl1qtestingaddr",
                "--pearld-rpc-url",
                "http://127.0.0.1:44107",
                "--pearld-rpc-user",
                "rpcuser",
                "--pearld-rpc-password-env",
                "TEST_PEARLD_PASSWORD",
                "--model",
                "pearl-ai/Qwen3.5-9B-pearl",
                "--local-model-path",
                str(local_model),
                "--vllm-arg=--language-model-only",
                "--vllm-arg=--skip-mm-profiling",
            ],
            env={"OPENJARVIS_CONFIG": str(config_path)},
        )

    assert result.exit_code == 0
    content = config_path.read_text()
    assert 'model = "pearl-ai/Qwen3.5-9B-pearl"' in content
    assert f'local_model_path = "{local_model.resolve()}"' in content
    assert 'vllm_args = ["--language-model-only", "--skip-mm-profiling"]' in content


def test_mine_start_uses_configured_provider(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[mining]
provider = "cpu-pearl"
wallet_address = "prl1qtest"
submit_target = "solo"

[mining.extra]
pearld_rpc_url = "http://127.0.0.1:44107"
pearld_rpc_user = "rpcuser"
pearld_rpc_password_env = "TEST_PEARLD_PASSWORD"
gateway_host = "127.0.0.1"
gateway_port = 18337
metrics_port = 19109
"""
    )
    sidecar_path = tmp_path / "mining.json"
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", sidecar_path)

    started_configs = []

    async def fake_start(config):
        started_configs.append(config)

    fake_provider = MagicMock()
    provider_cls = MagicMock(return_value=fake_provider)
    fake_provider.start = fake_start

    with patch("openjarvis.cli.mine_cmd._provider_ids", return_value=("cpu-pearl",)):
        with patch("openjarvis.cli.mine_cmd.MinerRegistry.contains", return_value=True):
            with patch(
                "openjarvis.cli.mine_cmd.MinerRegistry.get",
                return_value=provider_cls,
            ):
                result = CliRunner().invoke(
                    cli,
                    ["mine", "start"],
                    env={
                        "OPENJARVIS_CONFIG": str(config_path),
                        "TEST_PEARLD_PASSWORD": "secret",
                    },
                )

    assert result.exit_code == 0
    assert "Started" in result.output
    provider_cls.assert_called_once_with()
    assert started_configs[0].provider == "cpu-pearl"


def test_mine_status_reports_sidecar_and_metrics(tmp_path: Path, monkeypatch) -> None:
    sidecar_path = tmp_path / "mining.json"
    Sidecar.write(
        sidecar_path,
        {
            "provider": "cpu-pearl",
            "wallet_address": "prl1qtest",
            "gateway_url": "http://127.0.0.1:8337",
            "metrics_url": "http://127.0.0.1:9109/metrics",
            "gateway_pid": 111,
            "miner_loop_pid": 222,
        },
    )
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", sidecar_path)
    monkeypatch.setattr("openjarvis.cli.mine_cmd._pid_alive", lambda pid: True)

    stats = MagicMock()
    stats.shares_submitted = 3
    stats.shares_accepted = 2
    stats.blocks_found = 1
    monkeypatch.setattr(
        "openjarvis.cli.mine_cmd._stats_from_metrics_url",
        lambda url, provider_id: (stats, None),
    )

    result = CliRunner().invoke(cli, ["mine", "status"])

    assert result.exit_code == 0
    assert "cpu-pearl" in result.output
    assert "Shares submitted" in result.output
    assert "3" in result.output


def test_mine_stop_terminates_pids_and_removes_sidecar(
    tmp_path: Path, monkeypatch
) -> None:
    sidecar_path = tmp_path / "mining.json"
    Sidecar.write(
        sidecar_path,
        {
            "provider": "cpu-pearl",
            "gateway_pid": 111,
            "miner_loop_pid": 222,
        },
    )
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", sidecar_path)
    terminated: list[int] = []

    def fake_terminate(pid, *, grace_seconds):
        terminated.append(pid)

    monkeypatch.setattr("openjarvis.cli.mine_cmd._terminate_pid", fake_terminate)

    result = CliRunner().invoke(cli, ["mine", "stop"])

    assert result.exit_code == 0
    assert sorted(terminated) == [111, 222]
    assert not sidecar_path.exists()


def test_mine_doctor_without_config(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "missing.toml"
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", tmp_path / "none.json")

    with patch("openjarvis.cli.mine_cmd._provider_ids", return_value=()):
        result = CliRunner().invoke(
            cli,
            ["mine", "doctor"],
            env={"OPENJARVIS_CONFIG": str(config_path)},
        )

    assert result.exit_code == 0
    assert "Pearl Mining Doctor" in result.output
    assert "jarvis mine init" in result.output


def test_mine_status_no_session(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", tmp_path / "none.json")

    result = CliRunner().invoke(cli, ["mine", "status"])

    assert result.exit_code == 0
    assert "No active mining session" in result.output


def test_mine_validate_model_blocks_planned_without_allow(
    tmp_path: Path, monkeypatch
) -> None:
    sidecar_path = tmp_path / "mining.json"
    model = "pearl-ai/Qwen3.5-9B-pearl"
    Sidecar.write(
        sidecar_path,
        {
            "provider": "vllm-pearl",
            "model": model,
            "vllm_endpoint": "http://127.0.0.1:8000/v1",
            "gateway_metrics_url": "http://127.0.0.1:8339",
        },
    )
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", sidecar_path)
    monkeypatch.setattr(
        "openjarvis.cli.mine_cmd._get_json",
        lambda url, *, timeout: {"data": [{"id": model}]},
    )
    stats = MagicMock()
    stats.shares_submitted = 1
    stats.shares_accepted = 1
    monkeypatch.setattr(
        "openjarvis.cli.mine_cmd._stats_from_metrics_url",
        lambda url, provider_id: (stats, None),
    )

    result = CliRunner().invoke(cli, ["mine", "validate-model"])

    assert result.exit_code != 0
    assert "planned" in result.output
    assert "validation checks failed" in result.output.lower()


def test_mine_validate_model_allows_planned_with_runtime_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    sidecar_path = tmp_path / "mining.json"
    model = "pearl-ai/Qwen3.5-9B-pearl"
    Sidecar.write(
        sidecar_path,
        {
            "provider": "vllm-pearl",
            "model": model,
            "vllm_endpoint": "http://127.0.0.1:8000/v1",
            "gateway_metrics_url": "http://127.0.0.1:8339",
        },
    )
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", sidecar_path)
    monkeypatch.setattr(
        "openjarvis.cli.mine_cmd._get_json",
        lambda url, *, timeout: {"data": [{"id": model}]},
    )
    monkeypatch.setattr(
        "openjarvis.cli.mine_cmd._post_json",
        lambda url, payload, *, timeout: {"choices": [{"message": {"content": "ok"}}]},
    )
    stats = MagicMock()
    stats.shares_submitted = 2
    stats.shares_accepted = 1
    monkeypatch.setattr(
        "openjarvis.cli.mine_cmd._stats_from_metrics_url",
        lambda url, provider_id: (stats, None),
    )

    result = CliRunner().invoke(
        cli,
        [
            "mine",
            "validate-model",
            "--allow-planned",
            "--prompt",
            "hello",
        ],
    )

    assert result.exit_code == 0
    assert "Validation checks passed" in result.output
    assert "Chat completion" in result.output
    assert "submitted=2 accepted=1" in result.output


def test_mine_validate_model_writes_json_artifact(tmp_path: Path, monkeypatch) -> None:
    sidecar_path = tmp_path / "mining.json"
    output_path = tmp_path / "artifacts" / "qwen-validation.json"
    model = "pearl-ai/Qwen3.5-9B-pearl"
    Sidecar.write(
        sidecar_path,
        {
            "provider": "vllm-pearl",
            "model": model,
            "vllm_endpoint": "http://127.0.0.1:8000/v1",
            "gateway_metrics_url": "http://127.0.0.1:8339",
        },
    )
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", sidecar_path)
    monkeypatch.setattr(
        "openjarvis.cli.mine_cmd._get_json",
        lambda url, *, timeout: {"data": [{"id": model}]},
    )
    stats = MagicMock()
    stats.shares_submitted = 2
    stats.shares_accepted = 1
    monkeypatch.setattr(
        "openjarvis.cli.mine_cmd._stats_from_metrics_url",
        lambda url, provider_id: (stats, None),
    )

    result = CliRunner().invoke(
        cli,
        [
            "mine",
            "validate-model",
            "--allow-planned",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output_path.read_text())
    assert payload["schema_version"] == 1
    assert payload["model"] == model
    assert payload["status"] == "passed"
    assert payload["prompt_ran"] is False
    assert {check["name"] for check in payload["checks"]} >= {
        "Model registry",
        "Sidecar",
        "vLLM /models",
        "Gateway metrics",
    }


def test_mine_validate_model_falls_back_to_vllm_metrics(
    tmp_path: Path, monkeypatch
) -> None:
    sidecar_path = tmp_path / "mining.json"
    model = "pearl-ai/Llama-3.3-70B-Instruct-pearl"
    Sidecar.write(
        sidecar_path,
        {
            "provider": "vllm-pearl",
            "model": model,
            "vllm_endpoint": "http://127.0.0.1:8000/v1",
            "gateway_metrics_url": "http://127.0.0.1:8339",
        },
    )
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", sidecar_path)
    monkeypatch.setattr(
        "openjarvis.cli.mine_cmd._get_json",
        lambda url, *, timeout: {"data": [{"id": model}]},
    )
    stats = MagicMock()
    stats.shares_submitted = 0
    stats.shares_accepted = 0

    def fake_stats(url, provider_id):
        if url == "http://127.0.0.1:8339/metrics":
            return None, "connection refused"
        return stats, None

    monkeypatch.setattr("openjarvis.cli.mine_cmd._stats_from_metrics_url", fake_stats)

    result = CliRunner().invoke(cli, ["mine", "validate-model"])

    assert result.exit_code == 0
    assert "vLLM submitted=0 accepted=0" in result.output
