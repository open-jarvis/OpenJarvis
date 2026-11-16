# Dependency security checks

Core CI calls `security-sast.yml` before lint. Lint runs even when the security
job fails or is cancelled, and explicitly rejects every result except success.
This keeps a failed audit from becoming a skipped lint check. Repository rules
should require the `lint` status before merging.

The Python check queries OSV for every PyPI package/version in `uv.lock`,
including optional extras and platform-specific resolutions. No packages are
installed for this audit. Network errors, incomplete responses, unrecognized
package sources, and partial advisory pages fail the check.

Cargo Deny checks both Rust dependency graphs with the lockfiles unchanged. It
rejects vulnerabilities, unsoundness, yanked releases, and unknown registry/Git
sources. Existing upstream maintenance-only notices are listed as exact,
expiring exceptions too; a new maintenance advisory is not automatically allowed.

Semgrep rejects new static security findings relative to the trusted PR base
or previous main commit. A manual workflow dispatch performs a full scan.
Scanner/configuration failures are blocking, and reports are uploaded even on
failure. The scanner image is pinned by version and digest.

`advisory-exceptions.json` is a reviewed policy, not an automatically generated
baseline. Every exception identifies a lockfile, package, exact version, exact
advisory IDs, an upstream reference, a substantive reason, and a UTC expiry date
within 90 days. Expired, stale, duplicate, wildcard, and malformed exceptions
fail CI. A new advisory on an excepted package is still rejected. Remove an
exception when its package is patched; do not renew it without reviewing the
remaining risk.

The runtime-related exceptions currently cover the Linux GTK3 GLib iterator
issue, Setuptools build/legacy-installer paths constrained by upstream GPU
packaging, and DiskCache. The OpenJarvis DSPy optimizer disables disk caching
before use; its waiver is invalid if another package starts using DiskCache or
the validated DSPy version changes. Five other entries are upstream
maintenance-only notices. None is a blanket exception for future advisories.

## Repository merge enforcement

After the workflow changes are merged, a repository owner should require the
`lint` check from GitHub Actions and require branches to be up to date. The
prepared additive rule is `required-checks.json`; it preserves the existing
review/linear-history rules. An account with repository Administration access
can apply it once with:

```sh
gh api --method POST repos/open-jarvis/OpenJarvis/rulesets \
  --input .github/security/required-checks.json
```

The current Maintain account could not activate that rule (GitHub returned
HTTP 404). The workflow itself still fails on rejected findings; mandatory
merge enforcement needs this separate owner step.
