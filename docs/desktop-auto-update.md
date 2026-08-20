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
builds signed binaries plus a `latest.json` manifest with the
`tauri-action` step (`includeUpdaterJson: true` generates the manifest
automatically). Where it publishes depends on the trigger.

Three release streams exist:

- **`desktop-latest`** (stable auto-update channel): **this is the
  channel the installed app polls.** It is *not* built directly —
  instead, when a stable `desktop-vX.Y.Z` release is published, the
  `refresh-stable-channel` job copies that release's `latest.json`
  into `desktop-latest`. So the app is only ever offered vetted stable
  builds, and `latest.json` here points at the current `desktop-v*`
  assets.
- **`desktop-vX.Y.Z`** (tagged stable): created when someone pushes a
  `desktop-v*` git tag. The user-facing stable release with full
  installers; also the source of truth the stable channel mirrors.
- **`desktop-edge`** (rolling pre-release): rebuilt on every push to
  `main` (via the `autotag` → `desktop.yml` dispatch) and on manual
  `workflow_dispatch`. Carries the most recent CI build for testers.
  The shipped app does **not** poll this stream, so dev builds never
  auto-install onto stable users.

This split means security and telemetry-policy fixes reach users on
the next **stable** `desktop-v*` tag — cut one to ship an update.
Edge builds are available for anyone who wants to test `main` ahead of
a stable tag, without risking the stable population.

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
