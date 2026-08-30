import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../lib/api', () => ({
  getSetupStatus: vi.fn(async () => null),
  fetchModels: vi.fn(async () => []),
  fetchRecommendedModel: vi.fn(async () => ({ model: '', reason: '' })),
  inferenceSourceConfigured: vi.fn(async () => false),
  relaunchApp: vi.fn(async () => undefined),
  setInferenceSource: vi.fn(async () => undefined),
}));
vi.mock('../lib/store', () => ({
  useAppStore: { getState: vi.fn(() => ({ selectedModel: '', setModels: vi.fn(), setModelsLoading: vi.fn(), setSelectedModel: vi.fn() })) },
}));

import { CustomSourceForm, SetupScreen, SourceChoice } from './SetupScreen';

describe('first-run inference source chooser (#274)', () => {
  it('offers the bundled engine and an existing server before booting anything', () => {
    const html = renderToStaticMarkup(<SourceChoice onChosen={vi.fn()} />);

    expect(html).toContain('How would you like to run inference?');
    expect(html).toContain('Bundled Ollama');
    expect(html).toContain('Existing server');
    expect(html).toContain('LM Studio');
  });

  it('shows the custom-endpoint form fields for an existing server', () => {
    const html = renderToStaticMarkup(
      <div>
        <CustomSourceForm />
      </div>,
    );

    expect(html).toContain('Server URL');
    expect(html).toContain('Model');
    expect(html).toContain('Server type');
    expect(html).toContain('LM Studio');
    expect(html).toContain('Save &amp; Restart OpenJarvis');
    // The endpoint backend requires host + model — Save stays disabled until
    // both are filled (model starts empty).
    expect(html).toMatch(/<button[^>]*disabled/);
  });

  it('shows neither the chooser nor the steps while first-run state is unknown', () => {
    const html = renderToStaticMarkup(<SetupScreen onReady={vi.fn()} />);

    expect(html).not.toContain('How would you like to run inference?');
    expect(html).not.toContain('Inference Engine');
    expect(html).not.toContain('Starting Ollama');
  });
});
