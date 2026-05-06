import { getBase, getAuthHeaders } from './api';
import type { ConnectorInfo, SyncStatus, ConnectRequest } from '../types/connectors';

// ---------------------------------------------------------------------------
// Connectors API
// ---------------------------------------------------------------------------

export async function listConnectors(): Promise<ConnectorInfo[]> {
  const res = await fetch(`${getBase()}/v1/connectors`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error(`Failed to list connectors: ${res.status}`);
  const data = await res.json();
  return data.connectors || [];
}

export async function getConnector(id: string): Promise<ConnectorInfo> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error(`Failed to get connector ${id}: ${res.status}`);
  return res.json();
}

export async function connectSource(id: string, req: ConnectRequest): Promise<ConnectorInfo> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`Failed to connect ${id}: ${res.status}`);
  return res.json();
}

export async function disconnectSource(id: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}/disconnect`, {
    method: 'POST',
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to disconnect ${id}: ${res.status}`);
}

export async function getSyncStatus(id: string): Promise<SyncStatus> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}/sync`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error(`Failed to get sync status for ${id}: ${res.status}`);
  return res.json();
}

export async function triggerSync(id: string): Promise<{ connector_id: string; chunks_indexed: number; status: string }> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}/sync`, {
    method: 'POST',
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Sync failed: ${res.status}`);
  }
  return res.json();
}
