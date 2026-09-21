import { describe, expect, it } from 'vitest';

import { serializeToolCallArguments } from './tool-call';

describe('serializeToolCallArguments', () => {
  it('preserves JSON strings', () => {
    expect(serializeToolCallArguments('{"query":"python"}')).toBe(
      '{"query":"python"}',
    );
  });

  it('serializes parsed argument objects', () => {
    expect(serializeToolCallArguments({ query: 'python' })).toBe(
      '{"query":"python"}',
    );
  });

  it('uses an empty string for missing arguments', () => {
    expect(serializeToolCallArguments(null)).toBe('');
    expect(serializeToolCallArguments(undefined)).toBe('');
  });
});
