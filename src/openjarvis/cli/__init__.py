"""Command-line interface for OpenJarvis (Click-based)."""

from __future__ import annotations

import click

import openjarvis
from openjarvis.cli.add_cmd import add
from openjarvis.cli.agent_cmd import agent
from openjarvis.cli.ask import ask
from openjarvis.cli.bench_cmd import bench
from openjarvis.cli.channel_cmd import channel
from openjarvis.cli.chat_cmd import chat
from openjarvis.cli.daemon_cmd import restart, start, status, stop
from openjarvis.cli.doctor_cmd import doctor
from openjarvis.cli.eval_cmd import eval_group
from openjarvis.cli.feedback_cmd import feedback_group
from openjarvis.cli.host_cmd import host
from openjarvis.cli.init_cmd import init
from openjarvis.cli.memory_cmd import memory
from openjarvis.cli.model import model
from openjarvis.cli.operators_cmd import operators
from openjarvis.cli.optimize_cmd import optimize_group
from openjarvis.cli.quickstart_cmd import quickstart
from openjarvis.cli.scheduler_cmd import scheduler
from openjarvis.cli.serve import serve
from openjarvis.cli.skill_cmd import skill
from openjarvis.cli.telemetry_cmd import telemetry
from openjarvis.cli.vault_cmd import vault
from openjarvis.cli.workflow_cmd import workflow


@click.group(help="OpenJarvis — modular AI assistant backend")
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


cli.add_command(init, "init")
cli.add_command(ask, "ask")
cli.add_command(chat, "chat")
cli.add_command(serve, "serve")
cli.add_command(model, "model")
cli.add_command(memory, "memory")
cli.add_command(telemetry, "telemetry")
cli.add_command(bench, "bench")
cli.add_command(channel, "channel")
cli.add_command(scheduler, "scheduler")
cli.add_command(doctor, "doctor")
cli.add_command(agent, "agent")
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


def main() -> None:
    """Entry point registered as ``jarvis`` console script."""
    cli()


__all__ = ["cli", "main"]
