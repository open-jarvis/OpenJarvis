"""``jarvis mine`` command group."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import click

from openjarvis.core.config import HardwareInfo, detect_hardware, load_config
from openjarvis.core.registry import MinerRegistry
from openjarvis.mining._constants import (
    DEFAULT_GATEWAY_METRICS_PORT,
    DEFAULT_GATEWAY_RPC_PORT,
    DEFAULT_PEARL_MODEL,
    DEFAULT_PEARLD_RPC_URL,
    PEARL_IMAGE_TAG,
    SIDECAR_PATH,
)
from openjarvis.mining._discovery import (
    check_disk_free,
    check_docker_available,
    check_pearld_reachable,
    check_wallet_address_format,
    detect_for_engine_model,
)
from openjarvis.mining._docker import PearlDockerLauncher
from openjarvis.mining._metrics import parse_gateway_metrics
from openjarvis.mining._models import (
    get_pearl_model_spec,
    iter_pearl_model_specs,
    pearl_variant_for_base_model,
)
from openjarvis.mining._stubs import Sidecar
from openjarvis.mining.vllm_pearl import ensure_registered as ensure_vllm_registered


def _detect_hardware() -> HardwareInfo:
    """Wrapper to make hardware detection mockable in CLI tests."""
    return detect_hardware()


def _docker_from_env():
    """Wrapper to make Docker client creation mockable in CLI tests."""
    import docker

    return docker.from_env()


def _ensure_providers_registered() -> None:
    ensure_vllm_registered()
    from openjarvis.mining.cpu_pearl import ensure_registered as ensure_cpu_registered

    ensure_cpu_registered()
    try:
        from openjarvis.mining.apple_mps_pearl import (
            ensure_registered as ensure_mps_registered,
        )

        ensure_mps_registered()
    except ImportError:
        pass


def _provider_ids() -> tuple[str, ...]:
    _ensure_providers_registered()
    return tuple(MinerRegistry.keys())


def _select_provider(provider: str) -> str:
    if provider != "auto":
        return provider
    hw = _detect_hardware()
    gpu_vendor = hw.gpu.vendor.lower() if hw.gpu else ""
    if hw.platform == "darwin" and gpu_vendor == "apple":
        return "apple-mps-pearl"
    if hw.platform == "linux" and gpu_vendor == "nvidia":
        return "vllm-pearl"
    return "cpu-pearl"


def _stats_from_metrics_url(
    metrics_url: str,
    provider_id: str,
) -> tuple[Any | None, str | None]:
    try:
        with urllib.request.urlopen(metrics_url, timeout=2.0) as resp:
            text = resp.read().decode()
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)
    return parse_gateway_metrics(text, provider_id=provider_id), None


def _get_json(url: str, *, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _post_json(url: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _hf_json(
    path: str,
    *,
    token: str = "",
    timeout: float = 10.0,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Fetch JSON from the Hugging Face API with an optional token."""

    request = urllib.request.Request(f"https://huggingface.co{path}")
    if token:
        request.add_header("authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _extract_model_ids(models_payload: dict[str, Any]) -> set[str]:
    data = models_payload.get("data", [])
    ids: set[str] = set()
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                ids.add(item["id"])
            elif isinstance(item, str):
                ids.add(item)
    return ids


def _hf_model_path(model_id: str, suffix: str) -> str:
    encoded = urllib.parse.quote(model_id, safe="/")
    return f"/api/models/{encoded}{suffix}"


def _artifact_file_paths(tree_payload: Any) -> set[str]:
    paths: set[str] = set()
    if isinstance(tree_payload, list):
        for item in tree_payload:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                paths.add(item["path"])
    return paths


def _artifact_has_weights(paths: set[str]) -> bool:
    return any(
        path.endswith(".safetensors") or path.endswith(".bin") or path.endswith(".gguf")
        for path in paths
    )


def _artifact_quant_method(model_payload: Any) -> str:
    if not isinstance(model_payload, dict):
        return ""
    config = model_payload.get("config")
    if not isinstance(config, dict):
        return ""
    quant_config = config.get("quantization_config")
    if not isinstance(quant_config, dict):
        return ""
    return str(quant_config.get("quant_method") or "")


def _artifact_architectures(model_payload: Any) -> list[str]:
    if not isinstance(model_payload, dict):
        return []
    config = model_payload.get("config")
    if not isinstance(config, dict):
        return []
    architectures = config.get("architectures")
    if not isinstance(architectures, list):
        return []
    return [str(item) for item in architectures if isinstance(item, str)]


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _terminate_pid(pid: int | None, *, grace_seconds: float = 3.0) -> None:
    if not pid or not _pid_alive(pid):
        return
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.05)
    if _pid_alive(pid):
        os.kill(pid, signal.SIGKILL)


def _row(name: str, ok: bool, info: str) -> None:
    marker = "OK" if ok else "FAIL"
    click.echo(f"  {name:<22} {info:<45} {marker}")


def _validation_row(results: list[bool], name: str, ok: bool, info: str) -> None:
    results.append(ok)
    _row(name, ok, info)


@click.group()
def mine() -> None:
    """Configure and run Pearl mining."""


@mine.command("models")
def models() -> None:
    """List Pearl model support status."""
    click.echo("Pearl Mining Models")
    click.echo(
        f"{'Status':<10} {'Model':<42} {'Base model':<28} {'VRAM':<8} {'Context':<8}"
    )
    for spec in iter_pearl_model_specs():
        click.echo(
            f"{spec.status:<10} {spec.model_id:<42} {spec.base_model_id:<28} "
            f"{spec.min_vram_gb:.0f} GB   {spec.default_max_model_len:<8}"
        )
        if spec.notes:
            click.echo(f"  {spec.notes}")


@mine.command()
def doctor() -> None:
    """Diagnose mining capability with one row per check."""
    _ensure_providers_registered()
    hw = _detect_hardware()
    load_config.cache_clear()
    cfg = load_config()
    mining_cfg = cfg.mining

    click.echo("Pearl Mining Doctor")
    click.echo("Hardware")
    gpu = hw.gpu
    _row(
        "GPU vendor",
        bool(gpu and gpu.vendor == "nvidia"),
        gpu.vendor if gpu else "none",
    )
    compute_capability = gpu.compute_capability if gpu else "n/a"
    _row(
        "Compute capability",
        bool(gpu and compute_capability.startswith("9.0")),
        compute_capability,
    )
    vram_gb = gpu.vram_gb if gpu else 0.0
    _row("VRAM", vram_gb >= 70.0, f"{vram_gb:.0f} GB")

    click.echo("Docker")
    ok, info = check_docker_available()
    _row("Daemon", ok, info)

    click.echo("Disk")
    ok, info = check_disk_free(Path.home())
    _row("Free space", ok, info)

    click.echo("Pearl node")
    if mining_cfg is None:
        _row("RPC", False, "no [mining] config - run `jarvis mine init`")
    else:
        url = mining_cfg.extra.get("pearld_rpc_url", DEFAULT_PEARLD_RPC_URL)
        user = mining_cfg.extra.get("pearld_rpc_user", "rpcuser")
        password_env = mining_cfg.extra.get(
            "pearld_rpc_password_env",
            "PEARLD_RPC_PASSWORD",
        )
        ok, info = check_pearld_reachable(url, user, os.environ.get(password_env, ""))
        _row("RPC", ok, info)

    click.echo("Wallet")
    if mining_cfg is None:
        _row("Address format", False, "no [mining] config")
    else:
        ok, info = check_wallet_address_format(mining_cfg.wallet_address)
        _row("Address format", ok, info)

    click.echo("Provider capability")
    engine_id = "vllm"
    model = DEFAULT_PEARL_MODEL
    configured_provider = None
    if mining_cfg is not None:
        model = mining_cfg.extra.get("model", DEFAULT_PEARL_MODEL)
        configured_provider = mining_cfg.provider
    spec = get_pearl_model_spec(model)
    if spec is None:
        planned = pearl_variant_for_base_model(model)
        info = f"raw model; planned Pearl variant {planned}" if planned else "unknown"
        _row("Model registry", False, info)
    else:
        _row("Model registry", spec.is_validated, f"{spec.status}: {spec.model_id}")

    for provider_id, provider_cls in MinerRegistry.items():
        cap = provider_cls.detect(hw, engine_id, model)
        suffix = " (configured)" if provider_id == configured_provider else ""
        if cap.supported:
            click.echo(f"  {provider_id:<22} SUPPORTED{suffix}")
        else:
            reason = cap.reason or "unsupported"
            click.echo(f"  {provider_id:<22} UNSUPPORTED - {reason}{suffix}")

    click.echo("Session")
    sidecar = Sidecar.read(SIDECAR_PATH)
    if sidecar is None:
        click.echo("  Sidecar                absent (not running)")
    else:
        click.echo(f"  Sidecar                present ({SIDECAR_PATH})")
        click.echo(f"  Container              {sidecar.get('container_id', '?')}")


@mine.command()
@click.option(
    "--provider",
    type=click.Choice(["auto", "vllm-pearl", "cpu-pearl", "apple-mps-pearl"]),
    default="vllm-pearl",
    show_default=True,
)
@click.option(
    "--wallet",
    "--wallet-address",
    prompt="Pearl wallet address (prl1q/prl1p...)",
)
@click.option(
    "--pearld-url",
    "--pearld-rpc-url",
    default=DEFAULT_PEARLD_RPC_URL,
    prompt="pearld RPC URL",
)
@click.option(
    "--pearld-user",
    "--pearld-rpc-user",
    default="rpcuser",
    prompt="pearld RPC user",
)
@click.option(
    "--pearld-password-env",
    "--pearld-rpc-password-env",
    default="PEARLD_RPC_PASSWORD",
    prompt="env var holding pearld password",
)
@click.option("--model", default=DEFAULT_PEARL_MODEL)
@click.option("--image", default=PEARL_IMAGE_TAG)
@click.option(
    "--cuda-visible-devices",
    default="",
    help="Comma-separated NVIDIA GPU IDs to expose to the vLLM Pearl container.",
)
@click.option("--gateway-host", default="127.0.0.1", show_default=True)
@click.option("--gateway-port", default=DEFAULT_GATEWAY_RPC_PORT, show_default=True)
@click.option(
    "--gateway-metrics-port",
    "--metrics-port",
    default=DEFAULT_GATEWAY_METRICS_PORT,
    show_default=True,
)
def init(
    provider: str,
    wallet: str,
    pearld_url: str,
    pearld_user: str,
    pearld_password_env: str,
    model: str,
    image: str,
    cuda_visible_devices: str,
    gateway_host: str,
    gateway_port: int,
    gateway_metrics_port: int,
) -> None:
    """Interactive setup for the v1 Pearl mining providers."""
    _ensure_providers_registered()
    selected_provider = _select_provider(provider)
    if not MinerRegistry.contains(selected_provider):
        raise click.ClickException(f"Unknown mining provider: {selected_provider}")

    ok, info = check_wallet_address_format(wallet)
    if not ok:
        raise click.ClickException(f"Invalid wallet address: {info}")

    if selected_provider == "vllm-pearl":
        hw = _detect_hardware()
        cap = detect_for_engine_model(
            hw=hw,
            engine_id="vllm",
            model=model,
            provider_id="vllm-pearl",
        )
        if not cap.supported:
            raise click.ClickException(
                f"vllm-pearl not supported on this host: {cap.reason}\n"
                "See `jarvis mine models` and `jarvis mine doctor` for details."
            )
        model_spec = get_pearl_model_spec(model)
        max_model_len = (
            model_spec.default_max_model_len if model_spec is not None else 8192
        )
        gpu_memory_utilization = (
            model_spec.default_gpu_memory_utilization
            if model_spec is not None
            else 0.96
        )

        ok, info = check_docker_available()
        if not ok:
            raise click.ClickException(f"Docker unavailable: {info}")

        ok, info = check_disk_free(Path.home())
        if not ok:
            raise click.ClickException(f"Insufficient disk: {info}")
    else:
        max_model_len = 8192
        gpu_memory_utilization = 0.96

    if pearld_password_env not in os.environ:
        click.echo(
            f"Warning: ${pearld_password_env} is not set. "
            "Set it before `jarvis mine start`.",
            err=True,
        )

    from openjarvis.core.config import DEFAULT_CONFIG_PATH

    config_path = Path(os.environ.get("OPENJARVIS_CONFIG", DEFAULT_CONFIG_PATH))
    config_path.parent.mkdir(parents=True, exist_ok=True)
    section = f"""
[mining]
provider = "vllm-pearl"
wallet_address = "{wallet}"
submit_target = "solo"
fee_bps = 0
fee_payout_address = ""

[mining.extra]
docker_image_tag = "{image}"
model = "{model}"
cuda_visible_devices = "{cuda_visible_devices.strip()}"
gateway_port = {gateway_port}
gateway_metrics_port = {gateway_metrics_port}
vllm_port = 8000
gpu_memory_utilization = {gpu_memory_utilization}
max_model_len = {max_model_len}
pearld_rpc_url = "{pearld_url}"
pearld_rpc_user = "{pearld_user}"
pearld_rpc_password_env = "{pearld_password_env}"
hf_token_env = "HF_TOKEN"
"""
    if selected_provider != "vllm-pearl":
        section = f"""
[mining]
provider = "{selected_provider}"
wallet_address = "{wallet}"
submit_target = "solo"
fee_bps = 0
fee_payout_address = ""

[mining.extra]
gateway_host = "{gateway_host}"
gateway_port = {gateway_port}
metrics_port = {gateway_metrics_port}
pearld_rpc_url = "{pearld_url}"
pearld_rpc_user = "{pearld_user}"
pearld_rpc_password_env = "{pearld_password_env}"
"""
    if config_path.exists():
        existing = config_path.read_text()
        if "[mining]" in existing:
            click.echo("[mining] section already present; not overwriting.")
            return
        config_path.write_text(existing.rstrip() + "\n" + section)
    else:
        config_path.write_text(section.lstrip())
    load_config.cache_clear()

    if selected_provider == "vllm-pearl":
        click.echo(f"Resolving image {image}...")
        PearlDockerLauncher(client=_docker_from_env()).ensure_image(image)
    click.echo("Done. Run `jarvis mine start` to begin mining.")


@mine.command()
def start() -> None:
    """Launch the configured mining provider."""
    _ensure_providers_registered()
    load_config.cache_clear()
    cfg = load_config().mining
    if cfg is None:
        raise click.ClickException(
            "no [mining] section in config - run `jarvis mine init`"
        )
    provider = MinerRegistry.get(cfg.provider)()
    asyncio.run(provider.start(cfg))
    click.echo(f"Started {cfg.provider}. Run `jarvis mine status` for live stats.")


@mine.command()
def stop() -> None:
    """Stop the configured mining provider."""
    _ensure_providers_registered()
    sidecar = Sidecar.read(SIDECAR_PATH)
    if sidecar and (sidecar.get("gateway_pid") or sidecar.get("miner_loop_pid")):
        _terminate_pid(sidecar.get("miner_loop_pid"), grace_seconds=2.0)
        _terminate_pid(sidecar.get("gateway_pid"), grace_seconds=5.0)
        Sidecar.remove(SIDECAR_PATH)
        click.echo("Mining stopped.")
        return
    load_config.cache_clear()
    cfg = load_config().mining
    if cfg is None:
        click.echo("no [mining] section - nothing to stop")
        return
    provider = MinerRegistry.get(cfg.provider)()
    asyncio.run(provider.stop())
    click.echo("Mining stopped.")


@mine.command()
def status() -> None:
    """Print live mining stats."""
    _ensure_providers_registered()
    sidecar = Sidecar.read(SIDECAR_PATH)
    if sidecar is not None:
        provider_id = str(sidecar.get("provider", "unknown"))
        click.echo(f"provider:           {provider_id}")
        if "gateway_pid" in sidecar:
            gateway_pid = sidecar.get("gateway_pid")
            miner_pid = sidecar.get("miner_loop_pid")
            click.echo(
                f"gateway pid:        {gateway_pid} "
                f"({'alive' if _pid_alive(gateway_pid) else 'dead'})"
            )
            click.echo(
                f"miner pid:          {miner_pid} "
                f"({'alive' if _pid_alive(miner_pid) else 'dead'})"
            )
        metrics_url = sidecar.get("metrics_url")
        if metrics_url:
            stats, error = _stats_from_metrics_url(str(metrics_url), provider_id)
            if error:
                click.echo(f"metrics error:      {error}")
                return
            if stats is not None:
                click.echo(f"Shares submitted:   {stats.shares_submitted}")
                click.echo(f"Shares accepted:    {stats.shares_accepted}")
                click.echo(f"Blocks found:       {stats.blocks_found}")
                return

    load_config.cache_clear()
    cfg = load_config().mining
    if cfg is None:
        click.echo("No active mining session")
        return
    provider = MinerRegistry.get(cfg.provider)()
    stats = provider.stats()
    click.echo(f"provider:           {stats.provider_id}")
    click.echo(f"shares submitted:   {stats.shares_submitted}")
    click.echo(f"shares accepted:    {stats.shares_accepted}")
    click.echo(f"blocks found:       {stats.blocks_found}")
    click.echo(f"hashrate:           {stats.hashrate:.2f}")
    click.echo(f"uptime (s):         {stats.uptime_seconds:.0f}")
    click.echo(f"last share at:      {stats.last_share_at or '-'}")
    click.echo(f"last error:         {stats.last_error or '-'}")
    click.echo(f"payout target:      {stats.payout_target}")
    click.echo(f"fees owed:          {stats.fees_owed}")


@mine.command("validate-model")
@click.option("--model", default=None, help="Pearl model id to validate.")
@click.option(
    "--vllm-endpoint",
    default=None,
    help="OpenAI-compatible vLLM endpoint, defaults to the mining sidecar.",
)
@click.option(
    "--gateway-metrics-url",
    default=None,
    help="Pearl gateway metrics URL, defaults to the mining sidecar.",
)
@click.option(
    "--allow-planned",
    is_flag=True,
    default=False,
    help="Allow planned models while collecting validation evidence.",
)
@click.option(
    "--prompt",
    default=None,
    help="Optional chat-completion smoke prompt to run through vLLM.",
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write a JSON validation artifact.",
)
@click.option("--timeout", default=10.0, show_default=True, type=float)
def validate_model(
    model: str | None,
    vllm_endpoint: str | None,
    gateway_metrics_url: str | None,
    allow_planned: bool,
    prompt: str | None,
    output: Path | None,
    timeout: float,
) -> None:
    """Collect runtime evidence for Pearl model validation."""
    sidecar = Sidecar.read(SIDECAR_PATH)
    sidecar_model = sidecar.get("model") if sidecar else None
    model_id = model or sidecar_model or DEFAULT_PEARL_MODEL
    endpoint = vllm_endpoint or (sidecar.get("vllm_endpoint") if sidecar else None)
    metrics_url = gateway_metrics_url or (
        sidecar.get("gateway_metrics_url") if sidecar else None
    )

    click.echo("Pearl Model Validation")
    click.echo(f"model:              {model_id}")
    results: list[bool] = []
    records: list[dict[str, Any]] = []

    def record(name: str, ok: bool, info: str) -> None:
        records.append({"name": name, "ok": ok, "info": info})
        _validation_row(results, name, ok, info)

    spec = get_pearl_model_spec(str(model_id))
    if spec is None:
        planned = pearl_variant_for_base_model(str(model_id))
        info = f"raw model; planned Pearl variant {planned}" if planned else "unknown"
        record("Model registry", False, info)
    elif spec.is_validated:
        record("Model registry", True, f"validated: {spec.model_id}")
    else:
        record(
            "Model registry",
            allow_planned,
            f"{spec.status}: {spec.model_id}",
        )

    if sidecar is None:
        record(
            "Sidecar",
            False,
            "absent - run `jarvis mine start` first",
        )
    else:
        record("Sidecar", True, f"present ({SIDECAR_PATH})")
        record(
            "Sidecar model",
            sidecar_model == model_id,
            str(sidecar_model or "missing"),
        )

    if endpoint is None:
        record("vLLM endpoint", False, "missing")
    else:
        endpoint = endpoint.rstrip("/")
        try:
            models_payload = _get_json(f"{endpoint}/models", timeout=timeout)
            model_ids = _extract_model_ids(models_payload)
            models_info = (
                str(model_id) if str(model_id) in model_ids else f"{len(model_ids)} ids"
            )
            record(
                "vLLM /models",
                str(model_id) in model_ids,
                models_info,
            )
        except Exception as exc:  # noqa: BLE001
            record("vLLM /models", False, str(exc).splitlines()[0])

        if prompt:
            try:
                payload = {
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 16,
                    "stream": False,
                }
                response = _post_json(
                    f"{endpoint}/chat/completions",
                    payload,
                    timeout=timeout,
                )
                choices = response.get("choices")
                record(
                    "Chat completion",
                    bool(choices),
                    "choices returned" if choices else "no choices",
                )
            except Exception as exc:  # noqa: BLE001
                record(
                    "Chat completion",
                    False,
                    str(exc).splitlines()[0],
                )
        else:
            click.echo("  Chat completion        skipped (pass --prompt to run)")

    metrics_candidates: list[tuple[str, str]] = []
    if metrics_url is not None:
        gateway_metrics_url = str(metrics_url).rstrip("/")
        if not gateway_metrics_url.endswith("/metrics"):
            gateway_metrics_url = f"{gateway_metrics_url}/metrics"
        metrics_candidates.append(("gateway", gateway_metrics_url))
        metrics_url = gateway_metrics_url
    if endpoint is not None:
        vllm_metrics_url = str(endpoint).rstrip("/").removesuffix("/v1") + "/metrics"
        if not any(url == vllm_metrics_url for _, url in metrics_candidates):
            metrics_candidates.append(("vLLM", vllm_metrics_url))

    if not metrics_candidates:
        record("Gateway metrics", False, "missing")
    else:
        errors: list[str] = []
        for label, candidate_url in metrics_candidates:
            stats, error = _stats_from_metrics_url(candidate_url, "vllm-pearl")
            if error:
                errors.append(f"{label}: {error}")
                continue
            submitted = stats.shares_submitted if stats is not None else 0
            accepted = stats.shares_accepted if stats is not None else 0
            record(
                "Gateway metrics",
                True,
                f"{label} submitted={submitted} accepted={accepted}",
            )
            break
        else:
            record("Gateway metrics", False, " | ".join(errors))

    passed = bool(results) and all(results)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        artifact = {
            "schema_version": 1,
            "model": str(model_id),
            "status": "passed" if passed else "failed",
            "allow_planned": allow_planned,
            "prompt_ran": bool(prompt),
            "vllm_endpoint": endpoint,
            "gateway_metrics_url": metrics_url,
            "sidecar_path": str(SIDECAR_PATH),
            "checks": records,
        }
        output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
        click.echo(f"Validation artifact written to {output}")

    if not passed:
        raise click.ClickException("Pearl model validation checks failed.")
    click.echo("Validation checks passed.")


@mine.command("inspect-model")
@click.option("--model", default=DEFAULT_PEARL_MODEL, help="Pearl model id to inspect.")
@click.option(
    "--allow-planned",
    is_flag=True,
    default=False,
    help="Inspect planned models even though they are not enabled for mining yet.",
)
@click.option(
    "--hf-token-env",
    default="HF_TOKEN",
    show_default=True,
    help="Environment variable containing a Hugging Face token.",
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write a JSON artifact inspection report.",
)
@click.option("--timeout", default=10.0, show_default=True, type=float)
def inspect_model(
    model: str,
    allow_planned: bool,
    hf_token_env: str,
    output: Path | None,
    timeout: float,
) -> None:
    """Inspect a Pearl model artifact before spending GPU time."""

    click.echo("Pearl Model Artifact Inspection")
    click.echo(f"model:              {model}")
    results: list[bool] = []
    records: list[dict[str, Any]] = []

    def record(name: str, ok: bool, info: str) -> None:
        records.append({"name": name, "ok": ok, "info": info})
        _validation_row(results, name, ok, info)

    spec = get_pearl_model_spec(model)
    if spec is None:
        planned = pearl_variant_for_base_model(model)
        info = f"raw model; planned Pearl variant {planned}" if planned else "unknown"
        record("Model registry", False, info)
    elif spec.is_validated:
        record("Model registry", True, f"validated: {spec.model_id}")
    else:
        record("Model registry", allow_planned, f"{spec.status}: {spec.model_id}")

    token = os.environ.get(hf_token_env, "")
    model_payload: Any = None
    paths: set[str] = set()
    try:
        model_payload = _hf_json(
            _hf_model_path(model, ""),
            token=token,
            timeout=timeout,
        )
        record("HF model", True, "accessible")
    except urllib.error.HTTPError as exc:
        info = f"HTTP {exc.code}"
        if exc.code in {401, 403} and not token:
            info += f"; set ${hf_token_env} for gated/private models"
        record("HF model", False, info)
    except Exception as exc:  # noqa: BLE001
        record("HF model", False, str(exc).splitlines()[0])

    if model_payload is not None:
        quant_method = _artifact_quant_method(model_payload)
        record(
            "Pearl quantization",
            quant_method == "pearl",
            quant_method or "missing quantization_config.quant_method",
        )

        try:
            tree_payload = _hf_json(
                _hf_model_path(model, "/tree/main?recursive=false"),
                token=token,
                timeout=timeout,
            )
            paths = _artifact_file_paths(tree_payload)
            record("HF file list", bool(paths), f"{len(paths)} files")
        except Exception as exc:  # noqa: BLE001
            record("HF file list", False, str(exc).splitlines()[0])

    if paths:
        has_config = "config.json" in paths
        record(
            "config.json",
            has_config,
            "present" if has_config else "missing",
        )
        tokenizer_ok = bool({"tokenizer.json", "tokenizer_config.json"} & paths)
        record(
            "Tokenizer metadata",
            tokenizer_ok,
            "present"
            if tokenizer_ok
            else "missing tokenizer.json/tokenizer_config.json",
        )
        has_weights = _artifact_has_weights(paths)
        record(
            "Weights",
            has_weights,
            "present" if has_weights else "missing",
        )

        architectures = _artifact_architectures(model_payload)
        is_gemma4 = any("Gemma4" in arch for arch in architectures)
        if is_gemma4:
            missing = [
                name
                for name in ("processor_config.json", "preprocessor_config.json")
                if name not in paths
            ]
            record(
                "Gemma4 processor metadata",
                not missing,
                "present" if not missing else "missing " + ", ".join(missing),
            )

    passed = bool(results) and all(results)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        artifact = {
            "schema_version": 1,
            "model": model,
            "status": "passed" if passed else "failed",
            "allow_planned": allow_planned,
            "hf_token_env": hf_token_env,
            "checks": records,
        }
        output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
        click.echo(f"Inspection artifact written to {output}")

    if not passed:
        raise click.ClickException("Pearl model artifact inspection failed.")
    click.echo("Artifact inspection passed.")


@mine.command()
@click.option("--vllm-endpoint", required=True)
@click.option("--gateway-url", required=True)
@click.option("--gateway-metrics-url", required=True)
@click.option("--model", default=DEFAULT_PEARL_MODEL)
@click.option("--container-id", default="external")
@click.option("--wallet", default="")
def attach(
    vllm_endpoint: str,
    gateway_url: str,
    gateway_metrics_url: str,
    model: str,
    container_id: str,
    wallet: str,
) -> None:
    """Manual mode: write a sidecar for an externally-started miner."""
    Sidecar.write(
        SIDECAR_PATH,
        {
            "provider": "vllm-pearl",
            "vllm_endpoint": vllm_endpoint,
            "model": model,
            "gateway_url": gateway_url,
            "gateway_metrics_url": gateway_metrics_url,
            "container_id": container_id,
            "wallet_address": wallet,
            "started_at": int(time.time()),
        },
    )
    click.echo(f"Sidecar written to {SIDECAR_PATH}")


@mine.command()
@click.option("-n", "--tail", "tail_n", default=200, type=int)
@click.option("-f", "--follow", is_flag=True, default=False)
def logs(tail_n: int, follow: bool) -> None:
    """Print the Pearl miner container log tail."""
    if follow:
        click.echo("note: -f follow is not implemented in v1; printing tail", err=True)
    client = _docker_from_env()
    launcher = PearlDockerLauncher(client=client)
    try:
        launcher._container = client.containers.get("openjarvis-pearl-miner")
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(f"no mining container: {exc}") from exc
    click.echo(launcher.get_logs(tail=tail_n))
