import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { ToolActionInfo, ToolArtifactInfo, ToolManifestInfo } from '../lib/api';
import { ToolActionDetails } from './CodexTasksPanel';

const action: ToolActionInfo = {
  action_id: 'action-1',
  proposal_id: 'proposal-1',
  task_id: 'task-1',
  approval_id: 'approval-1',
  tool_run_id: null,
  tool_id: 'browser.form.prepare',
  capability: 'browser:prepare',
  risk_level: 3,
  target: 'loopback synthetic form',
  expected_side_effect: 'external_write',
  verification_plan: 'observe the local confirmation marker',
  undo_plan: 'reset the synthetic form',
  status: 'waiting_approval',
  verification_status: 'pending',
  output_summary: '',
  error: '',
  retry_count: 0,
  effect_known: true,
  parameter_summary: { recipient: 'fake@example.invalid' },
  expected_result: 'local synthetic form is submitted',
  updated_at: '2026-07-30T00:00:00Z',
};

const tool: ToolManifestInfo = {
  tool_id: action.tool_id,
  name: action.tool_id,
  version: '1.0.0',
  description: 'Synthetic form preparation.',
  capability: action.capability,
  risk_level: action.risk_level,
  allowed_lanes: ['interactive_lane'],
  supported_platforms: ['windows'],
  timeout: 5,
  max_retries: 0,
  idempotency_policy: 'never_retry_after_unknown_effect',
  side_effect_class: action.expected_side_effect,
  verification_strategy: action.verification_plan,
  undo_strategy: action.undo_plan,
  required_approval: true,
  allowed_roots: ['C:\\synthetic-root'],
  network_policy: 'loopback_only',
  enabled: true,
  degraded_reason: '',
  runtime_available: true,
  healthy: true,
};

const artifact: ToolArtifactInfo = {
  artifact_id: 'artifact-1',
  action_id: action.action_id,
  kind: 'review_screenshot',
  path: 'temporary-artifact.bmp',
  sha256: 'a'.repeat(64),
  size_bytes: 1024,
  media_type: 'image/bmp',
  redacted: false,
  restore_of: null,
};

describe('ToolActionDetails', () => {
  it('shows exact effect, capability, target, undo, and artifacts', () => {
    const html = renderToStaticMarkup(
      <ToolActionDetails action={action} tool={tool} artifacts={[artifact]} />,
    );

    expect(html).not.toContain('Risk 3');
    expect(html).toContain('browser:prepare');
    expect(html).toContain('loopback synthetic form');
    expect(html).toContain('external_write');
    expect(html).toContain('reset the synthetic form');
    expect(html).toContain('review_screenshot');
    expect(html).toContain('fake@example.invalid');
  });

  it('does not expose an approval decision control', () => {
    const html = renderToStaticMarkup(
      <ToolActionDetails action={action} tool={tool} artifacts={[]} />,
    );

    expect(html).not.toContain('Allow once');
    expect(html).not.toContain('>Deny<');
  });
});
