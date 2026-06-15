import { getBase } from './api';
import type { ConnectorInfo, SyncStatus, ConnectRequest, ConnectResponse } from '../types/connectors';

// ---------------------------------------------------------------------------
// Connectors API
// ---------------------------------------------------------------------------

export async function listConnectors(): Promise<ConnectorInfo[]> {
  const res = await fetch(`${getBase()}/v1/connectors`);
  if (!res.ok) throw new Error(`Failed to list connectors: ${res.status}`);
  const data = await res.json();
  return data.connectors || [];
}

export async function getConnector(id: string): Promise<ConnectorInfo> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`Failed to get connector ${id}: ${res.status}`);
  return res.json();
}

export async function connectSource(id: string, req: ConnectRequest): Promise<ConnectResponse> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    // Surface the backend's actionable detail (e.g. malformed Client ID /
    // Secret) instead of a bare status code so the UI can render it.
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to connect ${id}: ${res.status}`);
  }
  return res.json();
}

/** Open the server-side OAuth consent flow in a popup and resolve once the
 *  connector reports connected (or reject on timeout). Reused for any OAuth
 *  connector whose /connect returned `oauth_required` (issue #512). */
export function startServerOAuth(id: string, oauthStartPath?: string): Promise<void> {
  const path = oauthStartPath || `/v1/connectors/${encodeURIComponent(id)}/oauth/start`;
  window.open(`${getBase()}${path}`, '_blank', 'width=600,height=700');
  return new Promise((resolve, reject) => {
    const interval = setInterval(async () => {
      try {
        const info = await getConnector(id);
        if (info.connected) {
          clearInterval(interval);
          clearTimeout(timer);
          resolve();
        }
      } catch {
        // ignore transient polling errors
      }
    }, 2000);
    const timer = setTimeout(() => {
      clearInterval(interval);
      reject(new Error('Authorization timed out — please try again.'));
    }, 180000);
  });
}

export async function disconnectSource(id: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}/disconnect`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`Failed to disconnect ${id}: ${res.status}`);
}

export async function getSyncStatus(id: string): Promise<SyncStatus> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}/sync`);
  if (!res.ok) throw new Error(`Failed to get sync status for ${id}: ${res.status}`);
  return res.json();
}

export async function triggerSync(id: string): Promise<{ connector_id: string; chunks_indexed: number; status: string }> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}/sync`, {
    method: 'POST',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Sync failed: ${res.status}`);
  }
  return res.json();
}
