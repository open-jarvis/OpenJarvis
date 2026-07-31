import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { EvidenceSources } from './MemoryVaultPanel';

describe('EvidenceSources', () => {
  it('renders only selected sources with note identity, path, span, and reason', () => {
    const html = renderToStaticMarkup(
      <EvidenceSources
        sources={[
          {
            source_id: 'source-1',
            retrieval_id: 'retrieval-1',
            note_id: '11111111-1111-4111-8111-111111111111',
            path: 'projects/synthetic.md',
            title: 'Synthetic source',
            relevant_text: 'Python is the selected synthetic fact.',
            line_start: 8,
            line_end: 9,
            section: 'Preferences',
            score: 0.91,
            selection_reason: 'title_alias_bm25',
            content_hash: 'abc',
            indexed_at: '2026-07-30T00:00:00Z',
            note_type: 'system_policy',
            trust_class: 'authority_sensitive_source',
            retrieval_class: 'explicit_review_only',
            authority_class: 'prohibited_runtime_authority',
            scope_class: 'explicit_review_only',
          },
        ]}
      />,
    );

    expect(html).toContain('Synthetic source');
    expect(html).toContain('projects/synthetic.md');
    expect(html).toContain('lines 8–9');
    expect(html).toContain('title_alias_bm25');
    expect(html).toContain('authority_sensitive_source');
    expect(html).toContain('explicit_review_only');
    expect(html).toContain('prohibited_runtime_authority');
    expect(html).not.toContain('unselected source');
  });

  it('shows the explicit insufficient-evidence marker', () => {
    const html = renderToStaticMarkup(<EvidenceSources sources={[]} />);
    expect(html).toContain('insufficient_evidence');
  });
});
