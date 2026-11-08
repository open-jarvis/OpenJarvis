#!/usr/bin/env python3
"""Smart Inbox — message triage and auto-reply with an orchestrator agent.

Usage:
    python examples/messaging_hub/smart_inbox.py --demo
    python examples/messaging_hub/smart_inbox.py --demo --model gpt-4o --engine cloud
    python examples/messaging_hub/smart_inbox.py --channel slack
"""

from __future__ import annotations

import sys

import click

DEMO_MESSAGES = [
    "URGENT: Server is down in production, need immediate help!",
    "Hey, just wanted to share this interesting article about AI agents.",
    "Can you review my PR #42 by end of day? It's blocking the release.",
    "Meeting reminder: Team standup at 10am tomorrow.",
    "Buy now! Limited time offer on premium widgets!!!",
]

CLASSIFICATION_PROMPT = (
    "You are a smart inbox assistant. Classify the following message into "
    "exactly one category: URGENT, ACTION_REQUIRED, FYI, or SPAM.\n"
    "Then draft a short reply if appropriate (not for SPAM).\n\n"
    "Respond in this exact format:\n"
    "CATEGORY: <category>\n"
    "REPLY: <reply or N/A>\n\n"
    "Message:\n{message}"
)

SUMMARY_PROMPT = (
    "You previously triaged the following messages and their classifications:\n\n"
    "{triage_log}\n\n"
    "Produce a concise end-of-day summary. Group by category "
    "(URGENT, ACTION_REQUIRED, FYI, SPAM) and highlight any items "
    "that still need attention."
)


def _parse_classification(response: str) -> tuple[str, str]:
    """Extract category and reply from the agent response."""
    category = "UNKNOWN"
    reply = "N/A"
    for line in response.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("CATEGORY:"):
            category = stripped.split(":", 1)[1].strip().upper()
        elif stripped.upper().startswith("REPLY:"):
            reply = stripped.split(":", 1)[1].strip()
    return category, reply


def _print_table(results: list[dict[str, str]]) -> None:
    """Print triage results as a formatted table."""
    # Column widths
    cat_w = max(len("Category"), max((len(r["category"]) for r in results), default=0))
    msg_w = min(
        50,
        max(len("Message"), max((len(r["message"]) for r in results), default=0)),
    )
    rep_w = min(
        40,
        max(len("Reply"), max((len(r["reply"]) for r in results), default=0)),
    )

    header = (
        f"  {'#':<3} {'Category':<{cat_w}}  {'Message':<{msg_w}}  {'Reply':<{rep_w}}"
    )
    separator = "  " + "-" * (len(header) - 2)

    click.echo()
    click.echo(header)
    click.echo(separator)

    for i, r in enumerate(results, 1):
        msg_display = r["message"][:msg_w]
        rep_display = r["reply"][:rep_w]
        row = (
            f"  {i:<3} {r['category']:<{cat_w}}"
            f"  {msg_display:<{msg_w}}  {rep_display:<{rep_w}}"
        )
        click.echo(row)

    click.echo(separator)
    click.echo()


def _run_demo(model: str, engine_key: str) -> None:
    """Process sample messages through the agent for classification."""
    try:
        from friday_ai import Friday
    except ImportError:
        click.echo(
            "Error: friday_ai is not installed. "
            "Install it with:  uv sync --extra dev",
            err=True,
        )
        sys.exit(1)

    tools = ["think", "memory_store", "memory_search"]

    click.echo("Smart Inbox — Demo Mode")
    click.echo(f"Model: {model}  |  Engine: {engine_key}")
    click.echo("=" * 60)
    click.echo(f"Processing {len(DEMO_MESSAGES)} messages...\n")

    try:
        j = Friday(model=model, engine_key=engine_key)
    except Exception as exc:
        click.echo(
            f"Error: could not initialize Friday — {exc}\n\n"
            "Make sure your engine is running. For Ollama:\n"
            "  ollama serve\n"
            "  ollama pull qwen3:8b\n\n"
            "For cloud engines, ensure API keys are set in your .env file.",
            err=True,
        )
        sys.exit(1)

    results: list[dict[str, str]] = []

    try:
        for idx, message in enumerate(DEMO_MESSAGES, 1):
            click.echo(f"  [{idx}/{len(DEMO_MESSAGES)}] Classifying: {message[:60]}...")

            prompt = CLASSIFICATION_PROMPT.format(message=message)
            response = j.ask(
                prompt,
                agent="orchestrator",
                tools=tools,
                temperature=0.3,
            )

            category, reply = _parse_classification(response)
            results.append(
                {"message": message, "category": category, "reply": reply}
            )
            click.echo(f"           -> {category}")

        # Print results table
        _print_table(results)

        # Generate end-of-day summary
        click.echo("Generating end-of-day summary...\n")
        triage_log = "\n".join(
            f"- [{r['category']}] {r['message']}" for r in results
        )
        summary_prompt = SUMMARY_PROMPT.format(triage_log=triage_log)
        summary = j.ask(
            summary_prompt,
            agent="orchestrator",
            tools=tools,
            temperature=0.3,
        )
        click.echo("End-of-Day Summary")
        click.echo("-" * 40)
        click.echo(summary)

    except Exception as exc:
        click.echo(f"Error during triage: {exc}", err=True)
        sys.exit(1)
    finally:
        j.close()


def _run_channel(channel: str, model: str, engine_key: str) -> None:
    """Connect to a real messaging channel for live triage.

    This mode requires channel credentials to be configured. See the
    README for setup instructions for each supported channel.
    """
    click.echo("Smart Inbox — Live Channel Mode")
    click.echo(f"Channel: {channel}  |  Model: {model}  |  Engine: {engine_key}")
    click.echo("=" * 60)
    click.echo()

    # Channel setup guidance
    setup_help = {
        "slack": (
            "To set up Slack:\n"
            "  1. Run: friday add slack\n"
            "  2. Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN in your .env\n"
            "  3. Invite the bot to your target channel\n"
        ),
        "whatsapp": (
            "To set up WhatsApp:\n"
            "  1. Ensure Node.js 22+ is installed\n"
            "  2. Configure WhatsApp Baileys bridge (see channel docs)\n"
            "  3. Scan the QR code to authenticate\n"
        ),
    }

    help_text = setup_help.get(
        channel,
        f"Channel '{channel}' requires appropriate credentials.\n"
        f"Run: friday channel list   to see available channels.\n",
    )

    click.echo(help_text)
    click.echo(
        "Once configured, incoming messages will be triaged automatically.\n"
        "Use --demo to test with sample messages without channel setup.\n"
    )

    # Demonstrate how the channel integration would work
    click.echo("Example integration code:\n")
    click.echo("  from friday_ai import Friday")
    click.echo(f'  j = Friday(model="{model}", engine_key="{engine_key}")')
    click.echo("  # Listen for incoming messages on the channel")
    click.echo(f'  # See: friday channel status  (to verify "{channel}" is connected)')
    click.echo('  response = j.ask(message, agent="orchestrator",')
    click.echo('                   tools=["think", "memory_store", "memory_search"])')
    click.echo()


@click.command()
@click.option(
    "--channel",
    default="slack",
    show_default=True,
    help="Messaging channel to connect to (slack, whatsapp, etc.).",
)
@click.option(
    "--model",
    default="qwen3:8b",
    show_default=True,
    help="Model to use for message triage.",
)
@click.option(
    "--engine",
    "engine_key",
    default="ollama",
    show_default=True,
    help="Engine backend (ollama, cloud, vllm, etc.).",
)
@click.option(
    "--demo",
    is_flag=True,
    default=False,
    help="Run in demo mode with sample messages (no channel required).",
)
def main(channel: str, model: str, engine_key: str, demo: bool) -> None:
    """Smart inbox assistant — classify and reply to messages.

    Processes incoming messages through an orchestrator agent that classifies
    each message as URGENT, ACTION_REQUIRED, FYI, or SPAM, drafts concise
    replies, and stores key information for end-of-day summaries.

    \b
    Demo mode (no engine required for --help):
        python examples/messaging_hub/smart_inbox.py --demo

    \b
    Live channel mode:
        python examples/messaging_hub/smart_inbox.py --channel slack
    """
    if demo:
        _run_demo(model, engine_key)
    else:
        _run_channel(channel, model, engine_key)


if __name__ == "__main__":
    main()
