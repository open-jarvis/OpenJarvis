---
title: Memory That Doesn't Reset
description: Tell Jarvis something once. It remembers — three months later, across every conversation
---

# 🧠 Memory That Doesn't Reset — Jarvis actually knows me

<figure markdown>
  ![Jarvis remembering a user preference three months later](../assets/showcase/persistent-memory.png){ .showcase-screenshot loading=lazy }
  <figcaption>Three months after I mentioned the allergy in passing, Jarvis brings it up — unprompted — while helping me pick a birthday-dinner restaurant.</figcaption>
</figure>

I mentioned to Jarvis once, in a throwaway sentence in April, that I'm allergic to shellfish. In July, when I asked it to help me pick a restaurant for my partner's birthday, it volunteered "you'll want to filter for menus that have non-shellfish options" — without being reminded, in a totally different conversation, on a different topic.

That's not magic. The trick is that Jarvis writes to three plain markdown files in my home directory whenever it learns something worth remembering:

- `SOUL.md` — how I want it to behave (tone, length, what to push back on)
- `MEMORY.md` — facts about me, my projects, my preferences
- `USER.md` — who I am: my role, my team, my context

Every new conversation starts by reading those three files. I can open them in any text editor. I can delete a line and the memory is gone. The whole thing is `~6 KB` of markdown. No vector DB, no embedding cache, no opaque "personalization layer."

## Why it's nice

- **It's auditable.** I can read what Jarvis "knows" about me in 30 seconds. Most personal-AI products literally can't tell you.
- **It's portable.** I keep my three files in iCloud Drive. When I set up Jarvis on a new machine, my memory comes with me — without re-onboarding.
- **It compounds.** After two weeks Jarvis stopped re-asking what my code style is. After six weeks it stopped re-asking who's on my team. The conversations get shorter because the context is already there.
- **It can't drift.** Vector retrieval can confidently surface the wrong "memory" and you'd never know. Plain markdown that I can read can't lie about what it contains.

## How I set this up

→ **[User Guide: Agents](../user-guide/agents.md)** explains the persistent-agent pattern, including how `SOUL.md` / `MEMORY.md` / `USER.md` are loaded at conversation start.

→ **[Tutorial: Deep Research Assistant](../tutorials/deep-research.md)** uses the same persistent-memory primitive — a good place to see it in action with code.
