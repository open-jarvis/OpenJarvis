# Phase 1 – OpenJarvis Windows baseline

Date: 2026-07-29

## Scope and safety

This baseline was produced in the new repository only:

`C:\Users\Playe\Documents\JARVIS\openjarvis-codex`

The legacy `jarvis-desktop` working tree, its runtime data, its untracked files, and
the real Obsidian vault were not accessed during Phase 1. No migration was attempted.
A backup and restore proof that includes untracked files remains a hard gate before
any future migration access.

No OpenJarvis source or test file was changed for this baseline.

## Git baseline

| Item | Value |
|---|---|
| Integration branch | `feature/codex-jarvis-orchestrator` |
| Integration HEAD | `1fa80d8ecd2e043cb61fdc8310f9f7ffef83698c` |
| Release tags at the commit | `v1.0.3`, `desktop-v1.0.3`, `v1.0.3.dev862` |
| Upstream fetch URL | `https://github.com/open-jarvis/OpenJarvis.git` |
| Upstream push URL | `DISABLED` |
| Upstream default branch | `main` |
| Upstream `main` observed during setup | `ed01ab8c8d907015382dd200633ae4e34f0a39dc` |
| Personal `origin` | not configured; no fork URL was supplied |

The integration branch deliberately has no remote tracking branch. The local `main`
tracks `upstream/main`; no work is performed on `main`.

## Toolchain

| Component | Version or state |
|---|---|
| Python | 3.11.9 |
| OpenJarvis | 1.0.3, editable checkout |
| uv | 0.12.0 |
| Rust | 1.88.0 |
| Cargo | 1.88.0 |
| Node.js | 24.13.1 |
| Git | 2.53 |
| Codex CLI | 0.145.0 |
| Python environment | repository-local `.venv` |
| Python packages | 87; see [installed-packages.txt](installed-packages.txt) |

`uv` and Rust were bootstrapped outside the repository under the Phase 1 work
directory. Neither installer changed the global `PATH`. The Rust installer was
verified against the official SHA-256 file before execution:

`86478E53F769379D7F0EBFA7C9AA97CB76CA92233F79AA2CC0DBEE2EFAAC73C7`

Installed locked extras:

- `dev`
- `framework-comparison`
- `server`

Not installed:

- browser/Playwright;
- Docker sandbox;
- WSL tooling;
- local inference engines or models;
- cloud-provider extras;
- GPU-specific inference stacks;
- speech and desktop extras.

These are intentionally outside the Phase 1 baseline.

## Dependency installation

The documented contributor command was first executed without additional extras:

```powershell
uv sync --extra dev --frozen
```

This installed 81 packages successfully. The first complete test collection then
failed because an unguarded comparison test imports `polars`, while `polars` is not
part of the documented `dev` extra.

The environment was therefore aligned with the repository CI:

```powershell
uv sync --extra dev --extra framework-comparison --extra server --frozen
uv pip check --python .venv\Scripts\python.exe
```

Result:

```text
Checked 87 packages
All installed packages are compatible
```

No lock file changed.

## Test results

### 1. Contributor-guide test command, first run

Command:

```powershell
uv run pytest tests/ -v
```

Result:

- exit code 1 during collection;
- 6,989 items found before interruption;
- 27 collection skips;
- one collection error;
- duration 58.17 seconds;
- cause: `polars` missing from the documented `dev` installation.

The error points to
`tests/evals/comparison/test_export_to_table_gen_roundtrip.py` and explicitly asks
for the `framework-comparison` extra.

### 2. Contributor-guide test command after adding the missing extra

The exact serial command was repeated without changing source or test selection.

Result:

- 7,009 test items collected;
- 26 collection skips reported;
- exit code 1;
- duration 1,497.4 seconds (24 minutes 57.4 seconds);
- 204 failed/error node IDs recorded by Pytest after the run.

The direct verbose output exceeded the terminal capture limit. A compact last-failed
rerun confirmed that the dominant categories were the missing mandatory Rust module,
Windows/POSIX assumptions, and tests that invoke unavailable live components.

### 3. CI-aligned marker-filtered suite

Command:

```powershell
uv run pytest tests/ -n auto -q --tb=short -m "not live and not cloud and not hub"
```

Result:

```text
6929 passed
175 failed
10 errors
67 skipped
68 warnings
190.67 seconds
```

This is the most representative complete Windows baseline result. It uses the same
marker selection and parallelization as the main upstream CI test lane, but the
mandatory Rust extension could not be built locally.

### 4. Upstream Windows-specific CI block

Command:

```powershell
uv run pytest tests/hardware/test_hardware_profiles.py tests/cli/test_cli.py `
  -v -m "not live and not cloud"
```

Result:

```text
28 passed
2 skipped
14.09 seconds test time
23.6 seconds process time
```

The skipped cases are the Darwin- and Linux-specific RAM probes. The Windows
`GlobalMemoryStatusEx` RAM path and UTF-8 CLI startup path passed.

### 5. Lint

Command:

```powershell
uv run ruff check src/ tests/
```

Result:

```text
All checks passed!
```

## Rust extension build

OpenJarvis makes `openjarvis_rust` mandatory for SQLite memory and several security
modules.

The repository CI uses:

```powershell
uv run maturin develop --manifest-path rust/crates/openjarvis-python/Cargo.toml
```

On the locally created uv environment this first fails because the environment has no
`pip` module:

```text
Failed to find pip (if working with a uv venv try `maturin develop --uv`)
```

The diagnostic uv-compatible command is:

```powershell
uv run maturin develop --uv `
  --manifest-path rust/crates/openjarvis-python/Cargo.toml
```

After exposing the isolated `uv` and Cargo executables to that process, compilation
starts and then fails reproducibly:

```text
error: linker `link.exe` not found
the msvc targets depend on the msvc linker but `link.exe` was not found
```

No Visual Studio installation, `vswhere.exe`, `cl.exe`, or `link.exe` is present.
Completing the Rust build requires Visual Studio 2017 or later, or Visual Studio Build
Tools with the Visual C++ workload. Installing that system toolchain is intentionally
not performed silently as part of this baseline.

## Start smoke test

| Probe | Result |
|---|---|
| `import openjarvis` | pass, version 1.0.3 |
| `jarvis --version` | pass, `jarvis, version 1.0.3` |
| `jarvis --help` | pass |
| `jarvis serve --help` | pass |
| `import openjarvis_rust` | fail, module not built |
| full API service start | blocked before a meaningful smoke test |

The CLI startup smoke test matches the upstream Windows CI smoke step.

A full API server start is not claimed: server initialization applies
`setup_security()`, which constructs Rust-backed scanners, and also requires an
available inference engine. Neither the Rust extension nor a local inference engine
is available in this Phase 1 environment.

## Existing failure classes

### A. Missing mandatory Rust extension

This is the dominant failure class. It affects:

- SQLite/FTS memory backends and memory CLI;
- secret and PII scanning;
- prompt-injection scanning;
- rate limiting;
- capability policy persistence;
- guardrails;
- loop guards and several server-memory routes;
- direct Rust bridge tests.

Representative exception:

```text
ModuleNotFoundError: No module named 'openjarvis_rust'
```

This is an environment blocker caused by the missing MSVC linker, not a Codex
integration regression.

### B. Optional or external services used by unmarked tests

Dense-storage tests call:

`http://localhost:11434/api/embed`

The endpoint returns `404 Not Found`; no supported local embedding model is configured.
These tests are not excluded by the normal `not live/cloud/hub` selection and produce
six setup errors plus related failures.

The completely unfiltered contributor-guide run also includes:

- live connectors;
- live skill integration;
- Gemma C++ inference;
- external framework runners.

These should be capability- or marker-gated on a minimal Windows baseline.

### C. POSIX assumptions on native Windows

Reproduced cases:

- assertions for Unix file modes `0600` and directory modes `0700`;
- `os.setsid` in the subprocess sandbox;
- shell template execution that assumes a POSIX executable/shell;
- RAPL/sysfs tests that create names such as `intel-rapl:0`, invalid as Windows
  directory names;
- forward-slash string assertions for generated paths;
- TOML fixtures that interpolate Windows backslashes into basic strings without
  escaping them.

These are test/code portability issues. Windows ACLs, process groups, shell invocation,
path serialization, and telemetry need native implementations or explicit platform
skips.

### D. Other reproducible baseline issues

- Background installer-state tests do not find their expected model state on Windows.
- A server construction test receives `memory_backend=None` while the Rust memory
  implementation is unavailable.
- The WhatsApp bridge bootstrap raises `WinError 2` while looking for its external
  Node/npm command.
- The OpenClaw contract runner's Node child aborts in this host environment at
  `ncrypto::CSPRNG`.
- Several display, persona, trial-output, and recipe tests compare POSIX-formatted
  paths to native Windows paths.
- FastAPI reports deprecation warnings for `on_event`; this contributes to the 68
  warnings but is not a startup blocker.

No Phase 1 source fix was applied to any of these existing issues.

## Windows capabilities currently unavailable or degraded

| Capability | State | Reason |
|---|---|---|
| Rust-backed SQLite/FTS memory | unavailable | MSVC linker absent |
| Rust-backed scanners/guardrails | unavailable | MSVC linker absent |
| Full API server | blocked | mandatory Rust security plus no inference engine |
| Unix permission enforcement | not equivalent | Windows ACL model differs |
| POSIX process-group sandbox | unavailable | no `os.setsid` |
| Linux RAPL energy telemetry | unavailable | no sysfs/RAPL |
| WSL shell tools | unavailable | WSL not installed |
| Docker sandbox/tools | unavailable | Docker not installed |
| Browser automation | not installed | optional browser extra deferred |
| Local LLM/embedding service | unavailable | no configured Ollama/model |
| Cloud inference | intentionally unavailable | no cloud extras or credentials |
| External live connectors | intentionally unavailable | no service credentials |

The Windows hardware detection and core CLI paths are available and tested.

## Generated or changed files

Tracked additions created by Phase 1:

- `docs/baseline/phase-1-windows-baseline.md`
- `docs/baseline/installed-packages.txt`

Generated but Git-ignored:

- `.venv/` – isolated Python environment;
- `.pytest_cache/` – test collection and last-failed cache;
- `rust/target/` – partial Cargo build output.

Repository-local Git metadata changed:

- remote `origin` was renamed to `upstream`;
- upstream push URL was set to `DISABLED`;
- branch `feature/codex-jarvis-orchestrator` was created at the approved commit.

External Phase 1 work artifacts:

- isolated uv bootstrap environment;
- isolated Rust/Cargo homes and verified rustup installer.

No lock file, source file, test file, real vault file, or legacy JARVIS file changed.

## Phase 2 – planned Codex backend work

Phase 2 should begin with small, testable modules following the OpenJarvis registry and
optional-dependency patterns:

```text
src/openjarvis/codex/
  __init__.py
  backend.py
  config.py
  sdk_backend.py
  app_server_backend.py
  cli_fallback.py
  event_adapter.py
  health.py

src/openjarvis/agents/
  codex_agent.py

tests/codex/
  test_backend_contract.py
  test_sdk_backend.py
  test_app_server_backend.py
  test_cli_fallback.py
  test_event_adapter.py
  test_health.py
```

Planned sequence:

1. Add a validated backend contract and capability model.
2. Add `openai-codex` as a justified optional dependency.
3. Implement the primary `AsyncCodex` backend.
4. Require explicit `ApprovalMode.deny_all` and explicit sandbox selection.
5. Reuse external Codex authentication and expose only a redacted
   `codex login status` health result.
6. Persist thread IDs and support start/resume/fork/interrupt/steer.
7. Add the App Server stdio transport for full history, streaming items, and
   interactive approvals.
8. Retain a read-only, ephemeral CLI fallback.
9. Normalize all backend events before publishing them to OpenJarvis traces.
10. Use fakes/recorded protocol messages for tests; do not consume an account in unit
    tests.

Before relying on OpenJarvis memory or security as a production foundation, the Rust
build prerequisite must be resolved or a reviewed prebuilt Windows artifact must be
used.
