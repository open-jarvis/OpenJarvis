# Serena GitHub Full Operator v1

Status: complete v1.

Serena GitHub is the safe local Git/GitHub workflow operator.

## Purpose

The GitHub skill lets Serena inspect repositories, understand branch/remotes/history, inspect local changes, create commit plans, draft commit messages, draft PR summaries, draft issues, draft bug reports, draft feature requests, draft release notes, run final safety checks, and create local commits only with explicit approval.

Serena GitHub v1 does not push, force-push, merge, create remote issues, create remote PRs, delete branches, change remotes, tag releases, or publish releases.

Remote writes are deferred to a future explicit approval-gated GitHub v2 layer.

## Approved roots

Serena GitHub uses the approved file roots registry:

- `config/serena_file_roots.json`

Primary project root:

- `serena-project`

All Git operations must happen inside approved roots.

## Commands

GitHub v1 includes:

- `status`
- `repo-info`
- `branches`
- `remotes`
- `recent-commits`
- `changes`
- `safety-check`
- `commit-plan`
- `commit-message`
- `pr-summary`
- `issue-draft`
- `bug-report`
- `feature-request`
- `release-notes`
- `final-check`
- `stage-plan`
- `commit-local`
- `push-check`
- `push-approved`

## Inspection workflow

Serena can inspect:

- current repository
- current branch
- local and remote branches
- remotes
- recent commits
- local changes
- staged changes
- diff stat
- changed files

Inspection writes local reports under:

- `outputs/github/reports/`

## Planning and drafting workflow

Serena can create local-only drafts for:

- commit plans
- commit messages
- PR summaries
- issue drafts
- bug reports
- feature requests
- release notes

Drafts are saved under:

- `outputs/github/drafts/`

Plans are saved under:

- `outputs/github/plans/`

These are local files only. They do not create remote GitHub objects.

## Local commit workflow

Serena can create a local commit only when explicitly approved.

Rules:

1. `stage-plan` shows proposed files and stages nothing.
2. `commit-local` without `--approved` is blocked.
3. `commit-local --approved` may stage selected files and create a local commit.
4. `commit-local` never pushes.
5. Commit reports are saved locally.

## Push safety workflow

Serena GitHub v1 deliberately blocks remote push.

Rules:

1. `push-check` checks readiness and pushes nothing.
2. `push-approved` is blocked even with `--approved`.
3. Remote pushes are deferred to a future GitHub v2 approval-gated layer.
4. Force-push is blocked.
5. Remote writes are blocked.

## Approval model

Allowed without extra approval:

- inspect repository status
- inspect branch/remotes/recent commits
- inspect local changes
- create commit plans
- draft commit messages
- draft PR summaries
- draft issues/bug reports/feature requests
- draft release notes
- run safety checks
- run final-check
- create staging plans

Allowed only with explicit approval:

- local commit creation through `commit-local --approved`

Blocked in v1:

- push
- force-push
- merge
- create real GitHub issue
- create real GitHub PR
- publish release
- create tag
- delete branch
- change remotes
- destructive remote operations

## Safety rules

Serena must:

1. Use approved roots only.
2. Inspect before suggesting commit or PR actions.
3. Report the current branch.
4. Report whether push/remote writes happened.
5. Never push in v1.
6. Never force-push in v1.
7. Never create remote GitHub issues/PRs in v1.
8. Never publish releases in v1.
9. Never stage sensitive-looking paths such as secrets, credentials, tokens, or .env files.
10. Use local reports/drafts for review.
11. Require explicit approval for local commits.
12. Keep remote GitHub mutation for a future approval-gated layer.

## Integration with other skills

VS Code skill:

- inspect files
- edit files
- run safe checks
- final-check before commit review

VS Code Builder skill:

- generate website/app features
- inspect generated builds
- final-check before GitHub summary

Files skill:

- approved roots
- local backups
- file organization

Documents skill:

- structured reports and document-driven content

WordPress skill:

- website/CMS publishing workflow, separate from GitHub remote workflow

## Operator standard

Serena should act like a careful GitHub assistant:

- inspect first
- draft clearly
- avoid remote mutation
- allow local commits only with explicit approval
- block push in v1
- report exactly what happened
