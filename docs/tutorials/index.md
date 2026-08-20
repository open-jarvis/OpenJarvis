---
title: Tutorials
description: Step-by-step guides for building with OpenJarvis
---

# Tutorials

Hands-on guides that walk through building real applications with OpenJarvis. Each tutorial includes a standalone script you can run immediately, a TOML recipe for configuration, and a detailed walkthrough of the concepts involved.

!!! note "Before you begin"
    All tutorials assume OpenJarvis is installed and an inference engine is running. If you have not completed setup yet, start with the [Quick Start guide](../getting-started/quickstart.md).

<div class="grid cards" markdown>

- :material-magnify:{ .lg .middle } **Deep Research Assistant**

    ---

    Multi-source research with a memory-augmented orchestrator agent. Searches the web, stores findings across turns, cross-references sources, and produces a cited report.

    [:octicons-arrow-right-24: Get started](deep-research.md)

- :material-clock-outline:{ .lg .middle } **Scheduled Personal Ops**

    ---

    Autonomous agents on cron schedules for recurring personal tasks — morning news digests, weekly code reviews, and gym schedule checks.

    [:octicons-arrow-right-24: Get started](scheduled-ops.md)

- :material-message-outline:{ .lg .middle } **Messaging Hub**

    ---

    Smart inbox assistant that triages messages by priority, drafts context-aware replies, and produces end-of-day summaries across Slack, WhatsApp, and other channels.

    [:octicons-arrow-right-24: Get started](messaging-hub.md)

- :material-code-braces:{ .lg .middle } **Code Companion**

    ---

    Code review, debugging, and test generation using a ReAct agent that reads source files, runs commands, and reasons step by step before producing structured output.

    [:octicons-arrow-right-24: Get started](code-companion.md)

- :material-puzzle:{ .lg .middle } **Skills Workflow**

    ---

    Install skills from Hermes Agent, use them with a local agent, discover patterns from traces, optimize with DSPy, and benchmark the impact — the complete skills lifecycle.

    [:octicons-arrow-right-24: Get started](skills-workflow.md)

</div>

## What You Will Learn

Each tutorial demonstrates a different combination of OpenJarvis primitives working together:

| Tutorial | Agent | Key Primitives |
|---|---|---|
| Deep Research | `orchestrator` | Engine, Agents, Tools (web + memory), Recipes |
| Scheduled Ops | `orchestrator`, `native_react` | Agents, Tools, Scheduler |
| Messaging Hub | `orchestrator` | Agents, Tools (memory), Channels |
| Code Companion | `native_react` | Agents, Tools (git + file + shell) |

## Estimated Time

Each tutorial takes approximately 15-30 minutes to complete end-to-end, including setup and running the scripts. The TOML configuration sections and customization tips are optional reading for when you adapt the pattern to your own use case.
