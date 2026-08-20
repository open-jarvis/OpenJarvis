---
title: Offline Code Reviewer
description: Review a pull request on a transatlantic flight, no internet required
---

# 🛠️ Offline Code Reviewer — code review on an airplane

<figure markdown>
  ![Jarvis reviewing a diff with no internet connection](../assets/showcase/coding-assistant.png){ .showcase-screenshot loading=lazy }
  <figcaption>Airplane mode in the menu bar. Jarvis reading a `git diff`, the surrounding files, and producing a code review at gate-level Wi-Fi (i.e., none).</figcaption>
</figure>

Earlier this month I was on a flight from SFO to FRA — eleven hours, no usable Wi-Fi. I had a teammate's pull request open in VS Code. I asked Jarvis to review it. It read the diff, read the three files the diff touched, read the project's `CLAUDE.md` for conventions, and produced a review with five comments — two of which caught real bugs.

The review took about 40 seconds on the laptop's built-in GPU. No API call. No "you're offline" error. By the time we landed I'd dropped the comments into GitHub and the PR was merging.

The same setup handles:

- **Code review** — diff + context files + conventions, structured comments.
- **Debugging** — paste a traceback, Jarvis reads the stack, opens the relevant files, suggests fixes.
- **Test generation** — point at a function, get back a `pytest` file with edge cases.
- **Documentation** — generate docstrings that actually match the code, because Jarvis has the file open.

## Why it's nice

- **It works on a plane.** Or a train, or a hotel with bad Wi-Fi, or your couch when Comcast is having a day. Same speed every time.
- **It sees your repo, not a sanitized chunk.** Cloud coding assistants make you upload a context window. The local one just reads `git status` and the files you're working on.
- **No "we trained on your code" question.** Your code never leaves your laptop. Period.

## How I set this up

→ **[Tutorial: Code Companion](../tutorials/code-companion.md)** walks through the ReAct-agent + git/file/shell tool stack this uses end-to-end.

→ **[User Guide: Code Assistant](../user-guide/code-assistant.md)** is the focused recipe walkthrough for daily-driver code review.

→ **[OpenAI-compatible server](../getting-started/quickstart.md)** — point your editor's existing AI integration (Cursor, Continue, Cody, Aider) at `localhost:8000`. They mostly don't know they're not talking to OpenAI.
