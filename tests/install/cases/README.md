# Failure-mode regression catalog

Every error-handling case from the [design doc §8](../../../docs/superpowers/specs/2026-05-03-cli-cold-start-refresh-design.md) is documented here, with:

- The trigger conditions
- The expected user-visible behavior
- The retry / fix command
- The test that exercises it (in `tests/install/`)

When a real-world bug report uncovers a new failure mode, add an entry here at the same time you add the regression test.

## Index

- [run-as-root.md](run-as-root.md) — installer refuses to run as root
- [missing-git.md](missing-git.md) — installer refuses without `git` on PATH

(Add new entries as the catalog grows.)
