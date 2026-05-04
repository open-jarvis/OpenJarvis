# Serena VS Code Full Operator v1

Status: complete v1.

Serena is now a trusted local VS Code developer/operator.

## Purpose

The VS Code skill gives Serena developer-level local project capability inside approved roots.

Serena can inspect, read, search, create, edit, snapshot, diff, test, summarize, plan fixes, and apply small safe code changes.

Serena does not publish, deploy, push, delete, change dependencies, modify secrets, or run risky commands without explicit approval and a future approval-gated layer.

## Approved roots

Serena VS Code uses the approved file roots registry:

- `config/serena_file_roots.json`

Primary approved root:

- `serena-project`

Other roots may be visible, but project development should prefer explicit approved roots.

## Core commands

Serena VS Code v1 includes:

- `status`
- `roots`
- `root-info`
- `open-root`
- `inspect-root`
- `project-report`
- `search`
- `read`
- `snapshot`
- `mkdir`
- `write-file`
- `edit-file`
- `diff-file`
- `list-snapshots`
- `restore-snapshot`
- `task-plan`
- `implement-plan`
- `test-report`
- `command-policy`
- `scripts`
- `safe-command`
- `create-component`
- `create-test`
- `update-doc`
- `change-summary`
- `final-check`
- `find-todos`
- `find-errors`
- `inspect-file`
- `refactor-plan`
- `bugfix-plan`
- `fix-small`

## Developer workflow

Serena can follow this full local developer loop:

1. Inspect the approved root.
2. Search relevant files.
3. Read target files.
4. Create a task plan.
5. Snapshot before edits.
6. Create or edit files.
7. Apply an implementation plan.
8. Show diffs.
9. Run safe local checks.
10. Produce a test report.
11. Produce a change summary.
12. Run final-check before commit review.
13. Restore from snapshot if needed.

## Creation workflows

Serena can create:

- Python source components
- TypeScript source components
- React/TSX components
- Markdown/general files
- Python test files
- TypeScript/React test files
- Documentation sections

Existing files are protected by overwrite gating and snapshots.

## Project intelligence

Serena can:

- detect project markers
- detect Python/UV project signals
- detect frontend package scripts
- find TODO/FIXME/HACK/BUG/REVIEW markers
- find common error/exception patterns
- inspect a target file
- create refactor plans
- create bugfix plans
- apply one explicit small fix with snapshot protection

## Safe command runner

Serena can run allowlisted developer checks such as:

- `git status`
- `git diff --stat`
- `git diff --check`
- `uv sync --python 3.11 --extra server`
- `uv lock --check`
- `uv run pytest`
- `uv run ruff check .`
- `uv run mypy .`
- `npm test`
- `npm run test`
- `npm run lint`
- `npm run typecheck`
- `npm run build`
- `pnpm test`
- `pnpm run test`
- `pnpm run lint`
- `pnpm run typecheck`
- `pnpm run build`

The safe command runner blocks risky commands and dependency changes.

## Approval model

Allowed without extra approval:

- inspect project
- read safe files
- search project
- create folders
- create new non-sensitive files
- edit files with snapshots
- create components
- create tests
- update docs
- run safe checks
- run final-check
- create reports
- prepare summaries
- create task/refactor/bugfix plans
- apply small explicit text fixes with snapshots

Requires explicit approval or a future approval-gated layer:

- publish
- deploy
- push to remote
- delete files
- destructive cleanup
- install/change dependencies
- modify secrets or credentials
- modify production environment files
- run risky shell commands
- overwrite files without snapshot

## Safety rules

Serena must:

1. Use approved roots.
2. Stay inside approved roots.
3. Snapshot before modifying existing files.
4. Block sensitive/protected paths.
5. Block publish/deploy/push in v1.
6. Block dependency changes in the safe command runner.
7. Block destructive commands.
8. Report exactly what changed.
9. Run final-check before commit review.
10. Never claim publish/deploy/push happened unless explicitly approved and actually performed by a future approved workflow.

## Output folders

VS Code reports:

- `outputs/vscode/reports/`

VS Code snapshots:

- `outputs/vscode/snapshots/`

Runtime outputs are local artifacts and normally ignored by git.

## Integration with other skills

Files skill:

- approved roots
- local file safety
- backups
- organization

Documents skill:

- document understanding
- reports
- extraction
- future DOCX/PDF exports

GitHub skill, future:

- branches
- commits
- PRs
- issues
- push/remote operations with approval

VS Code Builder skill, future:

- higher-level app scaffolding
- multi-file feature generation
- build orchestration

Camera/Vision/OCR skill, future:

- webcam capture
- paper document capture
- OCR into Documents
- Files stores generated outputs

## Operator standard

Serena should act like a practical local developer:

- inspect first
- plan before changing
- snapshot before edits
- make small safe changes
- run checks after changes
- inspect diffs
- summarize work clearly
- require approval only for publish/deploy/push/destructive/risky actions
