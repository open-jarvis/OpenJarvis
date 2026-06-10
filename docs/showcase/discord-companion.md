---
title: Discord Companion
description: Jarvis answers questions in your private Discord while you sleep — reads your notes, checks your calendar, schedules things
---

# 💬 Discord Companion — a personal assistant that lives in my Discord

<figure markdown>
  ![Jarvis answering a Discord DM about the user's calendar and notes](../assets/showcase/discord-companion.png){ .showcase-screenshot loading=lazy }
  <figcaption>I DM'd Jarvis from my phone at midnight. It checked my Google Calendar, cross-referenced a note from last week, and answered — running on the Mac mini in my closet.</figcaption>
</figure>

I have a private Discord server with two channels and one user (me). Jarvis lives there. I can DM it from my phone, my laptop, or my watch — anywhere Discord runs. Sample things I've asked it this week:

- "What's the address of the place I had that meeting last Tuesday?" → Jarvis searches my calendar + meeting notes, replies in 4 seconds.
- "Reply to Mom's text from earlier saying I'll call tomorrow at 7." → drafts a reply, asks me to confirm, sends.
- "Add 'Sam's birthday is March 12' to my long-term memory." → updates `MEMORY.md`, confirms.
- "Summarize the last hour of conversation in `#deploys-prod`." → reads the Slack channel via MCP, summarizes.

I used to use my phone's voice assistant for this. The two differences that matter: **Jarvis answers in three sentences, not one,** and **it actually has my context** — my notes, my calendar, my projects, my history.

## Why it's nice

- **Latency feels like talking to a person.** Local inference on a modest GPU is 5–10× faster than round-tripping to a cloud API. Question to answer in 3 seconds.
- **The Discord interface is multi-device for free.** Same conversation thread on my phone, laptop, watch — no special app to install.
- **It's already private.** A Discord server I run, talking to a model on a machine I own. The data trail is two endpoints I control.

## How I set this up

→ **[Tutorial: Messaging Hub](../tutorials/messaging-hub.md)** is the closest match — same channel-adapter + orchestrator-agent pattern, with Discord substituted for Slack.

→ **[Channel docs](../user-guide/cli.md)** walks through Discord/Slack/Telegram/WhatsApp setup. Discord is two environment variables and a bot token.

→ **[MCP integration guide](../user-guide/cli.md)** if you want Jarvis to reach into Notion, Linear, Gmail, etc.
