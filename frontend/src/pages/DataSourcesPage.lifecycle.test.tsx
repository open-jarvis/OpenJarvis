import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../lib/store', () => ({ useAppStore: vi.fn() }));

import { SyncStatusDisplay } from './DataSourcesPage';
import type { SyncStatus } from '../types/connectors';

const baseStatus: SyncStatus = {
  state: 'idle',
  items_synced: 0,
  items_total: 0,
  last_sync: null,
  error: null,
};

function renderStatus(sync: SyncStatus, disabled = false): string {
  return renderToStaticMarkup(
    <SyncStatusDisplay
      chunks={0}
      sync={sync}
      unitLabel="items"
      connectorId="obsidian"
      disabled={disabled}
      onSyncTriggered={vi.fn()}
    />,
  );
}

describe('connector lifecycle status', () => {
  it('renders pending cleanup without a competing sync action', () => {
    const html = renderStatus({ ...baseStatus, state: 'stopping' });

    expect(html).toContain('Disconnect pending');
    expect(html).toContain('cleaned up before this source disconnects');
    expect(html).not.toContain('<button');
  });

  it('disables sync while another connector lifecycle action is active', () => {
    const html = renderStatus(baseStatus, true);

    expect(html).toContain('Sync Now');
    expect(html).toMatch(/<button[^>]*disabled/);
  });
});
