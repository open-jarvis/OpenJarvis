"""Command-line interface for OpenJarvis (Click-based)."""

from __future__ import annotations

import click

import openjarvis
from openjarvis.cli._bootstrap import bootstrap_cmd
from openjarvis.cli.add_cmd import add
from openjarvis.cli.agent_cmd import agent
from openjarvis.cli.ask import ask
from openjarvis.cli.bench_cmd import bench
from openjarvis.cli.channel_cmd import channel
from openjarvis.cli.channels_cmd import channels
from openjarvis.cli.chat_cmd import chat
from openjarvis.cli.compose_cmd import compose
from openjarvis.cli.config_cmd import config
from openjarvis.cli.connect_cmd import connect
from openjarvis.cli.daemon_cmd import restart, start, status, stop
from openjarvis.cli.digest_cmd import digest
from openjarvis.cli.doctor_cmd import doctor
from openjarvis.cli.eval_cmd import eval_group
from openjarvis.cli.feedback_cmd import feedback_group
from openjarvis.cli.gateway_cmd import gateway
from openjarvis.cli.host_cmd import host
from openjarvis.cli.init_cmd import init
from openjarvis.cli.memory_cmd import memory
from openjarvis.cli.mine_cmd import mine
from openjarvis.cli.model import model
from openjarvis.cli.operators_cmd import operators
from openjarvis.cli.optimize_cmd import optimize_group
from openjarvis.cli.pearl_cmd import pearl
from openjarvis.cli.quickstart_cmd import quickstart
from openjarvis.cli.registry_cmd import registry
from openjarvis.cli.scan_cmd import scan
from openjarvis.cli.scheduler_cmd import scheduler
from openjarvis.cli.self_update_cmd import self_update
from openjarvis.cli.serve import serve
from openjarvis.cli.skill_cmd import skill
from openjarvis.cli.telemetry_cmd import telemetry
from openjarvis.cli.tool_cmd import tool
from openjarvis.cli.vault_cmd import vault
from openjarvis.cli.workflow_cmd import workflow


@click.group(
    help="OpenJarvis — modular AI assistant backend",
    invoke_without_command=True,
)
@click.version_option(version=openjarvis.__version__, prog_name="jarvis")
@click.option("--verbose", is_flag=True, default=False, help="Enable debug logging")
@click.option("--quiet", is_flag=True, default=False, help="Suppress non-error output")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, quiet: bool) -> None:
    """Top-level CLI group."""
    from openjarvis.cli.log_config import setup_logging

    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet
    setup_logging(verbose=verbose, quiet=quiet)

    # Check for updates on interactive commands. The banner is noise in
    # demo recordings of ``jarvis ask --research``, so skip it whenever
    # the research flag is in argv (cheap argv sniff — Click hasn't
    # parsed the subcommand's args yet at this point).
    import sys

    research_mode_active = "--research" in sys.argv
    if not quiet and ctx.invoked_subcommand and not research_mode_active:
        import threading

        from openjarvis.cli._version_check import check_for_updates

        # Run the PyPI version poll off the hot path: on a cache miss it does
        # a blocking urlopen (up to 3s) that otherwise delays every command,
        # notably `jarvis serve` startup (#263). It's best-effort and never
        # raises, and the nudge prints to stderr, so a daemon thread is safe —
        # for long-lived commands (serve) it finishes; for short commands that
        # exit first, the check is simply skipped this run (same as a miss).
        threading.Thread(
            target=check_for_updates,
            args=(ctx.invoked_subcommand,),
            daemon=True,
        ).start()

    # First-run guard — routes bare `jarvis` to chat or init.
    if ctx.invoked_subcommand is None:
        from openjarvis.cli._first_run import check_and_route

        check_and_route(ctx)


cli.add_command(init, "init")
cli.add_command(ask, "ask")
cli.add_command(chat, "chat")
cli.add_command(serve, "serve")
cli.add_command(model, "model")
cli.add_command(memory, "memory")
cli.add_command(mine, "mine")
cli.add_command(pearl, "pearl")
cli.add_command(telemetry, "telemetry")
cli.add_command(bench, "bench")
cli.add_command(channel, "channel")
cli.add_command(channels, "channels")
cli.add_command(scheduler, "scheduler")
cli.add_command(doctor, "doctor")
cli.add_command(agent, "agents")
cli.add_command(workflow, "workflow")
cli.add_command(skill, "skill")
cli.add_command(start, "start")
cli.add_command(stop, "stop")
cli.add_command(restart, "restart")
cli.add_command(status, "status")
cli.add_command(vault, "vault")
cli.add_command(add, "add")
cli.add_command(operators, "operators")
cli.add_command(eval_group, "eval")
cli.add_command(host, "host")
cli.add_command(quickstart, "quickstart")
cli.add_command(optimize_group, "optimize")
cli.add_command(feedback_group, "feedback")
cli.add_command(compose, "compose")
cli.add_command(gateway, "gateway")
cli.add_command(tool, "tool")
cli.add_command(registry, "registry")
cli.add_command(config, "config")
cli.add_command(scan, "scan")
cli.add_command(connect, "connect")
cli.add_command(digest, "digest")
# deep-research setup pulls the ingestion pipeline (embeddings/numpy). Guard it
# so a broken or slow numpy on Windows — which can raise at IMPORT time, not
# just ImportError (#404) — can never take down the whole CLI, including
# `jarvis serve`. Invoking `jarvis deep-research-setup` without the deps still
# errors clearly on demand.
try:
    from openjarvis.cli.deep_research_setup_cmd import deep_research_setup

    cli.add_command(deep_research_setup, "deep-research-setup")
    cli.add_command(deep_research_setup, "research")
except Exception as _dr_exc:
    import logging as _logging

    _logging.getLogger(__name__).debug("deep-research command unavailable: %s", _dr_exc)
cli.add_command(self_update, "self-update")
cli.add_command(bootstrap_cmd, "_bootstrap")

# Gateway CLI commands (lazy import to avoid pulling starlette)
try:
    from openjarvis.cli.auth_cmd import auth

    cli.add_command(auth, "auth")
except ImportError:
    pass

try:
    from openjarvis.cli.tunnel_cmd import tunnel

    cli.add_command(tunnel, "tunnel")
except ImportError:
    pass


def main() -> None:
    """Entry point registered as ``jarvis`` console script."""
    import sys

    if sys.platform == "win32":
        for _stream in (sys.stdout, sys.stderr):
            if hasattr(_stream, "reconfigure"):
                try:
                    _stream.reconfigure(encoding="utf-8", errors="replace")
                except (AttributeError, OSError):
                    pass
    cli()


__all__ = ["cli", "main"]
