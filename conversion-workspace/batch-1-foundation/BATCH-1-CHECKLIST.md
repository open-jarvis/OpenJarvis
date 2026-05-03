# Serena Batch 1 - Foundation Conversion

## Goal

Convert the first 7 high-value old Serena JavaScript skills into new OpenJarvis-native Serena skills and tools.

## Batch 1 files

- 13-wordpress.js
- 67-documents.js
- 63-files.js
- 41-vscode.js
- 83-vscode-builder.js
- 64-github.js
- 47-health-monitor.js

## Conversion rule

For each skill:

1. Inspect old JavaScript file.
2. Extract purpose, triggers, env variables, dependencies, APIs, outputs, and safety risks.
3. Research upgrades:
   - GitHub
   - mrfreetools.com
   - official docs where relevant
4. Create/upgrade skill folder under src/openjarvis/skills/serena/.
5. Create/upgrade Python tool under src/openjarvis/tools/.
6. Test through:
   - uv run serena tool list
   - uv run serena tool inspect <tool>
   - uv run serena ask "<natural request>"
   - uv run serena live
7. Update conversion registry.
8. Delete the matching old JS file only after native conversion is tested.
9. Commit.

## First conversion

Start with:

legacy/serena-skills/13-wordpress.js

Target:

src/openjarvis/skills/serena/content-marketing/wordpress/
src/openjarvis/tools/serena_wordpress.py
