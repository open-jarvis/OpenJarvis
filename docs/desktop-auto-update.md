# Desktop auto-update

The OpenJarvis desktop app ships with [Tauri's updater
plugin](https://v2.tauri.app/plugin/updater/), which checks for new
versions on launch and every 30 minutes. When a newer signed build is
available, the app prompts the user to download and install it.

## How it works

```
on launch / every 30 min
        │
        ▼
GET https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/latest.json
        │
        ▼
Parse manifest: { "version": "X.Y.Z", "platforms": { ... } }
        │
        ▼
If manifest.version > installed_version:
   download signed .dmg / .deb / .msi from manifest.platforms[target].url
   verify against the minisign pubkey baked into the app
   prompt user to install
```

The frontend code lives in
[`frontend/src/components/Desktop/UpdateChecker.tsx`](../frontend/src/components/Desktop/UpdateChecker.tsx);
the Tauri wiring is in
[`frontend/src-tauri/tauri.conf.json`](../frontend/src-tauri/tauri.conf.json)
under `plugins.updater`.

## How releases reach the update endpoint

The `Desktop Build & Release` GitHub Action
([`.github/workflows/desktop.yml`](../.github/workflows/desktop.yml))
publishes signed binaries plus a `latest.json` manifest to the
`desktop-latest` GitHub release on every push to `main`. The
`tauri-action` step with `includeUpdaterJson: true` generates the
manifest automatically.

Two release streams exist:

- **`desktop-latest`** (rolling pre-release): updated on every push to
  `main`. This is the channel the desktop app currently polls. Users
  on this channel get the most recent build the CI produced.
- **`desktop-vX.Y.Z`** (tagged stable): created when someone pushes a
  `desktop-v*` git tag. Has the same artifacts but is marked as a
  proper release rather than a pre-release.

The current updater endpoint points at the rolling `desktop-latest`
stream so that bug fixes (especially security and telemetry-policy
changes) reach users without waiting for a manual stable tag. A future
release may introduce a stable channel that points at
`desktop-v*` tags only.

## Signing

Binaries are signed by `tauri-action` using the minisign key pair
referenced via these GitHub Actions secrets:

| Secret | Purpose |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | Private key (PEM-formatted minisign) |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | Passphrase for the private key |

The matching public key is baked into the app at
`tauri.conf.json:plugins.updater.pubkey`. If you ever need to rotate
the key, replace the public key in the JSON file *and* update both
secrets atomically — mismatched keys cause every update download to
fail signature verification with no recovery path other than a manual
reinstall.

## Disabling the updater locally

For frontend development, set `VITE_OPENJARVIS_NO_UPDATER=1` in your
shell before running `npm run tauri dev`. Vite injects any
`VITE_`-prefixed env var into `import.meta.env`, and the
`UpdateChecker.tsx` component honors it to skip the 30-minute poll.

```bash
export VITE_OPENJARVIS_NO_UPDATER=1
npm run tauri dev
```

This is purely a dev escape hatch — it has no effect on production
builds (where `import.meta.env.VITE_OPENJARVIS_NO_UPDATER` will be
`undefined` unless you explicitly set it at build time).

## Verifying a release manually

```bash
# Download the latest manifest and confirm it parses cleanly
curl -fsSL https://github.com/open-jarvis/OpenJarvis/releases/download/desktop-latest/latest.json | jq .

# Fields:
#   version       — semver string, must match the tag (without leading "v")
#   notes         — release notes string
#   pub_date      — RFC3339 timestamp
#   platforms     — map keyed by "<target>-<arch>" e.g. "darwin-aarch64"
#                   each entry has { signature: "...", url: "..." }
```

A 404 on the manifest URL means the most recent desktop CI run
didn't complete or didn't have signing secrets — check the
`Desktop Build & Release` workflow logs.
