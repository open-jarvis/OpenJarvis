import { describe, expect, it } from 'vitest';

import { voiceStatusText } from './voiceStatus';

describe('voiceStatusText', () => {
  it('keeps a recoverable voice error visible while listening resumes', () => {
    expect(voiceStatusText('listening', 'artifact_missing')).toBe('artifact_missing');
  });

  it('reports plain status text while voice is running', () => {
    expect(voiceStatusText('speaking', null)).toBe('Speaking...');
  });

  it('reports pre-audio activity statuses', () => {
    expect(voiceStatusText('inference', null)).toBe('Inferring...');
    expect(voiceStatusText('tool', null)).toBe('Running tool...');
  });
});
