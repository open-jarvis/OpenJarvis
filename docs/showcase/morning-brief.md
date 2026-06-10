---
title: Morning Brief
description: Slack, email, GitHub, and calendar — summarized into a 5-bullet brief on your phone by 7am
---

# ☕ Morning Brief — Jarvis reads everything overnight so I don't have to

<figure markdown>
  ![Morning brief in Discord](../assets/showcase/morning-brief.png){ .showcase-screenshot loading=lazy }
  <figcaption>The 7am brief that arrives in my private Discord — 5 bullets, two minutes to read, written by an agent that ran on my desk while I slept.</figcaption>
</figure>

Every morning at 7am, before my first coffee, a message appears in my private Discord with five bullets:

- what shipped at work overnight (GitHub releases + merged PRs)
- the two emails I actually need to act on (with one-line summaries)
- anything mentioned in my team's `#general` Slack channel
- today's calendar with the next 24 hours of meetings
- one thing I asked Jarvis to track for me ("did Tuesday's deploy roll out cleanly?")

It's the first thing I read on my phone, while I'm still in bed. The brief used to take me 25 minutes — opening four apps, scrolling, deciding what mattered. Now it's two minutes of reading and I'm done.

## Why it's nice

- **Costs me nothing per month.** It runs on a Mac mini in my closet. Same prompt-volume on the OpenAI API would be `~$18/month` based on the leaderboard's estimates.
- **Nothing leaves my house.** My inbox, my Slack DMs, my calendar — Jarvis reads them locally and writes the digest locally. The only network call is the Discord webhook to my own private server.
- **It learns my taste.** Over a few weeks Jarvis figured out that PR titles starting with `chore:` aren't worth surfacing and that I don't want to see calendar holds I created myself. The summarizer has a `MEMORY.md` it updates when I react with 👎 to a bullet.

## What you'd need

A laptop or mini-PC that stays on overnight, an inference engine (Ollama is the easy default), accounts on whichever surfaces you want summarized (Slack, Gmail, GitHub, Google Calendar), and a Discord (or Slack, or Telegram, or email) destination to post the brief to.

## How I set this up

→ **[Tutorial: Scheduled Personal Ops](../tutorials/scheduled-ops.md)** walks through the cron-scheduled agent pattern this uses. The morning-brief flavour is `orchestrator` agent + the channel adapters + the scheduler primitive — three primitives, one TOML recipe.

→ **[User Guide: Morning Digest](../user-guide/morning-digest.md)** is the focused recipe walkthrough if you only want this one workflow.

→ **[User Guide: Channels](../user-guide/cli.md)** for connecting Discord/Slack/Telegram as the destination.
