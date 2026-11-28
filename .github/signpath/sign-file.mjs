import { randomUUID } from 'node:crypto';
import { copyFileSync, existsSync, mkdtempSync, rmSync, statSync } from 'node:fs';
import { basename, dirname, extname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DefaultArtifactClient } from '@actions/artifact';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));

// Tauri calls this hook for the app, the NSIS uninstaller, and the installers.
// Each request uses a GitHub-hosted artifact so SignPath can verify its origin.
export async function signFile(path, {
  env = process.env,
  artifactClient = new DefaultArtifactClient(),
  run = spawnSync,
} = {}) {
  const source = resolve(path);
  if (!['.exe', '.msi'].includes(extname(source).toLowerCase()) || !statSync(source).isFile()) {
    throw new Error(`Expected a Windows executable or MSI: ${source}`);
  }
  for (const name of [
    'SIGNPATH_API_TOKEN', 'SIGNPATH_ORGANIZATION_ID', 'SIGNPATH_PROJECT_SLUG',
    'SIGNPATH_SIGNING_POLICY_SLUG', 'SIGNPATH_CERTIFICATE_THUMBPRINT',
    'SIGNPATH_ACTION_DIRECTORY', 'RUNNER_TEMP', 'GITHUB_TOKEN',
  ]) {
    if (!env[name]) throw new Error(`Missing ${name}`);
  }
  const action = join(env.SIGNPATH_ACTION_DIRECTORY, 'index.js');
  if (!existsSync(action)) throw new Error('The pinned SignPath action is missing');
  const output = mkdtempSync(join(env.RUNNER_TEMP, 'signpath-'));
  try {
    const { id } = await artifactClient.uploadArtifact(
      `windows-signing-${randomUUID()}`, [source], dirname(source),
      { retentionDays: 7, compressionLevel: 0 },
    );
    if (!id) throw new Error('GitHub did not return an uploaded artifact ID');
    const result = run(process.execPath, [action], {
      stdio: 'inherit',
      env: {
        ...env,
        'INPUT_CONNECTOR-URL': 'https://pipelineconnector.connectors.signpath.io/GitHubActions/GitHubCom',
        'INPUT_API-TOKEN': env.SIGNPATH_API_TOKEN,
        'INPUT_ORGANIZATION-ID': env.SIGNPATH_ORGANIZATION_ID,
        'INPUT_PROJECT-SLUG': env.SIGNPATH_PROJECT_SLUG,
        'INPUT_SIGNING-POLICY-SLUG': env.SIGNPATH_SIGNING_POLICY_SLUG,
        'INPUT_ARTIFACT-CONFIGURATION-SLUG': env.SIGNPATH_ARTIFACT_CONFIGURATION_SLUG || '',
        'INPUT_GITHUB-ARTIFACT-ID': String(id),
        'INPUT_GITHUB-TOKEN': env.GITHUB_TOKEN,
        'INPUT_WAIT-FOR-COMPLETION': 'true',
        'INPUT_WAIT-FOR-COMPLETION-TIMEOUT-IN-SECONDS': '1800',
        'INPUT_SERVICE-UNAVAILABLE-TIMEOUT-IN-SECONDS': '600',
        'INPUT_DOWNLOAD-SIGNED-ARTIFACT-TIMEOUT-IN-SECONDS': '300',
        'INPUT_OUTPUT-ARTIFACT-DIRECTORY': output,
        'INPUT_SKIP-DECOMPRESS': 'false',
      },
    });
    if (result.error || result.status !== 0) throw new Error('SignPath signing failed');
    const signed = join(output, basename(source));
    if (!existsSync(signed) || statSync(signed).size === 0) {
      throw new Error('SignPath did not return the expected signed file');
    }
    const verify = run('pwsh', [
      '-NoLogo', '-NoProfile', '-NonInteractive', '-File',
      join(scriptDirectory, 'verify-signature.ps1'), '-Path', signed,
      '-ExpectedThumbprint', env.SIGNPATH_CERTIFICATE_THUMBPRINT,
    ], { stdio: 'inherit', env });
    if (verify.error || verify.status !== 0) throw new Error('Authenticode verification failed');
    copyFileSync(signed, source);
  } finally {
    rmSync(output, { recursive: true, force: true });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  signFile(process.argv[2]).catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
