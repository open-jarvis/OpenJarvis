import assert from 'node:assert/strict';
import { test } from 'node:test';
import { checkAudit } from './check-audit.mjs';

const now = Date.parse('2026-10-28T12:00:00Z');
function fixture() {
  const vulnerabilities = {};
  const packages = {};
  for (const [name, via] of [
    ['deepmerge', [{ url: 'https://github.com/advisories/GHSA-gcqx-w48m-w2h4', severity: 'low' }]],
    ['@rollup/plugin-node-resolve', ['deepmerge']],
    ['workbox-build', ['@rollup/plugin-node-resolve']],
    ['vite-plugin-pwa', ['workbox-build']],
  ]) {
    const node = `node_modules/${name}`;
    vulnerabilities[name] = { severity: 'low', via, nodes: [node] };
    packages[node] = { dev: true };
  }
  return [{ auditReportVersion: 2, vulnerabilities }, { packages }];
}

test('accepts a clean report and only the known dev advisory chain', () => {
  assert.equal(checkAudit({ auditReportVersion: 2, vulnerabilities: {} }, {}, now), 0);
  assert.equal(checkAudit(...fixture(), now), 4);
});

test('rejects a different advisory, including another low-severity finding', () => {
  const [report, lock] = fixture();
  report.vulnerabilities.deepmerge.via[0].url = 'https://github.com/advisories/GHSA-other';
  assert.throws(() => checkAudit(report, lock, now), /Unaccepted/);
});

test('rejects severity increases and additional causes on a known package', () => {
  for (const severity of ['moderate', 'high', 'critical']) {
    const [report, lock] = fixture();
    report.vulnerabilities.deepmerge.severity = severity;
    assert.throws(() => checkAudit(report, lock, now), /Unaccepted/);
  }
  const [report, lock] = fixture();
  report.vulnerabilities['workbox-build'].via.push('another-package');
  assert.throws(() => checkAudit(report, lock, now), /Unaccepted/);
});

test('rejects runtime dependencies and unknown packages', () => {
  const [report, lock] = fixture();
  lock.packages['node_modules/deepmerge'].dev = false;
  assert.throws(() => checkAudit(report, lock, now), /Unaccepted/);
  const [other, otherLock] = fixture();
  other.vulnerabilities.unrelated = { severity: 'low', via: ['deepmerge'], nodes: [] };
  assert.throws(() => checkAudit(other, otherLock, now), /Unaccepted/);
});

test('rejects expired exceptions and malformed/network error reports', () => {
  assert.throws(() => checkAudit(...fixture(), Date.parse('2026-11-27')), /Unaccepted/);
  for (const report of [null, {}, { error: { code: 'ENETUNREACH' } },
    { auditReportVersion: 2, vulnerabilities: [] }]) {
    assert.throws(() => checkAudit(report, {}, now), /valid vulnerability report/);
  }
});
