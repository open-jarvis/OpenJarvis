# Windows release signing

The desktop workflow configures Tauri's `bundle.windows.signCommand` to run
`sign-file.mjs` for the application, NSIS uninstaller, and installers. The hook
uploads each unsigned file as a GitHub Actions artifact and submits its ID to
the pinned official SignPath action. SignPath retrieves the artifact from GitHub
and verifies its build origin. A signed file replaces the original only after
Windows verifies its certificate, timestamp, and expected certificate thumbprint.
Tauri then generates updater signatures over the final Authenticode-signed bytes.

## Account setup

The existing SignPath organization is `OpenJarvis [OSS]`, ID
`f0a8257c-d9c7-47ef-a9d4-bcc1c9f46741`.

1. Sign in to SignPath and accept the organization invitation if still pending.
2. Confirm the notification address for the existing `CI builds` user.
3. Create a project for `https://github.com/open-jarvis/OpenJarvis` and use the
   XML from `artifact-configuration.xml`. Each uploaded ZIP contains one file.
4. Link the GitHub.com trusted build system to the project and retain the
   Foundation program's build-origin verification requirements. SignPath's
   GitHub App is needed for audit-log-based policy verification. Check the
   project's actual policy before requesting that installation, because the
   app requests repository and organization administration permissions.
5. Grant the CI user submitter access to the project's signing policy and store
   its API token in the repository secret listed below. Keep the token out of
   source files and logs.
6. Complete a test-certificate signing request and send SignPath the request and
   workflow links for its technical review. The September 25 onboarding email
   states that the Foundation orders/imports the production certificate after
   this review. A test certificate does not satisfy the production verification.
7. Set the production signing policy and certificate thumbprint, then run the
   desktop release workflow and inspect the SignPath requests and Windows
   signature verification results before publishing a stable release.

## GitHub configuration

| Name | Location | Value |
| --- | --- | --- |
| `SIGNPATH_API_TOKEN` | Actions secret | Existing CI user's API token |
| `SIGNPATH_ORGANIZATION_ID` | Actions variable | `f0a8257c-d9c7-47ef-a9d4-bcc1c9f46741` |
| `SIGNPATH_PROJECT_SLUG` | Actions variable | Project slug from the account |
| `SIGNPATH_SIGNING_POLICY_SLUG` | Actions variable | Production signing policy slug |
| `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG` | Actions variable | Optional, defaults to project's artifact configuration |
| `SIGNPATH_CERTIFICATE_THUMBPRINT` | Actions variable | Production certificate's SHA-1 thumbprint |

The job needs `actions: read` and `contents: write`, in addition to the artifact
runtime credentials supplied automatically to GitHub JavaScript actions.
Signing credentials are available to the release build, which runs on tag pushes
and manual dispatch. Pull request test installers use their existing unsigned
build path.

## Local verification

```sh
cd .github/signpath
npm ci --ignore-scripts
npm audit
npm test
```

The hook tests cover successful replacement, signing failure, wrong/untrusted
certificate rejection, missing signed output, configuration errors, and artifact
upload failure. The real SignPath submission still requires account access and
a configured CI token.

## Scope

The signing hook covers first-party desktop binaries and the EXE/MSI installers.
It preserves third-party files distributed with Ollama. Shipping a prebuilt,
signed Python/Rust backend is separate work because current installations still
build that backend from source.

References

- https://docs.signpath.io/trusted-build-systems/github
- https://docs.signpath.io/artifact-configuration/syntax
- https://v2.tauri.app/distribute/sign/windows/
