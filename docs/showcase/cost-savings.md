---
title: Track Your Savings
description: A leaderboard that tells you exactly how much you saved by running locally
---

# 💸 Track Your Savings — the leaderboard that makes local-first feel real

<figure markdown>
  ![OpenJarvis savings leaderboard with personal row highlighted](../assets/showcase/cost-savings.png){ .showcase-screenshot loading=lazy }
  <figcaption>The public leaderboard. The bar on the right is what a month of my Jarvis usage would have cost on the cloud — measured per-query, not estimated.</figcaption>
</figure>

OpenJarvis tracks every inference call you make — the tokens, the latency, the GPU energy — and computes what that same call *would have cost* on OpenAI, Anthropic, Google, and Bedrock. There's a public leaderboard at **[/leaderboard](../leaderboard.md)** where anyone running Jarvis can opt in and watch their savings rack up.

My current month is roughly:

| | |
|---|---|
| Local inference cost | **`$0.00`** |
| Cloud-equivalent cost | **`$342.18`** (Claude Sonnet 4.6 baseline) |
| Energy used | **`1.4 kWh`** (~12¢ of grid power) |
| Prompts sent to a third party | **`0`** |

The dollar number is the hook. The bottom row is the actual reason I run Jarvis.

## Why it's nice

- **You can see what each query costs you.** Not estimated, not "roughly" — measured. Watt-hours per token, FLOPs per token, latency. Every primitive in OpenJarvis treats compute cost as a first-class quantity alongside accuracy.
- **It makes "local-first" stop being abstract.** Watching a bar chart accumulate `$X` a week that *didn't* leave your hands is a different kind of motivating than "your data is private" claims that you can't verify.
- **Privacy stops being an act of faith.** Every prompt I send to Jarvis can be traced through the codebase to local-only paths. No "cloud failover" hiding behind a switch.

## How I set this up

You don't, really — it's on by default. Every `jarvis ask`, `jarvis serve` request, and channel-routed message is metered by the [telemetry system](../telemetry.md). To opt your savings into the public leaderboard:

→ **[Leaderboard guide](../leaderboard.md)** — one command to opt in, one command to opt out. Telemetry is local-only by default.

→ **[Telemetry overview](../telemetry.md)** — what's measured, where it's stored, and how to inspect it yourself with `jarvis telemetry`.
