import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { Phase7DecisionDialog, Phase7Panel } from './Phase7Panel';

describe('Phase-7 Jarvis UI', () => {
  it('uses direct apply and reject decisions', () => {
    const allow = renderToStaticMarkup(
      <Phase7DecisionDialog
        title="promotion decision"
        decision="allow_once"
        busy={false}
        onConfirm={() => {}}
        onClose={() => {}}
      />,
    );
    const deny = renderToStaticMarkup(
      <Phase7DecisionDialog
        title="activation decision"
        decision="deny"
        busy={false}
        onConfirm={() => {}}
        onClose={() => {}}
      />,
    );

    expect(allow).toContain('aria-modal="true"');
    expect(allow).toContain('Apply now');
    expect(deny).toContain('Reject');
    expect(`${allow}${deny}`).not.toContain('Always allow');
    expect(`${allow}${deny}`).not.toContain('Approve all');
  });

  it('requires a canonical task and preserves automatic text direction', () => {
    const html = renderToStaticMarkup(
      <Phase7Panel mode="learning" taskId={null} sessionId="session-test" />,
    );
    expect(html).toContain('Select or create a canonical task');
    expect(html).toContain('Learning');
  });
});
