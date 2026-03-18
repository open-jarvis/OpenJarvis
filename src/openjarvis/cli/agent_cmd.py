"""``jarvis agents`` — persistent agent lifecycle management."""

from __future__ import annotations

import threading
from typing import Optional

import click
from rich.console import Console
from rich.table import Table


def _get_manager():
    """Get or create the AgentManager singleton."""
    from pathlib import Path

    from openjarvis.agents.manager import AgentManager
    from openjarvis.core.config import load_config

    config = load_config()
    db_path = config.agent_manager.db_path or str(
        Path("~/.openjarvis/agents.db").expanduser()
    )
    return AgentManager(db_path=db_path)


def _resolve_agent_id(manager, agent_id_or_name: str) -> str:
    """Resolve an agent name or ID to the actual agent ID.

    Accepts either the hex ID or the agent name.  Raises SystemExit if
    no matching agent is found.
    """
    # Try direct ID lookup first
    agent = manager.get_agent(agent_id_or_name)
    if agent is not None:
        return agent["id"]

    # Fall back to name lookup
    for a in manager.list_agents(include_archived=True):
        if a["name"] == agent_id_or_name:
            return a["id"]

    click.echo(f"Agent not found: {agent_id_or_name}", err=True)
    raise SystemExit(1)


@click.group("agents")
def agent() -> None:
    """Manage persistent agents — create, inspect, chat, bind channels."""


@agent.command("list")
def list_agents() -> None:
    """List all managed agents."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        agents = mgr.list_agents()
        if not agents:
            console.print(
                "[dim]No agents found. Create one with: jarvis agents create[/dim]"
            )
            return
        table = Table(title="Managed Agents")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name", style="green")
        table.add_column("Type", style="yellow")
        table.add_column("Status", style="bold")
        table.add_column("Tasks", justify="right")
        table.add_column("Channels", justify="right")
        for a in agents:
            tasks = mgr.list_tasks(a["id"])
            bindings = mgr.list_channel_bindings(a["id"])
            status_style = {
                "idle": "dim", "running": "green", "paused": "yellow",
                "error": "red", "archived": "dim strike",
            }.get(a["status"], "")
            table.add_row(
                a["id"], a["name"], a["agent_type"],
                f"[{status_style}]{a['status']}[/{status_style}]",
                str(len(tasks)), str(len(bindings)),
            )
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("create")
@click.option("--name", "-n", required=True, help="Agent name")
@click.option("--template", "-t", default=None, help="Template ID to use")
@click.option("--type", "agent_type", default="monitor_operative", help="Agent type")
def create_agent(name: str, template: Optional[str], agent_type: str) -> None:
    """Create a new persistent agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        if template:
            result = mgr.create_from_template(template, name)
        else:
            result = mgr.create_agent(name=name, agent_type=agent_type)
        console.print(
            f"[green]Created agent:[/green] {result['id']} ({result['name']})"
        )
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("info")
@click.argument("agent_id")
def info(agent_id: str) -> None:
    """Show detailed info about a managed agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        a = mgr.get_agent(agent_id)
        if not a:
            console.print(f"[red]Agent not found: {agent_id}[/red]")
            return
        console.print(f"[bold]{a['name']}[/bold] ({a['id']})")
        console.print(f"  Type:   {a['agent_type']}")
        console.print(f"  Status: {a['status']}")
        if a.get("summary_memory"):
            console.print(f"  Memory: {a['summary_memory'][:100]}...")
        tasks = mgr.list_tasks(agent_id)
        if tasks:
            console.print(f"  Tasks:  {len(tasks)}")
            for t in tasks[:5]:
                console.print(f"    [{t['status']}] {t['description'][:60]}")
        bindings = mgr.list_channel_bindings(agent_id)
        if bindings:
            console.print(f"  Channels: {len(bindings)}")
            for b in bindings:
                console.print(f"    {b['channel_type']}: {b['config']}")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("tasks")
@click.argument("agent_id")
def tasks(agent_id: str) -> None:
    """List tasks for an agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        task_list = mgr.list_tasks(agent_id)
        if not task_list:
            console.print("[dim]No tasks.[/dim]")
            return
        table = Table(title="Tasks")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")
        table.add_column("Status", style="bold")
        for t in task_list:
            table.add_row(t["id"], t["description"][:60], t["status"])
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("pause")
@click.argument("agent_id")
def pause(agent_id: str) -> None:
    """Pause an agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        mgr.pause_agent(agent_id)
        console.print(f"[yellow]Paused agent {agent_id}[/yellow]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("resume")
@click.argument("agent_id")
def resume(agent_id: str) -> None:
    """Resume a paused agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        mgr.resume_agent(agent_id)
        console.print(f"[green]Resumed agent {agent_id}[/green]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("delete")
@click.argument("agent_id")
def delete(agent_id: str) -> None:
    """Archive (soft-delete) an agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        mgr.delete_agent(agent_id)
        console.print(f"[dim]Archived agent {agent_id}[/dim]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("bind")
@click.argument("agent_id")
@click.option("--slack", default=None, help="Slack channel (e.g. #research)")
@click.option("--telegram", default=None, help="Telegram chat ID")
@click.option("--whatsapp", default=None, help="WhatsApp phone number")
def bind(
    agent_id: str,
    slack: Optional[str],
    telegram: Optional[str],
    whatsapp: Optional[str],
) -> None:
    """Bind a channel to an agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        if slack:
            b = mgr.bind_channel(agent_id, "slack", {"channel": slack})
        elif telegram:
            b = mgr.bind_channel(agent_id, "telegram", {"chat_id": telegram})
        elif whatsapp:
            b = mgr.bind_channel(agent_id, "whatsapp", {"phone": whatsapp})
        else:
            console.print(
                "[red]Specify a channel: --slack, --telegram, or --whatsapp[/red]"
            )
            return
        console.print(f"[green]Bound channel:[/green] {b['id']} ({b['channel_type']})")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("channels")
@click.argument("agent_id")
def channels(agent_id: str) -> None:
    """List channel bindings for an agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        bindings = mgr.list_channel_bindings(agent_id)
        if not bindings:
            console.print("[dim]No channel bindings.[/dim]")
            return
        table = Table(title="Channel Bindings")
        table.add_column("ID", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Config", style="white")
        table.add_column("Mode", style="yellow")
        for b in bindings:
            table.add_row(
                b["id"], b["channel_type"], str(b["config"]), b["routing_mode"]
            )
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("search")
@click.argument("agent_id")
@click.argument("query")
@click.option("--limit", "-l", default=10, help="Max results")
def search(agent_id: str, query: str, limit: int) -> None:
    """Cross-session search across agent traces."""
    console = Console(stderr=True)
    try:
        from openjarvis.core.config import load_config
        from openjarvis.traces.store import TraceStore

        config = load_config()
        mgr = _get_manager()
        agent = mgr.get_agent(agent_id)
        if not agent:
            console.print(f"[red]Agent not found: {agent_id}[/red]")
            return
        store = TraceStore(config.traces.db_path or "~/.openjarvis/traces.db")
        results = store.search(query, agent=agent["name"], limit=limit)
        if not results:
            console.print("[dim]No results.[/dim]")
            return
        table = Table(title=f"Search: {query}")
        table.add_column("Trace", style="cyan", no_wrap=True)
        table.add_column("Query", style="white")
        table.add_column("Result", style="green")
        for r in results:
            table.add_row(r["trace_id"][:12], r["query"][:40], r["result"][:40])
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("templates")
def templates() -> None:
    """List available agent templates."""
    console = Console(stderr=True)
    try:
        from openjarvis.agents.manager import AgentManager

        tpls = AgentManager.list_templates()
        if not tpls:
            console.print("[dim]No templates found.[/dim]")
            return
        table = Table(title="Agent Templates")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Source", style="yellow")
        table.add_column("Description", style="white")
        for t in tpls:
            table.add_row(
                t.get("id", ""), t.get("name", ""),
                t.get("source", ""), t.get("description", "")[:60],
            )
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


def _get_system():
    """Build a JarvisSystem for CLI commands that need scheduler/executor."""
    from openjarvis.system import SystemBuilder
    try:
        return SystemBuilder().build()
    except RuntimeError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)


def _get_scheduler_and_executor(system=None):
    """Get scheduler + executor from a JarvisSystem instance."""
    if system is None:
        system = _get_system()
    return system.agent_scheduler, system.agent_executor, system


@agent.command()
def launch():
    """Interactive agent launcher."""
    from openjarvis.agents.manager import AgentManager as _AM
    templates = _AM.list_templates()
    click.echo("Available templates:")
    for i, t in enumerate(templates, 1):
        click.echo(f"  [{i}] {t['name']} — {t.get('description', '')}")
    click.echo(f"  [{len(templates) + 1}] Custom (from scratch)")
    choice = click.prompt("Select template", type=int, default=1)
    if choice <= len(templates):
        template = templates[choice - 1]
        name = click.prompt("Agent name", default=template["name"])
    else:
        template = None
        name = click.prompt("Agent name")
    schedule_type = click.prompt(
        "Schedule type",
        type=click.Choice(["cron", "interval", "manual"]),
        default="manual",
    )
    schedule_value = ""
    if schedule_type == "cron":
        schedule_value = click.prompt("Cron expression", default="0 9 * * *")
    elif schedule_type == "interval":
        schedule_value = click.prompt("Interval (seconds)", type=int, default=3600)
    max_cost = click.prompt("Budget limit ($, 0=unlimited)", type=float, default=0.0)
    config = {
        "schedule_type": schedule_type,
        "schedule_value": schedule_value,
        "max_cost": max_cost,
    }
    manager = _get_manager()
    if template:
        agent_data = manager.create_from_template(
            template["id"], name=name,
        )
        agent_config = agent_data.get("config", {})
        agent_config.update(config)
        manager.update_agent(agent_data["id"], config=agent_config)
        agent_data = manager.get_agent(agent_data["id"])
    else:
        agent_type = click.prompt("Agent type", default="monitor_operative")
        agent_data = manager.create_agent(
            name=name, agent_type=agent_type, config=config
        )
    click.echo(f"\nAgent \"{agent_data['name']}\" created (ID: {agent_data['id']})")


@agent.command("start")
@click.argument("agent_id")
def start_agent(agent_id):
    """Start scheduling an agent."""
    manager = _get_manager()
    agent_data = manager.get_agent(agent_id)
    if not agent_data:
        click.echo(f"Agent {agent_id} not found", err=True)
        raise SystemExit(1)
    scheduler, _, _ = _get_scheduler_and_executor()
    if scheduler is None:
        click.echo("Scheduler not available", err=True)
        raise SystemExit(1)
    scheduler.register_agent(agent_id)
    click.echo(f"Agent \"{agent_data['name']}\" registered with scheduler")


@agent.command("stop")
@click.argument("agent_id")
def stop_agent(agent_id):
    """Stop scheduling an agent."""
    manager = _get_manager()
    agent_data = manager.get_agent(agent_id)
    if not agent_data:
        click.echo(f"Agent {agent_id} not found", err=True)
        raise SystemExit(1)
    scheduler, _, _ = _get_scheduler_and_executor()
    if scheduler is None:
        click.echo("Scheduler not available", err=True)
        raise SystemExit(1)
    scheduler.deregister_agent(agent_id)
    click.echo(f"Agent \"{agent_data['name']}\" deregistered from scheduler")


@agent.command("run")
@click.argument("agent_id")
def run_agent(agent_id):
    """Run one tick immediately for testing."""
    manager = _get_manager()
    agent_data = manager.get_agent(agent_id)
    if not agent_data:
        click.echo(f"Agent {agent_id} not found", err=True)
        raise SystemExit(1)
    if agent_data["status"] == "archived":
        click.echo(f"Agent {agent_id} is archived and cannot be run", err=True)
        raise SystemExit(1)
    click.echo(f"Running tick for \"{agent_data['name']}\"...")
    _, executor, _ = _get_scheduler_and_executor()
    if executor is None:
        click.echo("Executor not available", err=True)
        raise SystemExit(1)
    try:
        executor.execute_tick(agent_id)
    except Exception as exc:
        click.echo(f"Tick failed: {exc}", err=True)
        raise SystemExit(1)
    updated = manager.get_agent(agent_id)
    runs = updated.get("total_runs", 0)
    click.echo(f"Tick complete. Status: {updated['status']}, runs: {runs}")


@agent.command("status")
def status():
    """Show all agents with schedule and run info."""
    import time as _time

    manager = _get_manager()
    agents = manager.list_agents()
    if not agents:
        click.echo("No agents found.")
        return
    header = (
        f"{'Agent':<20} {'Status':<16} {'Schedule':<12} "
        f"{'Runs':<5} {'Budget':<14} {'Last Seen':<12}"
    )
    click.echo(header)
    click.echo("-" * 79)
    for a in agents:
        cfg = a.get("config", {})
        sched = cfg.get("schedule_type", "manual")
        if sched == "cron":
            sched = cfg.get("schedule_value", "?")
        elif sched == "interval":
            sched = f"every {cfg.get('schedule_value', '?')}s"
        # Budget column
        max_cost = cfg.get("max_cost", 0)
        if max_cost > 0:
            pct = min(100, int(a.get("total_cost", 0) / max_cost * 100))
            budget = (
                f"${a.get('total_cost', 0):.2f}/{max_cost:.0f} ({pct}%)"
            )
        else:
            budget = f"${a.get('total_cost', 0):.2f}"
        # Last seen column
        last_act = a.get("last_activity_at")
        if last_act:
            ago = int(_time.time() - last_act)
            if ago < 60:
                last_seen = f"{ago}s ago"
            elif ago < 3600:
                last_seen = f"{ago // 60}m ago"
            else:
                last_seen = f"{ago // 3600}h ago"
        else:
            last_seen = "-"
        runs = a.get("total_runs", 0)
        click.echo(
            f"{a['name']:<20} {a['status']:<16} {sched:<12} "
            f"{runs:<5} {budget:<14} {last_seen:<12}"
        )


@agent.command("learning")
@click.argument("agent_id")
@click.option(
    "--run", "trigger_run", is_flag=True, help="Trigger manual learning run"
)
def learning(agent_id, trigger_run):
    """Show learning history or trigger a manual run."""
    import datetime

    manager = _get_manager()
    agent_data = manager.get_agent(agent_id)
    if not agent_data:
        click.echo(f"Agent {agent_id} not found", err=True)
        raise SystemExit(1)

    if trigger_run:
        click.echo(f"Triggering learning for \"{agent_data['name']}\"...")
        from openjarvis.core.events import EventType, get_event_bus

        bus = get_event_bus()
        bus.publish(
            EventType.AGENT_LEARNING_STARTED, {"agent_id": agent_id}
        )
        click.echo("Learning triggered.")
        return

    logs = manager.list_learning_log(agent_id)
    if not logs:
        click.echo(f"No learning history for \"{agent_data['name']}\"")
        return
    click.echo(f"Learning history for \"{agent_data['name']}\":")
    for entry in logs:
        ts = datetime.datetime.fromtimestamp(
            entry["created_at"]
        ).strftime("%Y-%m-%d %H:%M")
        click.echo(
            f"  {ts}  [{entry['event_type']}] "
            f"{entry.get('description', '')[:60]}"
        )


@agent.command("trace")
@click.argument("agent_id")
@click.option(
    "--run", "run_number", default=None, type=int,
    help="Specific run number",
)
@click.option("--limit", "-n", default=10, help="Number of traces to show")
def trace(agent_id, run_number, limit):
    """Show step-by-step trace of agent ticks."""
    import datetime

    from openjarvis.core.config import load_config
    from openjarvis.traces.store import TraceStore

    manager = _get_manager()
    agent_data = manager.get_agent(agent_id)
    if not agent_data:
        click.echo(f"Agent {agent_id} not found", err=True)
        raise SystemExit(1)

    config = load_config()
    store = TraceStore(
        config.traces.db_path or "~/.openjarvis/traces.db"
    )
    traces = store.list_traces(agent=agent_id, limit=limit)

    if not traces:
        click.echo(f"No traces for \"{agent_data['name']}\"")
        return

    if run_number is not None and 1 <= run_number <= len(traces):
        t = traces[run_number - 1]
        click.echo(
            f"Trace #{run_number} — {t.outcome} "
            f"({t.total_latency_seconds:.1f}s)"
        )
        for i, step in enumerate(t.steps, 1):
            click.echo(
                f"  Step {i}: [{step.step_type.value}] "
                f"{step.duration_seconds:.2f}s"
            )
            inp = str(step.input)[:80]
            out = str(step.output)[:80]
            click.echo(f"    In:  {inp}")
            click.echo(f"    Out: {out}")
    else:
        click.echo(f"Traces for \"{agent_data['name']}\":")
        for i, t in enumerate(traces, 1):
            ts = datetime.datetime.fromtimestamp(
                t.started_at
            ).strftime("%Y-%m-%d %H:%M")
            click.echo(
                f"  #{i}  {ts}  {t.outcome}  "
                f"{t.total_latency_seconds:.1f}s  "
                f"{len(t.steps)} steps"
            )


@agent.command("logs")
@click.argument("agent_id")
@click.option("--limit", "-n", default=10, help="Number of recent traces to show")
def logs(agent_id, limit):
    """Show recent execution traces for an agent."""
    import datetime

    manager = _get_manager()
    agent_data = manager.get_agent(agent_id)
    if not agent_data:
        click.echo(f"Agent {agent_id} not found", err=True)
        raise SystemExit(1)
    checkpoints = manager.list_checkpoints(agent_id)
    if not checkpoints:
        click.echo(f"No execution history for \"{agent_data['name']}\"")
        return
    click.echo(f"Recent runs for \"{agent_data['name']}\":")
    for cp in checkpoints[:limit]:
        ts = datetime.datetime.fromtimestamp(cp["created_at"]).strftime(
            "%Y-%m-%d %H:%M"
        )
        click.echo(f"  {cp['tick_id']}  {ts}")


@agent.command("daemon")
def daemon():
    """Run the agent scheduler as a standalone daemon."""
    import signal

    click.echo("Starting agent scheduler daemon...")
    system = _get_system()
    scheduler = system.agent_scheduler
    if scheduler is None:
        click.echo("Scheduler not available (agent_manager not configured)", err=True)
        raise SystemExit(1)
    manager = system.agent_manager
    for agent_data in manager.list_agents():
        cfg = agent_data.get("config", {})
        if cfg.get("schedule_type") in ("cron", "interval"):
            scheduler.register_agent(agent_data["id"])
    scheduler.start()
    n = len(scheduler.registered_agents)
    click.echo(f"Scheduler running ({n} agents). Ctrl+C to stop.")
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()
    scheduler.stop()
    system.close()
    click.echo("Daemon stopped.")


@agent.command("watch")
@click.argument("agent_id", required=False)
def watch(agent_id):
    """Live feed of agent activity."""
    import signal

    from openjarvis.core.events import EventType, get_event_bus

    click.echo("Watching agent events... (press Ctrl+C to stop)")
    bus = get_event_bus()
    agent_events = [
        EventType.AGENT_TICK_START, EventType.AGENT_TICK_END,
        EventType.AGENT_TICK_ERROR, EventType.AGENT_BUDGET_EXCEEDED,
    ]

    def _on_event(event):
        data = event.data or {}
        if agent_id and data.get("agent_id") != agent_id:
            return
        label = data.get("agent_name", data.get("agent_id", "?"))
        click.echo(f"  {label:<20} {event.event_type.value}")

    for et in agent_events:
        bus.subscribe(et, _on_event)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    stop.wait()


@agent.command("recover")
@click.argument("agent_id")
def recover(agent_id):
    """Recover an agent from its last checkpoint."""
    manager = _get_manager()
    checkpoint = manager.recover_agent(agent_id)
    if checkpoint:
        click.echo(f"Recovered from checkpoint {checkpoint['tick_id']}")
    else:
        click.echo("No checkpoint found for this agent", err=True)


@agent.command("errors")
def errors():
    """Show all agents in error or needs_attention state."""
    manager = _get_manager()
    agents = manager.list_agents()
    error_agents = [a for a in agents if a["status"] in ("error", "needs_attention")]
    if not error_agents:
        click.echo("No agents with errors.")
        return
    for a in error_agents:
        click.echo(f"  {a['name']} ({a['id'][:8]}): {a['status']}")


@agent.command("ask")
@click.argument("agent_id")
@click.argument("message")
def ask(agent_id, message):
    """Ask an agent a question (immediate response)."""
    manager = _get_manager()
    agent_id = _resolve_agent_id(manager, agent_id)
    manager.send_message(agent_id, message, mode="immediate")
    click.echo("Asking agent...")
    _, executor, _ = _get_scheduler_and_executor()
    if executor is None:
        click.echo("Executor not available", err=True)
        raise SystemExit(1)
    executor.execute_tick(agent_id)
    msgs = manager.list_messages(agent_id)
    responses = [m for m in msgs if m["direction"] == "agent_to_user"]
    if responses:
        click.echo(f"\nAgent: {responses[0]['content']}")
    else:
        click.echo("\n(No response from agent)")


@agent.command("instruct")
@click.argument("agent_id")
@click.argument("message")
def instruct(agent_id, message):
    """Queue an instruction for the agent's next tick."""
    manager = _get_manager()
    agent_id = _resolve_agent_id(manager, agent_id)
    msg = manager.send_message(agent_id, message, mode="queued")
    click.echo(f"Instruction queued (ID: {msg['id'][:8]})")


@agent.command("messages")
@click.argument("agent_id")
def messages(agent_id):
    """Show message history with an agent."""
    manager = _get_manager()
    msgs = manager.list_messages(agent_id)
    if not msgs:
        click.echo("No messages.")
        return
    for m in msgs:
        direction = "You" if m["direction"] == "user_to_agent" else "Agent"
        mode_badge = f" [{m['mode']}]" if m["direction"] == "user_to_agent" else ""
        click.echo(f"  {direction}{mode_badge}: {m['content'][:100]}")


__all__ = ["agent"]
