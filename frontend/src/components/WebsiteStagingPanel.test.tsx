import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { WebsiteStagingWorkspace } from '../lib/api';
import { WebsiteStagingPanel, WebsiteStagingSummary } from './WebsiteStagingPanel';

const workspace: WebsiteStagingWorkspace = {
  schema_version: '1.0',
  workspace_id: 'workspace-test',
  plan: {
    request: {
      request_id: 'request-test',
      task_id: 'task-test',
      session_id: 'session-test',
      correlation_id: 'correlation-test',
      workspace_id: 'workspace-test',
      idempotency_key: 'idempotency-test',
    },
    proposals: [{
      relative_path: 'index.html',
      media_type: 'text/html',
      size_bytes: 42,
      proposed_sha256: 'a'.repeat(64),
      expected_before_sha256: null,
    }],
    file_diffs: [{
      relative_path: 'index.html',
      change: 'created',
      before_sha256: null,
      after_sha256: 'a'.repeat(64),
      size_bytes: 42,
    }],
    risk_level: 1,
    warnings: ['External URL not fetched'],
    external_urls: ['https://example.invalid'],
    script_files: ['app.js'],
    preview_hash: 'b'.repeat(64),
    predicted_manifest_sha256: 'c'.repeat(64),
  },
  execution: {
    execution_id: 'execution-test',
    status: 'completed',
    no_op: false,
    after_manifest_sha256: 'c'.repeat(64),
    artifact_manifest_sha256: 'd'.repeat(64),
    verification_hash: 'e'.repeat(64),
    trace_evaluation_hash: 'f'.repeat(64),
  },
  verification: {
    status: 'passed',
    passed: true,
    file_count: 1,
    total_bytes: 42,
    manifest_sha256: 'c'.repeat(64),
    errors: [],
    warnings: [],
    verification_hash: 'e'.repeat(64),
  },
  artifact_manifest: {
    manifest_sha256: 'd'.repeat(64),
    artifacts: [{
      artifact_id: 'artifact-test',
      relative_path: 'index.html',
      media_type: 'text/html',
      size_bytes: 42,
      sha256: 'a'.repeat(64),
      verification_status: 'passed',
      warnings: [],
    }],
  },
};

describe('isolated website staging UI', () => {
  it('shows the non-publication boundary without remembered approval', () => {
    const html = renderToStaticMarkup(<WebsiteStagingPanel />);
    expect(html).toContain('Nur isolierter lokaler Workspace – keine Veröffentlichung');
    expect(html).toContain('No real project path can be entered here');
    expect(html).not.toContain('Always allow');
  });

  it('renders preview, verification, artifacts, and rollback controls', () => {
    const html = renderToStaticMarkup(<WebsiteStagingSummary workspace={workspace} />);
    expect(html).toContain('Preview diff');
    expect(html).toContain('Planned files');
    expect(html).toContain('Checkpoint ready');
    expect(html).toContain('Apply result');
    expect(html).toContain('Verification');
    expect(html).toContain('Artifacts');
    expect(html).toContain('Rollback now');
    expect(html).not.toContain('Always allow');
  });

  it('uses direct apply and reject language', () => {
    const previewOnly = { ...workspace, execution: undefined, verification: undefined, artifact_manifest: undefined };
    const html = renderToStaticMarkup(<WebsiteStagingSummary workspace={previewOnly} />);
    expect(html).toContain('Apply now');
    expect(html).toContain('Deny');
    expect(html).not.toContain('Always allow');
  });
});
