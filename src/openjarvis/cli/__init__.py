"""Command-line interface for Serena (Click-based)."""

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
from openjarvis.cli.deep_research_setup_cmd import deep_research_setup
from openjarvis.cli.digest_cmd import digest
from openjarvis.cli.doctor_cmd import doctor
from openjarvis.cli.eval_cmd import eval_group
from openjarvis.cli.feedback_cmd import feedback_group
from openjarvis.cli.gateway_cmd import gateway
from openjarvis.cli.host_cmd import host
from openjarvis.cli.listen_cmd import listen
from openjarvis.cli.live_cmd import live
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
from openjarvis.cli.say_cmd import say
from openjarvis.cli.speak_cmd import speak
from openjarvis.cli.scheduler_cmd import scheduler
from openjarvis.cli.serve import serve
from openjarvis.cli.skill_cmd import skill
from openjarvis.cli.telemetry_cmd import telemetry
from openjarvis.cli.tool_cmd import tool
from openjarvis.cli.vault_cmd import vault
from openjarvis.cli.voice_cmd import voice
from openjarvis.cli.workflow_cmd import workflow
from openjarvis.cli.wordpress_cmd import wordpress
from openjarvis.cli.documents_cmd import documents
from openjarvis.cli.files_cmd import files
from openjarvis.cli.vscode_cmd import vscode
from openjarvis.cli.vscode_builder_cmd import vscode_builder
from openjarvis.cli.github_cmd import github
from openjarvis.cli.health_monitor_cmd import health_monitor
from openjarvis.cli.gdrive_cmd import gdrive
from openjarvis.cli.google_docs_cmd import google_docs
from openjarvis.cli.ocr_cmd import ocr
from openjarvis.cli.google_calendar_cmd import calendar
from openjarvis.cli.compliance_cmd import compliance
from openjarvis.learning.distillation.cli import learning_group


@click.group(
    help="Serena - Dr Piet Muller local AI assistant and operator",
    invoke_without_command=True,
)
@click.version_option(version=openjarvis.__version__, prog_name="serena")
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

    # Check for updates on interactive commands
    if not quiet and ctx.invoked_subcommand:
        from openjarvis.cli._version_check import check_for_updates

        check_for_updates(ctx.invoked_subcommand)

    # First-run guard - routes bare serena to chat or init.
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
cli.add_command(wordpress, "wordpress")
cli.add_command(documents, "documents")
cli.add_command(files, "files")
cli.add_command(vscode, "vscode")
cli.add_command(vscode_builder, "vscode-builder")
cli.add_command(github, "github")
cli.add_command(health_monitor, "health-monitor")
cli.add_command(gdrive, "gdrive")
cli.add_command(google_docs, "google-docs")
cli.add_command(ocr, "ocr")
cli.add_command(calendar, "calendar")
cli.add_command(compliance, "compliance")
cli.add_command(skill, "skill")
cli.add_command(start, "start")
cli.add_command(stop, "stop")
cli.add_command(restart, "restart")
cli.add_command(status, "status")
cli.add_command(vault, "vault")
cli.add_command(voice, "voice")
cli.add_command(add, "add")
cli.add_command(operators, "operators")
cli.add_command(eval_group, "eval")
cli.add_command(host, "host")
cli.add_command(listen, "listen")
cli.add_command(live, "live")
cli.add_command(quickstart, "quickstart")
cli.add_command(optimize_group, "optimize")
cli.add_command(feedback_group, "feedback")
cli.add_command(compose, "compose")
cli.add_command(gateway, "gateway")
cli.add_command(tool, "tool")
cli.add_command(registry, "registry")
cli.add_command(config, "config")
cli.add_command(scan, "scan")
cli.add_command(say, "say")
cli.add_command(speak, "speak")
cli.add_command(connect, "connect")
cli.add_command(digest, "digest")
cli.add_command(deep_research_setup, "deep-research-setup")
cli.add_command(deep_research_setup, "research")
cli.add_command(learning_group, "learning")
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
    """Entry point registered as the Serena console script."""
    cli()


__all__ = ["cli", "main"]
