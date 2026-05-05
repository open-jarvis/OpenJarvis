"""``jarvis mine`` command group."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import click

from openjarvis.core.config import HardwareInfo, detect_hardware, load_config
from openjarvis.core.registry import MinerRegistry
from openjarvis.mining._constants import (
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
from openjarvis.mining._stubs import Sidecar
from openjarvis.mining.vllm_pearl import ensure_registered as ensure_vllm_registered


def _detect_hardware() -> HardwareInfo:
    """Wrapper to make hardware detection mockable in CLI tests."""
    return detect_hardware()


def _docker_from_env():
    """Wrapper to make Docker client creation mockable in CLI tests."""
    import docker

    return docker.from_env()


def _row(name: str, ok: bool, info: str) -> None:
    marker = "OK" if ok else "FAIL"
    click.echo(f"  {name:<22} {info:<45} {marker}")


@click.group()
def mine() -> None:
    """Pearl PoUW mining commands."""


@mine.command()
def doctor() -> None:
    """Diagnose mining capability with one row per check."""
    ensure_vllm_registered()
    hw = _detect_hardware()
    cfg = load_config()
    mining_cfg = cfg.mining

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
@click.option("--wallet", prompt="Pearl Taproot wallet address (prl1q...)")
@click.option("--pearld-url", default=DEFAULT_PEARLD_RPC_URL, prompt="pearld RPC URL")
@click.option("--pearld-user", default="rpcuser", prompt="pearld RPC user")
@click.option(
    "--pearld-password-env",
    default="PEARLD_RPC_PASSWORD",
    prompt="env var holding pearld password",
)
@click.option("--model", default=DEFAULT_PEARL_MODEL)
@click.option("--image", default=PEARL_IMAGE_TAG)
def init(
    wallet: str,
    pearld_url: str,
    pearld_user: str,
    pearld_password_env: str,
    model: str,
    image: str,
) -> None:
    """Interactive setup for the v1 vllm-pearl provider."""
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
            "See `jarvis mine doctor` for details."
        )

    ok, info = check_docker_available()
    if not ok:
        raise click.ClickException(f"Docker unavailable: {info}")

    ok, info = check_disk_free(Path.home())
    if not ok:
        raise click.ClickException(f"Insufficient disk: {info}")

    ok, info = check_wallet_address_format(wallet)
    if not ok:
        raise click.ClickException(f"Invalid wallet address: {info}")

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
gateway_port = 8337
gateway_metrics_port = 8339
vllm_port = 8000
gpu_memory_utilization = 0.96
max_model_len = 8192
pearld_rpc_url = "{pearld_url}"
pearld_rpc_user = "{pearld_user}"
pearld_rpc_password_env = "{pearld_password_env}"
hf_token_env = "HF_TOKEN"
"""
    if config_path.exists():
        existing = config_path.read_text()
        if "[mining]" in existing:
            click.echo("[mining] section already present; not overwriting.")
            return
        config_path.write_text(existing.rstrip() + "\n" + section)
    else:
        config_path.write_text(section.lstrip())

    click.echo(f"Resolving image {image}...")
    PearlDockerLauncher(client=_docker_from_env()).ensure_image(image)
    click.echo("Done. Run `jarvis mine start` to begin mining.")


@mine.command()
def start() -> None:
    """Launch the configured mining provider."""
    ensure_vllm_registered()
    cfg = load_config().mining
    if cfg is None:
        raise click.ClickException(
            "no [mining] section in config - run `jarvis mine init`"
        )
    provider = MinerRegistry.get(cfg.provider)()
    asyncio.run(provider.start(cfg))
    click.echo("Mining started. Run `jarvis mine status` for live stats.")


@mine.command()
def stop() -> None:
    """Stop the configured mining provider."""
    ensure_vllm_registered()
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
    ensure_vllm_registered()
    cfg = load_config().mining
    if cfg is None:
        raise click.ClickException("no [mining] section - run `jarvis mine init`")
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
