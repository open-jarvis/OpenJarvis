# Serena VS Code Full Operator v1

Legacy source:

- `legacy\serena-skills\41-vscode.js`

Initial inspection:

- Lines: 197
- Characters: 7262
- Functions found: 1
- Dependencies found: 4

Target:

Serena VS Code Full Operator v1 should let Serena operate VS Code and local development workspaces safely.

Required lifecycle:

1. Check VS Code availability.
2. Check current project/workspace status.
3. Open approved project folders.
4. Inspect project structure.
5. Read important files safely.
6. Run safe diagnostics.
7. Generate developer reports.
8. Snapshot before risky edits.
9. Avoid destructive actions unless explicitly approved.
10. Integrate with Files skill approved roots.
11. Prepare handoff to VS Code Builder skill.

Safety rules:

- Prefer approved roots such as serena-project.
- Do not edit files without snapshot.
- Do not delete files in v1.
- Do not run destructive commands.
- Do not install or change dependencies without approval.
- Report exactly what was checked or changed.

Operator standard:

Serena should act like a careful local development operator:
- inspect first
- diagnose before changing
- snapshot before edits
- explain results clearly
- preserve project safety

## Full developer/operator target

Serena VS Code Full Operator v1 must reach the same quality level as WordPress Full Operator v1.

Serena should be able to operate VS Code as a real local developer assistant.

Required full lifecycle:

1. Detect VS Code availability.
2. Detect VS Code CLI availability.
3. Open approved project folders.
4. Inspect project structure.
5. Read important project files.
6. Search code and text.
7. Create files.
8. Create folders.
9. Edit files.
10. Snapshot files before edits.
11. Generate patch/change reports.
12. Run safe diagnostics.
13. Run safe tests.
14. Run safe formatting/linting where available.
15. Inspect package/project configuration.
16. Detect likely project language/framework.
17. Build developer task plans.
18. Implement approved features.
19. Fix bugs.
20. Refactor code safely.
21. Update documentation.
22. Prepare commit summaries.
23. Integrate with Files approved roots.
24. Integrate with GitHub skill later.
25. Integrate with VS Code Builder skill later.

Developer-level capabilities:

- create new source files
- create config files
- create scripts
- create tests
- create documentation
- modify existing files with snapshots
- inspect diffs after changes
- run diagnostics after changes
- produce final developer report
- explain what changed and why

Approval model:

Allowed without extra approval:

- inspect project
- read files
- search files
- create new non-sensitive files
- create folders
- edit project files with snapshots
- run safe local diagnostics
- run safe local tests
- run formatting/linting
- update docs
- generate reports
- prepare commit messages

Requires explicit approval:

- publish
- deploy
- push to remote
- delete files
- destructive cleanup
- install/change dependencies
- change secrets or credentials
- modify production environment files
- run risky shell commands
- overwrite files without snapshot

Important rule:

Publishing/deploying/pushing requires approval.
Normal local developer work should be trusted, snapshot-protected, and inspectable.

Operator standard:

Serena should not merely open VS Code.
Serena should be able to build, edit, test, inspect, and report like a developer.
