import { describe, expect, it } from 'vitest';

describe('Cloud Models catalogue', () => {
  it('offers gpt-5.6-luna under OpenAI', async () => {
    globalThis.localStorage = {
      getItem: () => null,
      setItem: () => undefined,
    } as unknown as Storage;
    const commandPalette = await import('./CommandPalette');
    const providers = (
      commandPalette as unknown as {
        CLOUD_PROVIDERS?: Array<{
          name: string;
          models: Array<{ id: string }>;
        }>;
      }
    ).CLOUD_PROVIDERS;

    const openAI = providers?.find((provider) => provider.name === 'OpenAI');
    expect(openAI?.models.map((model) => model.id) ?? []).toContain('gpt-5.6-luna');
  });
});
