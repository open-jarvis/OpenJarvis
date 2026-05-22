# Interactive CLI model and runtime picker (TUI)

Optional terminal UX for `jarvis chat` and bare `jarvis` on an interactive TTY.
Upstream previously relied on `default_model` in config or `-m` / `--model` only.

## Who may find this useful

- Local Ollama users who switch models often and want a numbered list at session start.
- People tuning context window or GPU layer offload per session without editing config.
- Power users who keep presets in `[intelligence]` (`model_chat`, `model_long`, etc.) but
  still want to override interactively sometimes.

Non-interactive use (CI, pipes, scripts) is unchanged when stdin is not a TTY or when
skip env vars are set.

## Behavior

### Model picker

On a TTY (unless skipped):

1. Lists models from the active engine (`engine.list_models()` — for Ollama, live `/api/tags`).
2. User picks by index, exact id, or Enter to fall back to config.
3. Resolution order after picker: `-m` / `--model` → `model_*` preset → `default_model` → first discovered model.
4. `-m smart` uses the variant preset (e.g. `model_chat`) like a named default.

Skip picker:

- `JARVIS_SKIP_MODEL_PICK=1`
- `jarvis chat` without bare `jarvis` (picker only auto-runs on bare `jarvis` unless `--pick-model`)
- `jarvis chat --pick-model` forces the list

### Runtime panel (Ollama-focused)

After model selection, optional prompts:

- **num_ctx** — context tokens (capped at 200,000)
- **num_gpu** — GPU layers (-1 = all, 0 = CPU); only shown for engine `ollama`

Skip panel:

- `JARVIS_SKIP_RUNTIME_PANEL=1`
- `--skip-runtime-panel`
- `--num-ctx` / `--num-gpu` (values applied directly, no prompts)

Session summary appears in the chat banner (`Runtime: ctx=…, gpu=…`). In-chat `/runtime` shows current values.

### Config additions

```toml
[intelligence]
default_model = "qwen3.5:4b"
model_chat = ""
model_short = ""
model_long = ""
model_code = ""
```

## Security notes

- Model ids from TTY/CLI are sanitized (control characters stripped, max length 512).
- Picker accepts only ids present in the engine list (no free-form path-like strings).
- Runtime kwargs forwarded to the engine are limited to `num_ctx` and `num_gpu`.
- Agent `engine_options` are filtered to the same allowlist before `engine.generate()`.

## Related commands

| Command | Role |
|---------|------|
| `jarvis model list` | Inspect models without starting chat |
| `jarvis chat -m MODEL` | Skip picker, fixed model |
| `jarvis chat --num-ctx N --num-gpu N` | Skip runtime panel |
