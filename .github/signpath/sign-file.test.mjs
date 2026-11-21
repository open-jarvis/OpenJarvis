import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import { test } from 'node:test';
import { signFile } from './sign-file.mjs';

function fixture(t) {
  const folder = mkdtempSync(join(tmpdir(), 'signpath-hook-test-'));
  t.after(() => rmSync(folder, { recursive: true, force: true }));
  const source = join(folder, 'OpenJarvis setup.exe');
  writeFileSync(source, 'original unsigned bytes');
  writeFileSync(join(folder, 'index.js'), '// signer fixture');
  const env = {
    SIGNPATH_API_TOKEN: 'test-token',
    SIGNPATH_ORGANIZATION_ID: 'test-org',
    SIGNPATH_PROJECT_SLUG: 'test-project',
    SIGNPATH_SIGNING_POLICY_SLUG: 'test-policy',
    SIGNPATH_CERTIFICATE_THUMBPRINT: 'test-thumbprint',
    SIGNPATH_ACTION_DIRECTORY: folder,
    GITHUB_TOKEN: 'test-github-token',
    RUNNER_TEMP: folder,
  };
  let uploads = 0;
  const artifactClient = {
    async uploadArtifact(name, paths, root, options) {
      assert.match(name, /^windows-signing-/);
      assert.deepEqual(paths, [source]);
      assert.equal(root, folder);
      assert.equal(options.compressionLevel, 0);
      uploads++;
      return { id: 42 };
    },
  };
  let verifications = 0;
  const run = (command, args, options) => {
    if (command === process.execPath) {
      assert.equal(options.env['INPUT_GITHUB-ARTIFACT-ID'], '42');
      assert.equal(options.env['INPUT_PROJECT-SLUG'], env.SIGNPATH_PROJECT_SLUG);
      writeFileSync(join(options.env['INPUT_OUTPUT-ARTIFACT-DIRECTORY'], basename(source)), 'signed bytes');
    } else {
      assert.equal(command, 'pwsh');
      assert.equal(args.at(-1), env.SIGNPATH_CERTIFICATE_THUMBPRINT);
      assert.equal(readFileSync(source, 'utf8'), 'original unsigned bytes');
      verifications++;
    }
    return { status: 0 };
  };
  return { folder, source, env, artifactClient, run, counts: () => ({ uploads, verifications }) };
}

test('uploads the original and replaces it only after signature verification', async (t) => {
  const f = fixture(t);
  await signFile(f.source, f);
  assert.equal(readFileSync(f.source, 'utf8'), 'signed bytes');
  assert.deepEqual(f.counts(), { uploads: 1, verifications: 1 });
  assert.deepEqual(readdirSync(f.folder).sort(), ['OpenJarvis setup.exe', 'index.js']);
});

test('a rejected signing request leaves the original intact', async (t) => {
  const f = fixture(t);
  await assert.rejects(signFile(f.source, { ...f, run: () => ({ status: 1 }) }), /signing failed/);
  assert.equal(readFileSync(f.source, 'utf8'), 'original unsigned bytes');
});

test('an untrusted or wrong-certificate result leaves the original intact', async (t) => {
  const f = fixture(t);
  const run = (command, args, options) => command === 'pwsh'
    ? { status: 1 } : f.run(command, args, options);
  await assert.rejects(signFile(f.source, { ...f, run }), /verification failed/);
  assert.equal(readFileSync(f.source, 'utf8'), 'original unsigned bytes');
});

test('missing signed output fails without replacing the original', async (t) => {
  const f = fixture(t);
  await assert.rejects(signFile(f.source, { ...f, run: () => ({ status: 0 }) }), /expected signed file/);
  assert.equal(readFileSync(f.source, 'utf8'), 'original unsigned bytes');
});

test('configuration is checked before uploading any file', async (t) => {
  const f = fixture(t);
  delete f.env.SIGNPATH_API_TOKEN;
  await assert.rejects(signFile(f.source, f), /Missing SIGNPATH_API_TOKEN/);
  assert.equal(f.counts().uploads, 0);
});

test('a failed GitHub artifact upload prevents a signing request', async (t) => {
  const f = fixture(t);
  const artifactClient = { async uploadArtifact() { return {}; } };
  await assert.rejects(signFile(f.source, { ...f, artifactClient }), /artifact ID/);
  assert.equal(f.counts().verifications, 0);
});
