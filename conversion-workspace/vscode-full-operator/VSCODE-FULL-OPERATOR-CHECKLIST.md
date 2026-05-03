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
