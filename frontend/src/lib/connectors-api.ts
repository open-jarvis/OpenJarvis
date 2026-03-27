import { getBase } from './api';
import type { ConnectorInfo, SyncStatus, ConnectRequest } from '../types/connectors';

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

export async function connectSource(id: string, req: ConnectRequest): Promise<ConnectorInfo> {
  const res = await fetch(`${getBase()}/v1/connectors/${encodeURIComponent(id)}/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`Failed to connect ${id}: ${res.status}`);
  return res.json();
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
