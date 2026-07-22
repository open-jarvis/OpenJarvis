#!/usr/bin/env node
// Headless crawl of the OpenJarvis frontend. Boots the backend + vite dev
// server (unless already running), clicks through every sidebar nav item
// like a user would, and reports console errors, failed network requests,
// blank/broken routes, broken images, accessibility violations, and slow
// loads — plus a desktop + mobile screenshot per page.
import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const REPORT_DIR = path.join(__dirname, 'report');
const SHOT_DIR = path.join(REPORT_DIR, 'screenshots');

const BACKEND_URL = process.env.AUDIT_BACKEND_URL || 'http://127.0.0.1:8000';
const FRONTEND_URL = process.env.AUDIT_FRONTEND_URL || 'http://127.0.0.1:5173';
const SKIP_START = process.argv.includes('--no-start');
const VERBOSE = process.argv.includes('--verbose');

const DESKTOP_VIEWPORT = { width: 1440, height: 900 };
const MOBILE_VIEWPORT = { width: 390, height: 844 };
const SLOW_LOAD_MS = 2000;

function log(...args) {
  console.log('[site-audit]', ...args);
}

async function isUp(url) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(2000) });
    return res.status < 500;
  } catch {
    return false;
  }
}

async function waitFor(url, timeoutMs, label) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await isUp(url)) return;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`Timed out waiting for ${label} at ${url}`);
}

function spawnService(label, cmd, args, cwd) {
  log(`starting ${label}: ${cmd} ${args.join(' ')} (cwd=${cwd})`);
  const child = spawn(cmd, args, {
    cwd,
    // own process group so teardown can kill vite/uvicorn's own children too
    detached: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stdout.on('data', (d) => VERBOSE && process.stdout.write(`[${label}] ${d}`));
  child.stderr.on('data', (d) => VERBOSE && process.stderr.write(`[${label}] ${d}`));
  child.on('error', (err) => log(`${label} failed to start: ${err.message}`));
  return child;
}

function killService(label, child) {
  if (!child || child.killed) return;
  try {
    log(`stopping ${label}`);
    process.kill(-child.pid, 'SIGTERM');
  } catch (err) {
    log(`could not stop ${label}: ${err.message}`);
  }
}

// Dismisses first-visit/full-screen modals (e.g. the opt-in dialog) that
// use the app's `.fixed.inset-0.z-50` overlay pattern and would otherwise
// intercept every click for the rest of the crawl. No-op if none is open.
async function dismissBlockingOverlay(page) {
  const overlayButton = page.locator('.fixed.inset-0.z-50 button').first();
  const present = await overlayButton.isVisible({ timeout: 1500 }).catch(() => false);
  if (!present) return;
  log('dismissing a blocking modal/overlay');
  await overlayButton.click().catch(() => {});
  await page.waitForTimeout(200);
}

async function runAudit() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: DESKTOP_VIEWPORT });
  const page = await context.newPage();

  const consoleIssues = [];
  const networkIssues = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' || msg.type() === 'warning') {
      consoleIssues.push({ type: msg.type(), text: msg.text() });
    }
  });
  page.on('pageerror', (err) => {
    consoleIssues.push({ type: 'pageerror', text: err.message });
  });
  page.on('requestfailed', (req) => {
    networkIssues.push({ url: req.url(), reason: req.failure()?.errorText || 'request failed' });
  });
  page.on('response', (res) => {
    if (res.status() >= 400) {
      networkIssues.push({ url: res.url(), status: res.status() });
    }
  });

  log('loading app shell...');
  // NOT 'networkidle': Vite's dev-server HMR socket (and the app's own
  // polling) stays open indefinitely, so networkidle never fires and every
  // wait stalls for its full timeout. Wait for the sidebar to actually
  // render instead, which is what a real user would wait for.
  await page.goto(FRONTEND_URL, { waitUntil: 'domcontentloaded' });
  await page.locator('nav button').first().waitFor({ state: 'visible', timeout: 15_000 });
  await dismissBlockingOverlay(page);

  const navLabels = await page.locator('nav button').allInnerTexts();
  log(`discovered ${navLabels.length} nav items: ${navLabels.join(', ')}`);

  const pages = [];
  for (const label of navLabels) {
    const consoleBefore = consoleIssues.length;
    const networkBefore = networkIssues.length;
    const issues = [];

    try {
      // Client-side route change, not a real navigation — no load event to
      // wait for. Give React + its data fetch a moment to settle instead.
      await page.locator('nav button', { hasText: label }).first().click();
      await page.waitForTimeout(800);
      await dismissBlockingOverlay(page);
    } catch (err) {
      log(`  ${label}: could not click nav item — ${err.message.split('\n')[0]}`);
      issues.push({ category: 'navigation', severity: 'critical', detail: `Clicking sidebar item "${label}" failed: ${err.message.split('\n')[0]}` });
      pages.push({ label, url: page.url(), slug: label.toLowerCase().replace(/[^a-z0-9]+/g, '-'), blank: true, timing: null, issues });
      await page.keyboard.press('Escape').catch(() => {});
      continue;
    }

    const url = page.url();
    const slug = label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-+|-+$)/g, '') || 'page';
    let blank = false;
    let timing = null;

    try {
      const mainState = await page.evaluate(() => {
        const main = document.querySelector('main');
        if (!main) return { present: false, textLength: 0, childCount: 0 };
        return {
          present: true,
          textLength: main.innerText.trim().length,
          childCount: main.children.length,
        };
      });
      blank = !mainState.present || (mainState.textLength === 0 && mainState.childCount === 0);

      const brokenImages = await page.evaluate(() =>
        Array.from(document.images)
          .filter((img) => img.complete && img.naturalWidth === 0)
          .map((img) => img.currentSrc || img.src),
      );

      timing = await page.evaluate(() => {
        const entry = performance.getEntriesByType('navigation')[0];
        return entry ? { domContentLoaded: entry.domContentLoadedEventEnd, load: entry.loadEventEnd } : null;
      });

      let axeViolations = [];
      try {
        const axeResults = await new AxeBuilder({ page }).analyze();
        axeViolations = axeResults.violations.map((v) => ({
          id: v.id,
          impact: v.impact || 'moderate',
          help: v.help,
          nodes: v.nodes.length,
        }));
      } catch (err) {
        axeViolations = [{ id: 'axe-error', impact: 'unknown', help: err.message, nodes: 0 }];
      }

      await page.screenshot({ path: path.join(SHOT_DIR, `${slug}-desktop.png`), fullPage: true });
      await page.setViewportSize(MOBILE_VIEWPORT);
      await page.waitForTimeout(150);
      await page.screenshot({ path: path.join(SHOT_DIR, `${slug}-mobile.png`), fullPage: true });
      await page.setViewportSize(DESKTOP_VIEWPORT);

      if (blank) {
        issues.push({
          category: 'navigation',
          severity: 'critical',
          detail: `Sidebar item "${label}" navigated to ${url} but rendered a blank page (no matching route or empty component).`,
        });
      }
      for (const c of consoleIssues.slice(consoleBefore)) {
        issues.push({ category: 'console', severity: c.type === 'pageerror' ? 'critical' : 'warning', detail: c.text });
      }
      for (const n of networkIssues.slice(networkBefore)) {
        issues.push({ category: 'network', severity: 'error', detail: n.status ? `HTTP ${n.status} — ${n.url}` : `${n.reason} — ${n.url}` });
      }
      for (const img of brokenImages) {
        issues.push({ category: 'images', severity: 'warning', detail: `Broken image: ${img}` });
      }
      for (const v of axeViolations) {
        issues.push({ category: 'accessibility', severity: v.impact, detail: `${v.id}: ${v.help} (${v.nodes} node(s))` });
      }
      if (timing && timing.load > SLOW_LOAD_MS) {
        issues.push({ category: 'performance', severity: 'warning', detail: `Page load took ${Math.round(timing.load)}ms (>${SLOW_LOAD_MS}ms)` });
      }
    } catch (err) {
      log(`  ${label}: error while inspecting page — ${err.message.split('\n')[0]}`);
      issues.push({ category: 'crawl-error', severity: 'critical', detail: `Inspection failed on "${label}": ${err.message.split('\n')[0]}` });
    }

    pages.push({ label, url, slug, blank, timing, issues });
    log(`  ${label} -> ${url}: ${issues.length} issue(s)${blank ? ' [BLANK PAGE]' : ''}`);
  }

  await browser.close();
  return { generatedAt: new Date().toISOString(), pages };
}

async function writeReport(report) {
  await writeFile(path.join(REPORT_DIR, 'report.json'), JSON.stringify(report, null, 2));

  const lines = [];
  const totalIssues = report.pages.reduce((s, p) => s + p.issues.length, 0);
  lines.push(`# Site audit — ${report.generatedAt}`, '');
  lines.push(`${report.pages.length} pages crawled, ${totalIssues} issue(s) found.`, '');

  for (const p of report.pages) {
    const marker = p.blank ? '❌' : p.issues.length ? '⚠️' : '✅';
    lines.push(`## ${marker} ${p.label} (${p.url})`, '');
    lines.push(`Screenshots: \`screenshots/${p.slug}-desktop.png\`, \`screenshots/${p.slug}-mobile.png\``, '');
    if (p.issues.length === 0) {
      lines.push('No issues found.', '');
      continue;
    }
    for (const issue of p.issues) {
      lines.push(`- **[${issue.severity}] ${issue.category}** — ${issue.detail}`);
    }
    lines.push('');
  }

  await writeFile(path.join(REPORT_DIR, 'report.md'), lines.join('\n'));
}

function printSummary(report) {
  console.log('\n=== Site audit summary ===');
  for (const p of report.pages) {
    const marker = p.blank ? '❌' : p.issues.length ? '⚠️ ' : '✅';
    const count = p.issues.length ? `${p.issues.length} issue(s)` : 'clean';
    console.log(`  ${marker} ${p.label.padEnd(14)} ${count}`);
  }
  console.log(`\nFull report: scripts/site_audit/report/report.md`);
  console.log(`Screenshots: scripts/site_audit/report/screenshots/`);
}

async function main() {
  await mkdir(SHOT_DIR, { recursive: true });

  let backendChild;
  let frontendChild;
  const backendAlreadyUp = await isUp(`${BACKEND_URL}/health`);
  const frontendAlreadyUp = await isUp(FRONTEND_URL);

  try {
    if (!SKIP_START) {
      if (!backendAlreadyUp) {
        backendChild = spawnService('backend', 'uv', ['run', 'jarvis', 'serve'], REPO_ROOT);
        await waitFor(`${BACKEND_URL}/health`, 60_000, 'backend');
      } else {
        log('backend already running at ' + BACKEND_URL + ', reusing it');
      }
      if (!frontendAlreadyUp) {
        frontendChild = spawnService(
          'frontend',
          'npm',
          ['run', 'dev', '--', '--host', '127.0.0.1', '--port', '5173', '--strictPort'],
          path.join(REPO_ROOT, 'frontend'),
        );
        await waitFor(FRONTEND_URL, 60_000, 'frontend');
      } else {
        log('frontend already running at ' + FRONTEND_URL + ', reusing it');
      }
    } else {
      await waitFor(`${BACKEND_URL}/health`, 5000, 'backend');
      await waitFor(FRONTEND_URL, 5000, 'frontend');
    }

    const report = await runAudit();
    await writeReport(report);
    printSummary(report);
    process.exitCode = report.pages.some((p) => p.issues.length > 0) ? 1 : 0;
  } finally {
    killService('frontend', frontendChild);
    killService('backend', backendChild);
  }
}

main().catch((err) => {
  console.error('[site-audit] fatal:', err);
  process.exitCode = 1;
});
