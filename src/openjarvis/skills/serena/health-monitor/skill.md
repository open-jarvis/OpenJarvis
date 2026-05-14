# Serena Health Monitor Full Operator v1

Status: complete v1.

Serena Health Monitor is the local operator/project health dashboard.

## Purpose

The Health Monitor skill lets Serena inspect whether her local operating environment is healthy before continuing upgrades, development work, publishing workflows, or project operations.

It checks system health, project structure, output folders, conversion registry status, skill documentation, native tool imports, Git status, and full final reports.

## Commands

Health Monitor v1 includes:

- `status`
- `system`
- `project`
- `outputs`
- `registry`
- `skills`
- `git`
- `final-report`

## System checks

Serena can inspect:

- operating system/platform
- Python executable
- Python version
- uv availability
- git availability
- VS Code CLI availability
- disk space

## Project checks

Serena can inspect important project files and folders:

- `pyproject.toml`
- `uv.lock`
- `src/openjarvis`
- `src/openjarvis/cli`
- `src/openjarvis/tools`
- `src/openjarvis/skills/serena`
- `src/openjarvis/serena_identity.py`
- `src/openjarvis/serena_capabilities/conversion_registry.json`
- `config/serena_file_roots.json`
- `conversion-workspace`
- `outputs`

## Output checks

Serena can inspect expected output folders:

- WordPress
- Documents
- Files
- VS Code
- VS Code Builder
- GitHub
- Health Monitor

## Registry checks

Serena can inspect the conversion registry and report:

- Batch 1 total skills
- completed skills
- remaining skills
- completion levels
- missing or invalid registry state

## Skills checks

Serena can inspect:

- expected skill documentation
- native tool imports
- missing skill docs
- failed imports

## Git checks

Serena can inspect:

- current branch
- Git status
- recent commits
- remotes
- untracked files
- modified files

## Final report

The final report combines:

- system health
- output folder health
- registry health
- skill documentation health
- native tool import health
- Git health
- issues
- recommendations

Reports are saved under:

- `outputs/health-monitor/reports/`

## Safety model

Health Monitor is read-only except for writing local reports.

It must not:

- modify project code
- publish
- deploy
- push
- delete files
- change configuration
- change dependencies

## Operator standard

Serena should use Health Monitor to verify the environment before and after major upgrade batches.

A healthy final report means Serena can trust the local operator environment enough to continue.
