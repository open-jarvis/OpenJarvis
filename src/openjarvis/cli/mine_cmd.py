"""``jarvis mine`` command group."""

from __future__ import annotations

import os
from pathlib import Path

import click

from openjarvis.core.config import HardwareInfo, detect_hardware, load_config
from openjarvis.core.registry import MinerRegistry
from openjarvis.mining._constants import (
    DEFAULT_PEARL_MODEL,
    DEFAULT_PEARLD_RPC_URL,
    SIDECAR_PATH,
)
from openjarvis.mining._discovery import (
    check_disk_free,
    check_docker_available,
    check_pearld_reachable,
    check_wallet_address_format,
)
from openjarvis.mining._stubs import Sidecar
from openjarvis.mining.vllm_pearl import ensure_registered as ensure_vllm_registered


def _detect_hardware() -> HardwareInfo:
    """Wrapper to make hardware detection mockable in CLI tests."""
    return detect_hardware()


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
