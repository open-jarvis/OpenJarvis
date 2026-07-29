# Phase 1.5 — Windows Native Build Readiness

Date: 2026-07-29
Platform: Windows 10.0.26200, x86-64
Repository: `C:\Users\Playe\Documents\JARVIS\openjarvis-codex`

## 1. Git baseline and repository status

The approved OpenJarvis source baseline remains:

```text
1fa80d8ecd2e043cb61fdc8310f9f7ffef83698c
```

The two Phase 1 baseline documents were reviewed as the complete staged diff,
passed `git diff --cached --check`, and were committed without source changes:

```text
95990a8286948ca53e63b67ed65063413f7bb8ac
docs: record Windows OpenJarvis baseline
```

The active branch is:

```text
feature/codex-jarvis-orchestrator
```

Remote policy:

```text
upstream (fetch): https://github.com/open-jarvis/OpenJarvis.git
upstream (push):  DISABLED
```

No push was performed. The legacy `jarvis-desktop` project and the real
Obsidian vault were not accessed or modified during Phase 1.5.

At the end of the work, the only intended untracked repository files are:

```text
docs/baseline/phase-1-5-msvc-install-plan.md
docs/baseline/phase-1-5-windows-native-build-readiness.md
```

The virtual environment, Rust target tree, and pytest cache are ignored
generated content. There are no tracked source-code modifications.

## 2. External recovery bundle

An external, complete Git recovery bundle was created after the Phase 1
documentation commit:

```text
C:\Users\Playe\Documents\Codex\2026-07-29\der-agent-soll-bevorzugt-den-python\outputs\phase-1-5\recovery\openjarvis-baseline-95990a82.bundle
```

Properties:

```text
Size:   79,181,039 bytes
SHA256: F954CE53A78B97590CA210F8BA963709C0608CD5F33CA1272174B9431B75F801
```

`git bundle verify` reported a valid bundle with complete history, 92 refs,
and `95990a8286948ca53e63b67ed65063413f7bb8ac` as `HEAD`.

## 3. Microsoft Build Tools installation

Preflight found no existing Visual Studio Build Tools product, Visual Studio
Installer, `vswhere.exe`, `cl.exe`, or Microsoft linker on `PATH`.

The official Visual Studio Build Tools 2022 bootstrapper was downloaded from:

```text
https://aka.ms/vs/17/release/vs_BuildTools.exe
```

Bootstrapper verification:

```text
File version: 17.14.37516.0
Size:         4,458,504 bytes
SHA256:       CE7BB977ACCAE1748191233D05EE6832A4B61A319419627BFCDBD818DE5BFD68
Signature:    Valid, Microsoft Corporation
```

The installation used a passive, non-restarting, cache-free command with an
explicit minimal native workload:

```text
vs_BuildTools.exe --passive --wait --norestart --nocache
  --installPath "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
  --add Microsoft.VisualStudio.Workload.VCTools
  --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64
  --add Microsoft.VisualStudio.Component.Windows11SDK.26100
```

No `--includeRecommended` or `--includeOptional` expansion was used.

Installed product:

```text
Visual Studio Build Tools 2022 17.14.37 (July 2026)
Installation version 17.14.37516.0
Current Release channel
Installation state: complete and launchable
Reboot required: no
```

Selected package and workload records:

| Component | Version | Reason |
| --- | --- | --- |
| `Microsoft.Component.MSBuild` | 17.14.36510.44 | Required |
| `Microsoft.VisualStudio.Component.CoreBuildTools` | 17.14.36510.44 | Required |
| `Microsoft.VisualStudio.Component.Roslyn.Compiler` | 17.14.36510.44 | Required |
| `Microsoft.VisualStudio.Component.TextTemplating` | 17.14.36510.44 | Required |
| `Microsoft.VisualStudio.Component.VC.CoreBuildTools` | 17.14.36510.44 | Required |
| `Microsoft.VisualStudio.Component.VC.CoreIde` | 17.14.36510.44 | Required workload component |
| `Microsoft.VisualStudio.Component.VC.Redist.14.Latest` | 17.14.36510.44 | Required |
| `Microsoft.VisualStudio.Component.VC.Tools.x86.x64` | 17.14.36510.44 | Explicit |
| `Microsoft.VisualStudio.Component.Windows10SDK` | 17.14.36510.44 | Required UCRT component |
| `Microsoft.VisualStudio.Component.Windows11SDK.26100` | 17.14.37011.9 | Explicit |
| `Microsoft.VisualStudio.ComponentGroup.NativeDesktop.Core` | 17.14.36510.44 | Required |
| `Microsoft.VisualStudio.Product.BuildTools` | 17.14.37516.0 | Product |
| `Microsoft.VisualStudio.Workload.MSBuildTools` | 17.14.36015.10 | Required |
| `Microsoft.VisualStudio.Workload.VCTools` | 17.14.36331.10 | Explicit |

MFC, ATL, the full Visual Studio IDE, and ARM/ARM64 MSVC compiler toolchains
were not selected. The monolithic Windows SDK itself contains
architecture-neutral and multi-architecture SDK material; this does not mean
that an ARM compiler workload was installed.

The main installer log is:

```text
C:\Users\Playe\AppData\Local\Temp\dd_setup_20260729233349.log
```

## 4. Disk-space impact

Before installation, the system drive had approximately 43.2 GiB free.
The measured installation delta was:

```text
5,747,212,288 bytes (approximately 5.35 GiB)
```

After installation, the system drive had approximately 37.59 GiB free.

## 5. Native toolchain proof

The environment was loaded process-locally with:

```text
C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat
  -arch=x64 -host_arch=x64
```

No permanent system or user `PATH` change was made.

Verified values:

```text
VSCMD_ARG_HOST_ARCH=x64
VSCMD_ARG_TGT_ARCH=x64
VCToolsVersion=14.44.35207
WindowsSDKVersion=10.0.26100.0

cl.exe:
C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe
Microsoft C/C++ Optimizing Compiler 19.44.35228 for x64

link.exe:
C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\link.exe
Microsoft Incremental Linker 14.44.35228.0

rustc 1.88.0 (6b00bc388)
host: x86_64-pc-windows-msvc
LLVM 20.1.5

cargo 1.88.0 (873a06493)
Python 3.11.9, 64-bit
uv 0.12.0
maturin 1.12.6
```

Rust and uv bootstrap state remained outside the repository:

```text
C:\Users\Playe\Documents\Codex\2026-07-29\der-agent-soll-bevorzugt-den-python\work\phase1-rust
C:\Users\Playe\Documents\Codex\2026-07-29\der-agent-soll-bevorzugt-den-python\work\phase1-uv-bootstrap
```

## 6. `openjarvis_rust` build

The requested project-environment command was used:

```text
uv run maturin develop --uv --manifest-path rust/crates/openjarvis-python/Cargo.toml
```

After the Microsoft toolchain was installed, the first native compilation
exposed an `aws-lc-sys` Windows path-length failure:

```text
tree_drbg_jitter_entropy.c(17): fatal error C1083:
../../../../third_party/jitterentropy/jitterentropy-library/jitterentropy.h:
No such file or directory
```

The referenced header existed. Its physical path plus MSVC's relative include
resolution exceeded the classic Windows path limit. A temporary `subst`
mapping did not resolve the problem because Cargo canonicalized the physical
path; the mapping was removed afterward.

The successful, reproducible process-local compatibility settings were:

```text
AWS_LC_SYS_PREBUILT_NASM=1
AWS_LC_SYS_NO_JITTER_ENTROPY=1
```

No OpenJarvis or dependency source was patched, and no substitute
implementation was introduced. With those variables and the same maturin
command, the build completed successfully:

```text
Exit code: 0
Duration: 272.5 seconds
Wheel: openjarvis_rust-0.1.0-cp311-cp311-win_amd64.whl
Editable package: openjarvis-rust 0.1.0
```

Installed native artifact:

```text
C:\Users\Playe\Documents\JARVIS\openjarvis-codex\.venv\Lib\site-packages\openjarvis_rust\openjarvis_rust.cp311-win_amd64.pyd
Size:   27,027,968 bytes
SHA256: CC5A2F6D13441FBEF88517AAB009330717B47066EB59721C935033A307E0778A
```

The generated debug symbols are 163,917,824 bytes. The package's dist-info and
SBOM material were also installed in the virtual environment.

All required imports succeeded:

```text
openjarvis_rust
openjarvis._rust.bridge
SQLiteMemory
PIIScanner
SecretScanner
InjectionScanner
GuardrailsEngine
RateLimiter
RateLimitConfig
CapabilityPolicy
Capability
create_app
JarvisConfig
```

Relevant installed Python package versions:

```text
openjarvis-rust 0.1.0
maturin 1.12.6
pytest 9.0.2
fastapi 0.129.0
uvicorn 0.41.0
pydantic 2.12.5
```

## 7. Targeted Memory and Security tests

All targeted runs used an external temporary `OPENJARVIS_HOME`; neither the
real Obsidian vault nor the legacy project was involved.

Memory/native group:

```text
83 passed, 10 skipped, 4 errors in 8.05s
```

The four errors occur only during teardown of
`tests/traces/test_store_fts.py`: the fixture yields a `TraceStore` without
closing it before `TemporaryDirectory` attempts to remove its SQLite files,
causing Windows `WinError 32`. Every FTS functional assertion passed. A
separate real `TraceStore` check with an explicit close passed query, result,
agent-filter, empty-result, and Windows file-cleanup checks.

Security group:

```text
85 passed in 4.97s
```

This covered the scanners, prompt-injection checks, guardrails, rate limiter,
capabilities, security setup, and security wiring.

CLI/server/config group:

```text
168 passed, 1 failed, 6 warnings in 19.89s
```

The one failure is an existing assertion/text mismatch in
`TestMetricsRoute.test_metrics_endpoint`: the route returned
`# no telemetry data`, while the isolated test accepts lowercase
`openjarvis` or exact-capital `No metrics`. This test passed in the parallel
full-suite run, making the result order/state dependent.

The exact Phase 1 Windows block:

```text
uv run pytest tests/hardware/test_hardware_profiles.py tests/cli/test_cli.py -v -m "not live and not cloud"
```

Result:

```text
28 passed, 2 skipped in 5.99s
Process duration: 8.27s
```

The test counts match Phase 1; the run is substantially faster after native
build readiness.

## 8. Full test comparison

Exact command:

```text
uv run pytest tests/ -n auto -q --tb=short -m "not live and not cloud and not hub"
```

| Result | Phase 1 | Phase 1.5 | Delta |
| --- | ---: | ---: | ---: |
| Passed | 6,929 | 7,071 | +142 |
| Failed | 175 | 51 | -124 |
| Errors | 10 | 10 | 0 |
| Skipped | 67 | 49 | -18 |
| Warnings | 68 | 68 | 0 |
| Test duration | 190.67s | 149.54s | -41.13s |

The total selected test count remained 7,181. Failures plus errors decreased
from 185 to 61, a net reduction of 124. The Phase 1 run did not retain a
node-by-node failure list, so this comparison is count- and category-based
rather than a claim that each previous failure was individually matched.

The remaining 61 full-suite failures/errors group as follows:

| Category | Count | Notes |
| --- | ---: | --- |
| Plausible OpenJarvis regression | 5 | Telemetry derived/batch/phase-energy zero-value logic |
| Windows/POSIX behavior | 23 | Platform scan filtering, Unix modes, `setsid`/`killpg`, `:memory:` path handling, RAPL/sysfs naming, POSIX shell templates |
| Missing optional external service | 2 | WhatsApp Baileys Node/npm and OpenClaw Node CSPRNG |
| Unmarked live Ollama dependency | 8 | Dense-store tests target `localhost:11434`; 2 failures and 6 setup errors |
| Fixture/path-format assumptions | 22 | Home isolation, display/background/model state, trial/persona, TOML backslashes, and four FTS teardown errors |
| Order/isolation-sensitive | 1 | Duplicate `scan_chunks` registration |
| **Total** | **61** | |

No missing-Rust-extension failure remains. The remaining errors are six
unavailable Ollama embedding calls and four Windows SQLite teardown errors.

## 9. Full local server smoke test

The unchanged OpenJarvis `create_app` path was started with:

- real Rust-backed SQLite memory;
- real security setup, guardrails, audit, capability policy, and rate limiter;
- an external temporary home and test vault;
- a deterministic, no-network in-process engine because no LLM service was
  configured;
- binding restricted to `127.0.0.1:8765`.

The smoke harness added diagnostics and controlled shutdown routes to that
single in-memory app instance only. It did not modify repository sources.

Validated results:

```text
GET  /health                         status=ok
GET  /v1/info                        model=phase15-no-llm, engine=phase15-smoke
GET  /v1/models                      one deterministic smoke model
GET  memory configuration            backend=sqlite, available=true
POST memory store/search              count 0 -> 1, exact fact found
POST /v1/security/scan                2 findings, no warnings/failures
Native extension                       loaded=true
Configuration                          validated=true
Security engine                        GuardrailsEngine
Audit logger                           available=true
Capability policy                      explicit grant allowed; deny blocked
Rate limiter                           first allowed; second throttled
LLM                                    explicitly disabled
POST chat completion                   phase-1.5 smoke response
POST controlled shutdown               shutting_down
```

The server process exited normally after controlled shutdown. The process was
gone and port 8765 was closed; no forced termination fallback was required.

Temporary locations:

```text
C:\Users\Playe\Documents\Codex\2026-07-29\der-agent-soll-bevorzugt-den-python\work\phase1-5-server-home
C:\Users\Playe\Documents\Codex\2026-07-29\der-agent-soll-bevorzugt-den-python\work\phase1-5-server-home\test-vault
```

## 10. Remaining Windows limitations

1. The `aws-lc-sys` build needs the two process-local environment variables
   documented above at this repository depth. This should be automated in a
   Windows developer entry point or validated against a shallower checkout.
2. Four FTS tests leak a live SQLite handle into temporary-directory teardown
   and therefore raise `WinError 32`.
3. Several tests assume POSIX permissions, process groups, shell syntax,
   sysfs/RAPL paths, or colon-containing path semantics.
4. Some TOML/path assertions use POSIX separator assumptions.
5. Eight dense-store tests are not marked as live but require a compatible
   Ollama embedding endpoint.
6. Two tests require optional Node-based services not installed for this
   Python/Rust baseline.
7. Five telemetry tests expose plausible zero-value aggregation defects and
   should be treated as product issues rather than Windows setup failures.
8. One duplicate-tool-registration test remains order/isolation sensitive.

These are development-readiness limitations. They do not invalidate the
successful native extension build, imports, security tests, or local server
startup.

## 11. Changed and generated files

Committed repository files:

```text
docs/baseline/phase-1-windows-baseline.md
docs/baseline/installed-packages.txt
```

New, intentionally uncommitted Phase 1.5 repository documentation:

```text
docs/baseline/phase-1-5-msvc-install-plan.md
docs/baseline/phase-1-5-windows-native-build-readiness.md
```

Ignored/generated repository content:

```text
.venv\Lib\site-packages\openjarvis_rust\...
rust\target\...
.pytest_cache\...
```

External recovery artifact, installer, logs, server harness, and temporary
test homes were created only below:

```text
C:\Users\Playe\Documents\Codex\2026-07-29\der-agent-soll-bevorzugt-den-python\outputs\phase-1-5
C:\Users\Playe\Documents\Codex\2026-07-29\der-agent-soll-bevorzugt-den-python\work
```

System-level additions are limited to Visual Studio Build Tools 2022 and its
selected Microsoft prerequisites and Windows SDK components.

No OpenJarvis source, test, lock, or migration file was changed. No content
was read from or written to the real Obsidian vault or the legacy
`jarvis-desktop` repository.

## 12. Phase 2 readiness decision

**Phase 2 can safely begin as an isolated implementation and migration
development phase.**

The decision is supported by a reproducible native Rust build, successful
required imports, 85/85 targeted security tests, a working Rust-backed memory
path, and a clean full local server lifecycle on loopback.

Phase 2 should continue to use a temporary vault and external test state. It
must not be considered a production-Windows readiness approval until the
documented Windows teardown/path assumptions, telemetry defects, unmarked
Ollama dependencies, and optional Node-service gaps are either fixed, marked,
or explicitly accepted.
