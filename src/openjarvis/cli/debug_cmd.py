"""Debug mode for OpenJarvis development."""

from __future__ import annotations

import sys

import click


@click.command("dev")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=8000, help="Port to bind to")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload")
@click.option(
    "--debug-tools", is_flag=True, default=False, help="Enable tool debug output"
)
@click.option(
    "--debug-agent", is_flag=True, default=False, help="Enable agent debug output"
)
@click.pass_context
def dev(
    ctx: click.Context,
    host: str,
    port: int,
    reload: bool,
    debug_tools: bool,
    debug_agent: bool,
) -> None:
    """Start OpenJarvis in development/debug mode.

    This command provides an interactive development experience with:
    - Debug logging enabled by default
    - Tool execution tracing
    - Agent decision tracking
    - Optional auto-reload (for serve mode)
    """
    import logging

    from openjarvis.cli.log_config import setup_logging

    setup_logging(verbose=True, quiet=False)
    logger = logging.getLogger("openjarvis")

    if debug_tools:
        logging.getLogger("openjarvis.tools").setLevel(logging.DEBUG)
    if debug_agent:
        logging.getLogger("openjarvis.agents").setLevel(logging.DEBUG)

    logger.info("Starting OpenJarvis in debug mode")
    logger.info(f"Debug flags: tools={debug_tools}, agent={debug_agent}")

    if reload:
        logger.info("Auto-reload enabled")

    click.echo("""
╔═══════════════════════════════════════════════════════════════╗
║                    OpenJarvis DEBUG MODE                      ║
╠═══════════════════════════════════════════════════════════════╣
║  Debug logging is enabled                                     ║
║  Tool execution will be traced to console                     ║
║  Agent decisions will be logged                                ║
║                                                               ║
║  To enable additional debugging:                               ║
║    --debug-tools   : Trace tool calls                        ║
║    --debug-agent   : Trace agent decisions                   ║
║    --reload        : Auto-reload on file changes              ║
╚═══════════════════════════════════════════════════════════════╝
""")

    if "--help" not in sys.argv:
        click.echo("\nHint: Use 'jarvis serve --help' to start the API server")
        click.echo("Hint: Use 'jarvis ask --help' to start an interactive chat\n")

    ctx.obj = ctx.obj or {}
    ctx.obj["debug"] = True
    ctx.obj["debug_tools"] = debug_tools
    ctx.obj["debug_agent"] = debug_agent
    ctx.obj["reload"] = reload


__all__ = ["dev"]
