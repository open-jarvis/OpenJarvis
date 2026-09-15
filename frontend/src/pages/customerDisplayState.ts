import type { AgentEvent } from '@/lib/useAgentEvents';

export interface CustomerMenuItem {
  id?: string;
  name: string;
  price?: number;
  available?: boolean;
  note?: string;
  image_url?: string;
  category?: string;
}

export interface CustomerDisplayLine {
  line_id?: string;
  name: string;
  size?: string;
  note?: string;
  quantity?: number;
  unit_price?: number;
  line_total?: number;
}

export type CustomerDisplayState =
  | { view: 'waiting' }
  | {
      view: 'menu';
      items: CustomerMenuItem[];
      resultComplete: boolean;
      projectedCount: number;
      publishedCount: number;
      preview: boolean;
    }
  | {
      view: 'cart';
      lines: CustomerDisplayLine[];
      total: number;
      order_note: string;
      order_type: string;
      table: string;
      table_name: string;
    }
  | {
      view: 'bill';
      order_id: string;
      status: string;
      order_type: string;
      branch: string;
      lines: CustomerDisplayLine[];
      total: number;
    }
  | {
      view: 'payment_qr';
      order_id: string;
      payment_slug: string;
      status: string;
      qr_code: string;
      total?: number;
    };

export const waitingState: CustomerDisplayState = { view: 'waiting' };

export function isSafeQrImageSource(value: string): boolean {
  if (value.startsWith('data:image/')) return true;
  try {
    return new URL(value).protocol === 'https:';
  } catch {
    return false;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function optionalString(row: Record<string, unknown>, field: string): string | undefined {
  return typeof row[field] === 'string' ? row[field] : undefined;
}

function optionalNumber(row: Record<string, unknown>, field: string): number | undefined {
  const value = row[field];
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function optionalBoolean(row: Record<string, unknown>, field: string): boolean | undefined {
  return typeof row[field] === 'boolean' ? row[field] : undefined;
}

function pickMenuItem(value: unknown): CustomerMenuItem | null {
  if (!isRecord(value) || typeof value.name !== 'string') return null;
  return {
    ...(optionalString(value, 'id') !== undefined ? { id: optionalString(value, 'id') } : {}),
    name: value.name,
    ...(optionalNumber(value, 'price') !== undefined ? { price: optionalNumber(value, 'price') } : {}),
    ...(optionalBoolean(value, 'available') !== undefined ? { available: optionalBoolean(value, 'available') } : {}),
    ...(optionalString(value, 'note') !== undefined ? { note: optionalString(value, 'note') } : {}),
    ...(optionalString(value, 'image_url') !== undefined ? { image_url: optionalString(value, 'image_url') } : {}),
    ...(optionalString(value, 'category') !== undefined ? { category: optionalString(value, 'category') } : {}),
  };
}

function pickLine(value: unknown): CustomerDisplayLine | null {
  if (!isRecord(value) || typeof value.name !== 'string') return null;
  return {
    ...(optionalString(value, 'line_id') !== undefined ? { line_id: optionalString(value, 'line_id') } : {}),
    name: value.name,
    ...(optionalString(value, 'size') !== undefined ? { size: optionalString(value, 'size') } : {}),
    ...(optionalString(value, 'note') !== undefined ? { note: optionalString(value, 'note') } : {}),
    ...(optionalNumber(value, 'quantity') !== undefined ? { quantity: optionalNumber(value, 'quantity') } : {}),
    ...(optionalNumber(value, 'unit_price') !== undefined ? { unit_price: optionalNumber(value, 'unit_price') } : {}),
    ...(optionalNumber(value, 'line_total') !== undefined ? { line_total: optionalNumber(value, 'line_total') } : {}),
  };
}

function pickRows<T>(value: unknown, pick: (row: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) return null;
  const rows: T[] = [];
  for (const valueRow of value) {
    const row = pick(valueRow);
    if (row === null) return null;
    rows.push(row);
  }
  return rows;
}

function matchingData(event: AgentEvent, sessionId: string): Record<string, unknown> | null {
  if (
    event.type !== 'display_update'
    || !isRecord(event.data)
    || event.data.presentation_session_id !== sessionId
  ) {
    return null;
  }
  return event.data;
}

export function reduceCustomerDisplay(
  state: CustomerDisplayState,
  event: AgentEvent,
  sessionId: string,
): CustomerDisplayState {
  const data = matchingData(event, sessionId);
  if (!data || typeof data.view !== 'string') return state;
  if (data.view === 'none') return waitingState;

  if (data.view === 'menu') {
    const items = pickRows(data.items, pickMenuItem);
    const projectedCount = optionalNumber(data, 'projected_count');
    const publishedCount = optionalNumber(data, 'published_count');
    return (
      items === null
      || data.result_complete !== true
      || projectedCount !== items.length
      || publishedCount !== items.length
    )
      ? state
      : {
          view: 'menu',
          items,
          resultComplete: true,
          projectedCount,
          publishedCount,
          preview: false,
        };
  }

  if (data.view === 'cart') {
    const lines = pickRows(data.lines, pickLine);
    const total = optionalNumber(data, 'total');
    return lines === null || total === undefined
      ? state
      : {
          view: 'cart',
          lines,
          total,
          order_note: optionalString(data, 'order_note') ?? '',
          order_type: optionalString(data, 'order_type') ?? '',
          table: optionalString(data, 'table') ?? '',
          table_name: optionalString(data, 'table_name') ?? '',
        };
  }

  if (data.view === 'bill') {
    const lines = pickRows(data.lines, pickLine);
    const total = optionalNumber(data, 'total');
    if (
      lines === null
      || total === undefined
      || typeof data.order_id !== 'string'
      || typeof data.status !== 'string'
      || typeof data.order_type !== 'string'
      || typeof data.branch !== 'string'
    ) return state;
    return {
      view: 'bill',
      order_id: data.order_id,
      status: data.status,
      order_type: data.order_type,
      branch: data.branch,
      lines,
      total,
    };
  }

  if (
    data.view === 'payment_qr'
    && typeof data.order_id === 'string'
    && typeof data.payment_slug === 'string'
    && typeof data.status === 'string'
    && typeof data.qr_code === 'string'
  ) {
    const priorTotal = ('total' in state && typeof state.total === 'number') ? state.total : undefined;
    const incomingTotal = optionalNumber(data, 'total');
    const finalTotal = incomingTotal !== undefined ? incomingTotal : priorTotal;

    return {
      view: 'payment_qr',
      order_id: data.order_id,
      payment_slug: data.payment_slug,
      status: data.status,
      qr_code: data.qr_code,
      ...(finalTotal !== undefined ? { total: finalTotal } : {}),
    };
  }

  return state;
}
