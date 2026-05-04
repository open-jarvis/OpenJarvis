# Serena VS Code Builder Full Operator v1

Legacy source:

- `legacy\serena-skills\83-vscode-builder.js`

Initial inspection:

- Lines: 93
- Characters: 3185
- Functions found: 0
- Dependencies found: 3

Target:

Serena VS Code Builder Full Operator v1 should let Serena build higher-quality website/app features, sections, pages, and multi-file project structures.

Required lifecycle:

1. Check builder status.
2. Use approved project roots only.
3. Create build plans.
4. Scaffold folders.
5. Generate source files.
6. Generate components.
7. Generate tests.
8. Generate documentation.
9. Generate landing page or website sections.
10. Generate WordPress-ready HTML sections.
11. Inspect affected files.
12. Run safe final checks through VS Code operator.
13. Produce build reports.
14. Block publish, deploy, push, destructive operations, secrets, and dependency changes unless explicit approval/future layer handles them.

Operator standard:

Serena should not just write random files.

Serena should build like a developer:
- plan first
- create structured output
- use approved roots
- snapshot before replacing existing files
- generate tests/docs where useful
- run final checks
- report exactly what changed
- keep publish/deploy/push approval-gated
