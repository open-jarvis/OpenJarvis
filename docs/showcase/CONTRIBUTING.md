---
title: Contributing a Showcase Entry
description: How to add your setup to the OpenJarvis Showcase
---

# Contributing a Showcase Entry

The Showcase exists for one reason: to help a confused, curious, *non-technical* reader figure out whether OpenJarvis is worth their weekend. That goal sets every editorial choice on this page.

## The format

```markdown
---
title: <Your Title — short, capitalized>
description: <One sentence. The hook a stranger sees in search results.>
---

# <emoji> <One-sentence hook — what it does FOR you, in plain English>

<figure markdown>
  ![<alt text>](../assets/showcase/<your-image>.png){ .showcase-screenshot loading=lazy }
  <figcaption>A one-sentence caption that adds context the image can't show on its own.</figcaption>
</figure>

<2–3 short paragraphs of context: when do you use this, what changed for
you, what the experience feels like. Concrete > abstract. "I read it on
my phone before coffee" > "improves morning productivity."

A bulleted list of two or three CONCRETE OUTCOMES works well — your
calendar, your inbox, your code. Specific verbs and proper nouns.>

## Why it's nice

- **<one-line benefit>.** <one or two sentences of evidence>
- **<one-line benefit>.** <one or two sentences of evidence>
- **<one-line benefit>.** <one or two sentences of evidence>

## How I set this up

→ **[Tutorial: <name>](../tutorials/<file>.md)** is the closest match.

→ **[Recipe: <name>](https://github.com/open-jarvis/OpenJarvis/tree/main/src/openjarvis/recipes/data)** if you want the exact config.

→ **[<one more related doc>](../<path>.md)** if the reader is going deeper.
```

## Editorial conventions

These are guardrails, not rules. Break them if you have a reason.

### Lead with the outcome, not the technology

❌ "Multi-channel routing with MCP-backed memory and an orchestrator agent."<br>
✅ "Jarvis answers my Discord messages while I sleep."

The reader doesn't know what an "orchestrator agent" is yet. They know what a Discord message is.

### Show one screenshot. Make it the headline.

A single, large, *interesting* screenshot beats five small ones. Crop it to show the result, not the UI chrome. If you can convey it in an image, don't write the paragraph.

**Screenshot specs:**

- 1600×1000 PNG, sRGB, no alpha
- File path: `docs/assets/showcase/<your-slug>.png`
- Redact: real email addresses, API keys, personal phone numbers, conversation partners' faces or full names (unless they've signed off)
- Keep: model names, timestamps, dollar amounts, emoji reactions, your own first name

### Specific over impressive

❌ "Saves significant time every morning."<br>
✅ "Cut my morning catch-up from 25 minutes to 2."

Numbers, durations, dollar amounts, and named tools build trust. Adjectives don't.

### Three paragraphs is plenty

A reader who wants more clicks the "How I set this up →" link at the bottom. Showcase pages are a funnel into the docs, not a replacement for them. If you find yourself explaining configuration in the showcase entry, that material belongs in the linked tutorial.

### "Why it's nice" is for the experience, not the architecture

The bullets under **Why it's nice** should answer "what's different *for you*?" — not "what's different about how the framework works?". Save the architecture talk for the linked docs.

❌ "Uses local SQLite for state with WAL mode for concurrent reads."<br>
✅ "I can read my own memory file in a text editor. I can delete a line and the memory is gone."

### Every entry must end with at least one "How I set this up →" link

If there isn't a relevant tutorial yet, link to the closest [User Guide](../user-guide/cli.md) and open an issue noting that the tutorial is missing. We will write it.

## Submitting

1. **Fork** the repo and create a branch: `docs/showcase-<your-slug>`.
2. **Add** your markdown file at `docs/showcase/<your-slug>.md` and screenshot at `docs/assets/showcase/<your-slug>.png`.
3. **Add a tile** to the grid in `docs/showcase/index.md` (matches the existing pattern — emoji + title + 1-sentence summary + `[:octicons-arrow-right-24: See it](<your-slug>.md)`).
4. **Open a PR** with the title `docs(showcase): <your title>`. Tag a maintainer if you'd like editorial feedback before merge.

## Where this goes after merge

Hannah and the docs team post merged showcase entries to **`#config-showcase`** in [the OpenJarvis Discord](https://discord.gg/openjarvis). You'll get tagged in the post — you don't have to do it yourself.

## Questions, drafts, half-finished ideas

Drop them in **`#config-showcase`** on Discord *before* opening a PR. Editorial feedback is faster on chat than in a PR review, and you'll save yourself a round of revisions.
