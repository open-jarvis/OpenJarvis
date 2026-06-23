import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = resolve(__dirname, '../../..');

const publicSupabaseSources = [
  'frontend/src/lib/api.ts',
  'frontend/src/components/Desktop/SavingsDashboard.tsx',
  'docs/javascripts/leaderboard.js',
];

describe('public Supabase configuration', () => {
  it('does not hardcode the Supabase project URL or anon JWT in public sources', () => {
    for (const source of publicSupabaseSources) {
      const text = readFileSync(resolve(repoRoot, source), 'utf8');

      expect(text, source).not.toMatch(/https:\/\/[a-z0-9]{20}\.supabase\.co/);
      expect(text, source).not.toMatch(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/);
    }
  });
});
