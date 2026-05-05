"""``jarvis pearl`` — thin wrappers around Pearl's native CLIs."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import click

PASSTHROUGH = {"ignore_unknown_options": True, "allow_extra_args": True}


def _candidate_roots(pearl_home: str | None) -> list[Path]:
    roots: list[Path] = []
    if pearl_home:
        roots.append(Path(pearl_home).expanduser())
    env_home = os.environ.get("PEARL_HOME")
    if env_home:
        roots.append(Path(env_home).expanduser())
    roots.extend(
        [
            Path.cwd() / "pearl",
            Path.cwd().parent / "pearl",
            Path.home() / "pearl",
        ]
    )
    return roots


def _resolve_binary(name: str, pearl_home: str | None = None) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for root in _candidate_roots(pearl_home):
        candidate = root / "bin" / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _require_binary(name: str, pearl_home: str | None = None) -> str:
    binary = _resolve_binary(name, pearl_home)
    if binary is None:
        raise click.ClickException(
            f"Pearl binary {name!r} not found. Set PEARL_HOME=/path/to/pearl "
            "or put Pearl's bin/ directory on PATH."
        )
    return binary


def _run(name: str, args: tuple[str, ...], pearl_home: str | None = None) -> int:
    binary = _require_binary(name, pearl_home)
    completed = subprocess.run([binary, *args], check=False)
    return completed.returncode


def _run_capture(
    name: str, args: tuple[str, ...], pearl_home: str | None = None
) -> subprocess.CompletedProcess[str]:
    binary = _require_binary(name, pearl_home)
    return subprocess.run(
        [binary, *args],
        check=False,
        capture_output=True,
        text=True,
    )


@click.group()
def pearl() -> None:
    """Access Pearl node, wallet, and RPC tools."""


@pearl.command("doctor")
@click.option("--pearl-home", type=click.Path(file_okay=False), default=None)
def doctor(pearl_home: str | None) -> None:
    """Show whether Pearl native binaries are discoverable."""
    click.echo("Pearl CLI Doctor")
    for name in ("pearld", "oyster", "prlctl"):
        binary = _resolve_binary(name, pearl_home)
        if binary:
            click.echo(f"  {name:<8} {binary} OK")
        else:
            click.echo(f"  {name:<8} not found FAIL")
    click.echo("Set PEARL_HOME=/path/to/pearl if binaries are not on PATH.")


@pearl.command("node", context_settings=PASSTHROUGH)
@click.option("--pearl-home", type=click.Path(file_okay=False), default=None)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def node(ctx: click.Context, pearl_home: str | None, args: tuple[str, ...]) -> None:
    """Run ``pearld`` with pass-through arguments."""
    ctx.exit(_run("pearld", args, pearl_home))


@pearl.command("wallet", context_settings=PASSTHROUGH)
@click.option("--pearl-home", type=click.Path(file_okay=False), default=None)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def wallet(ctx: click.Context, pearl_home: str | None, args: tuple[str, ...]) -> None:
    """Run ``oyster`` with pass-through arguments."""
    ctx.exit(_run("oyster", args, pearl_home))


@pearl.command("ctl", context_settings=PASSTHROUGH)
@click.option("--pearl-home", type=click.Path(file_okay=False), default=None)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def ctl(ctx: click.Context, pearl_home: str | None, args: tuple[str, ...]) -> None:
    """Run ``prlctl`` with pass-through arguments."""
    ctx.exit(_run("prlctl", args, pearl_home))


@pearl.command("address")
@click.option("--pearl-home", type=click.Path(file_okay=False), default=None)
@click.option("-u", "--user", default="rpcuser", show_default=True)
@click.option("-P", "--password", default="rpcpass", show_default=True)
@click.option("-s", "--server", default="localhost:44207", show_default=True)
@click.option("--notls/--tls", default=True, show_default=True)
@click.option("--skipverify/--verify", default=True, show_default=True)
def address(
    pearl_home: str | None,
    user: str,
    password: str,
    server: str,
    notls: bool,
    skipverify: bool,
) -> None:
    """Generate a Pearl wallet address through Oyster's wallet RPC."""
    args = ["--wallet", "-u", user, "-P", password, "-s", server]
    if notls:
        args.append("--notls")
    elif skipverify:
        args.append("--skipverify")
    args.append("getnewaddress")

    completed = _run_capture("prlctl", tuple(args), pearl_home)
    if completed.stdout:
        click.echo(completed.stdout.rstrip())
    if completed.stderr:
        click.echo(completed.stderr.rstrip(), err=True)
    if completed.returncode:
        raise click.ClickException(f"prlctl exited with {completed.returncode}")


__all__ = ["pearl"]
