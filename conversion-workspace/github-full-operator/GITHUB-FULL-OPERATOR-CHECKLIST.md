# Serena GitHub Full Operator v1

Legacy source:

- `legacy\serena-skills\64-github.js`

Initial inspection:

- Lines: 133
- Characters: 5032
- Functions found: 0
- Dependencies found: 1
- Triggers found: 4

Target:

Serena GitHub Full Operator v1 should give Serena safe local Git/GitHub workflow capability.

Required lifecycle:

1. Check GitHub/Git status.
2. Inspect current repository.
3. Detect branch and remotes.
4. Inspect recent commits.
5. Inspect local changes.
6. Build commit plan.
7. Draft commit message.
8. Draft PR summary.
9. Draft issue/bug/feature request.
10. Draft release notes.
11. Run final GitHub safety check.
12. Block push unless explicitly approved.
13. Block destructive remote operations.
14. Never expose or change secrets.

Operator standard:

Serena should not blindly push or mutate remote GitHub state.

Serena should:
- inspect first
- summarize clearly
- generate local plans/drafts
- use approved roots
- integrate with VS Code final-check
- require approval for remote writes
- report exactly what changed
