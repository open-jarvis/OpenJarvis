# Serena VS Code Builder Full Operator v1

Status: complete v1.

Serena VS Code Builder is the high-level local build layer for websites, app sections, components, feature scaffolds, WordPress-ready sections, tests, docs, and build reports.

## Purpose

The VS Code Builder skill lets Serena generate structured local website/app/build outputs under approved roots.

It does not publish, deploy, push, install dependencies, modify secrets, or perform destructive actions.

Publishing, deployment, pushing to remote, dependency changes, secrets/credentials changes, and destructive operations remain explicit-approval or future-layer workflows.

## Relationship to other skills

VS Code Builder works with:

- VS Code Full Operator v1 for safe local developer operations, final-checks, file reads, inspections, diffs, and snapshots.
- Files Full Operator v1 for approved roots, local storage, backups, and organization.
- WordPress Full Operator v1 for CMS operations, drafts, publishing checklist, rollback, menus, links, and WordPress publishing workflows.
- Documents Full Operator v1 for document extraction, structured content, reporting, and content inputs.

## Approved roots

VS Code Builder uses the approved file roots registry:

- `config/serena_file_roots.json`

Primary development/build root:

- `serena-project`

All generated project files must stay inside an approved root.

## Commands

VS Code Builder v1 includes:

- `status`
- `templates`
- `plan`
- `scaffold`
- `build-section`
- `build-wordpress-section`
- `build-react-component`
- `inspect-build`
- `final-check`

## Builder templates

Supported v1 templates/workflows:

- `feature-scaffold`
- `landing-html`
- `wordpress-section`
- `react-component`
- `docs-only`

## Build planning

Serena can create build plans that record:

- approved root
- build name
- goal
- kind/template
- target path
- build steps
- approval-required actions

Plans are saved locally under:

- `outputs/vscode-builder/plans/`

## Feature scaffold workflow

Serena can scaffold a structured feature folder with:

- source file
- test file
- README documentation

Supported v1 scaffold kinds include:

- Python
- TypeScript
- Markdown/general

Existing files are protected by overwrite gating.

## Website section workflow

Serena can generate polished local website sections with:

- `section.html`
- `section.css`
- `README.md`

This is local-only output. It does not publish or deploy.

## WordPress-ready section workflow

Serena can generate WordPress-ready HTML blocks with:

- `section.wordpress.html`
- `README.md`

WordPress-ready output is intended for review before use in the WordPress operator.

Generating a WordPress-ready block does not publish it to WordPress.

## React component workflow

Serena can generate local React/TSX components with:

- `.tsx` component file
- `README.md`

React output should be reviewed for project conventions, imports, styling framework, and integration requirements before production use.

## Build inspection

Serena can inspect generated build folders and detect:

- file count
- total size
- file types
- README/docs presence
- source/component/section presence
- WordPress-ready HTML
- React/TSX output
- issues
- recommendations

Inspection reports are saved under:

- `outputs/vscode-builder/reports/`

## Final check

Serena Builder final-check delegates to VS Code Full Operator v1 and verifies:

- git status
- git diff stat
- Python import check
- no publish/deploy/push performed

## Approval model

Allowed without extra approval:

- create build plans
- scaffold local feature folders
- generate website sections
- generate WordPress-ready HTML blocks
- generate React components
- create README documentation
- inspect generated builds
- run final-check
- save local reports

Requires explicit approval or a future approval-gated layer:

- publish
- deploy
- push to remote
- install/change dependencies
- modify secrets or credentials
- modify production environment files
- delete files
- destructive cleanup
- risky shell commands
- direct WordPress publishing

## Safety rules

Serena must:

1. Use approved roots only.
2. Keep generated files inside approved roots.
3. Avoid sensitive/protected paths.
4. Avoid publish/deploy/push in v1.
5. Avoid dependency changes in v1.
6. Avoid destructive operations in v1.
7. Create local reports for build operations.
8. Inspect generated builds before final commit review when practical.
9. Run final-check before commit review when practical.
10. Clearly state that generated WordPress-ready output has not been published.

## Output folders

Builder plans:

- `outputs/vscode-builder/plans/`

Builder reports:

- `outputs/vscode-builder/reports/`

Builder build artifacts/logical outputs:

- generated inside approved project roots

Runtime output folders are normally ignored by git.

## Operator standard

Serena should act like a careful website/app builder:

- plan first
- generate structured outputs
- include docs/tests where useful
- inspect generated folders
- run final-check
- report what was created
- keep publish/deploy/push approval-gated
