import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const advisory = 'https://github.com/advisories/GHSA-gcqx-w48m-w2h4';
const expires = Date.parse('2026-11-27T00:00:00Z');
const buildChain = new Map([
  ['deepmerge', null],
  ['@rollup/plugin-node-resolve', 'deepmerge'],
  ['workbox-build', '@rollup/plugin-node-resolve'],
  ['vite-plugin-pwa', 'workbox-build'],
]);

// No patched deepmerge release exists. Workbox merges our build configuration,
// not user input. Temporarily accept only this low-severity advisory in dev
// dependencies; retain the full audit gate for everything else. Remove this
// exception when upstream ships a fix; it expires on November 27, 2026.
export function checkAudit(report, lock, now = Date.now()) {
  if (report?.error || report?.auditReportVersion !== 2
      || !report.vulnerabilities || typeof report.vulnerabilities !== 'object'
      || Array.isArray(report.vulnerabilities)) {
    throw new Error('npm audit did not return a valid vulnerability report');
  }
  const findings = Object.entries(report.vulnerabilities);
  for (const [name, finding] of findings) {
    const via = finding?.via;
    const expected = buildChain.get(name);
    const knownCause = Array.isArray(via) && via.length === 1
      && (name === 'deepmerge'
        ? via[0]?.url === advisory && via[0]?.severity === 'low'
        : typeof expected === 'string' && via[0] === expected
          && Object.hasOwn(report.vulnerabilities, expected));
    const devOnly = Array.isArray(finding?.nodes) && finding.nodes.length > 0
      && finding.nodes.every((node) => lock?.packages?.[node]?.dev === true);
    if (now >= expires || !buildChain.has(name) || finding?.severity !== 'low'
        || !knownCause || !devOnly) {
      throw new Error(`Unaccepted audit finding: ${name} (${finding?.severity})`);
    }
  }
  return findings.length;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const report = JSON.parse(readFileSync(process.argv[2], 'utf8'));
    const lock = JSON.parse(readFileSync(new URL('../package-lock.json', import.meta.url), 'utf8'));
    const count = checkAudit(report, lock);
    if (count) {
      console.warn(`Temporary exception: ${advisory} in ${count} dev build dependencies; expires 2026-11-27.`);
    }
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
