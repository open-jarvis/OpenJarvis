import { describe, expect, it } from 'vitest';

import type { AgentEvent } from '@/lib/useAgentEvents';
import {
  isSafeQrImageSource,
  reduceCustomerDisplay,
  waitingState,
  type CustomerDisplayState,
} from './customerDisplayState';

function displayEvent(
  sessionId: string,
  data: Record<string, unknown>,
): AgentEvent {
  return {
    type: 'display_update',
    timestamp: 0,
    data: { ...data, presentation_session_id: sessionId },
  };
}

function verifiedMenu(items: Record<string, unknown>[]) {
  return {
    view: 'menu',
    items,
    result_complete: true,
    projected_count: items.length,
    published_count: items.length,
  };
}

describe('reduceCustomerDisplay', () => {
  it('accepts a matching menu event and ignores another session', () => {
    const state = reduceCustomerDisplay(waitingState, displayEvent('A', verifiedMenu([
      { id: 'latte', name: 'Latte', price: 45000 },
    ])), 'A');

    expect(state).toEqual({
      view: 'menu',
      items: [{ id: 'latte', name: 'Latte', price: 45000 }],
      resultComplete: true,
      projectedCount: 1,
      publishedCount: 1,
      preview: false,
    });
    expect(reduceCustomerDisplay(
      state,
      displayEvent('B', { view: 'none' }),
      'A',
    )).toBe(state);
  });

  it.each([0, 1, 6, 7, 100])('accepts all %i verified menu items', (count) => {
    const items = Array.from({ length: count }, (_, index) => ({
      id: `item-${index}`,
      name: `Item ${index}`,
    }));

    expect(reduceCustomerDisplay(
      waitingState,
      displayEvent('A', verifiedMenu(items)),
      'A',
    )).toEqual({
      view: 'menu',
      items,
      resultComplete: true,
      projectedCount: count,
      publishedCount: count,
      preview: false,
    });
  });

  it('retains previous state when complete menu counts do not match', () => {
    const prior = waitingState;
    const data = verifiedMenu([{ id: 'one', name: 'One' }]);

    for (const mismatch of [
      { ...data, projected_count: 2 },
      { ...data, published_count: 0 },
      { ...data, result_complete: false },
    ]) {
      expect(reduceCustomerDisplay(prior, displayEvent('A', mismatch), 'A')).toBe(prior);
    }
  });

  it('returns waiting state on a matching reset event', () => {
    const menuState: CustomerDisplayState = {
      view: 'menu',
      items: [{ id: 'latte', name: 'Latte', price: 45000 }],
      resultComplete: true,
      projectedCount: 1,
      publishedCount: 1,
      preview: false,
    };

    expect(reduceCustomerDisplay(
      menuState,
      displayEvent('A', { view: 'none' }),
      'A',
    )).toEqual(waitingState);
  });

  it('ignores malformed payloads and drops fields the display does not render', () => {
    const state = reduceCustomerDisplay(waitingState, displayEvent('A', verifiedMenu([
      { id: 'latte', price: 45000 },
    ])), 'A');
    expect(state).toBe(waitingState);

    expect(reduceCustomerDisplay(waitingState, displayEvent('A', verifiedMenu([
      { id: 'latte', name: 'Latte', price: 45000, html: '<script>x</script>' },
    ])), 'A')).toEqual({
      view: 'menu',
      items: [{ id: 'latte', name: 'Latte', price: 45000 }],
      resultComplete: true,
      projectedCount: 1,
      publishedCount: 1,
      preview: false,
    });
  });

  it('ignores null and non-record event data without throwing', () => {
    const state: CustomerDisplayState = {
      view: 'menu',
      items: [{ id: 'latte', name: 'Latte', price: 45000 }],
      resultComplete: true,
      projectedCount: 1,
      publishedCount: 1,
      preview: false,
    };

    for (const data of [null, 'not-an-object']) {
      const event = {
        type: 'display_update',
        timestamp: 0,
        data,
      } as unknown as AgentEvent;
      expect(reduceCustomerDisplay(state, event, 'A')).toBe(state);
    }
  });

  it('keeps normalized draft identity, prices, notes, and order type', () => {
    expect(reduceCustomerDisplay(waitingState, displayEvent('A', {
      view: 'cart',
      lines: [{
        line_id: 'line-1',
        name: 'Cà phê sữa',
        size: 'tiêu chuẩn',
        note: 'ít đá',
        quantity: 3,
        unit_price: 40000,
        line_total: 120000,
        html: '<script>x</script>',
      }],
      total: 120000,
      order_note: 'Làm nhanh giúp mình',
      order_type: 'at-table',
      table: 'table-73',
      table_name: '73',
      provider_status: 'invented',
    }), 'A')).toEqual({
      view: 'cart',
      lines: [{
        line_id: 'line-1',
        name: 'Cà phê sữa',
        size: 'tiêu chuẩn',
        note: 'ít đá',
        quantity: 3,
        unit_price: 40000,
        line_total: 120000,
      }],
      total: 120000,
      order_note: 'Làm nhanh giúp mình',
      order_type: 'at-table',
      table: 'table-73',
      table_name: '73',
    });
  });

  it('accepts a normalized bill and drops invented line fields', () => {
    expect(reduceCustomerDisplay(waitingState, displayEvent('A', {
      view: 'bill',
      order_id: 'order-1',
      status: 'placed',
      order_type: 'take-out',
      branch: 'br-thu-duc',
      lines: [{
        name: 'Cà phê đen',
        quantity: 2,
        line_total: 70000,
        html: '<script>x</script>',
      }],
      total: 70000,
      receipt_id: 'invented-receipt',
    }), 'A')).toEqual({
      view: 'bill',
      order_id: 'order-1',
      status: 'placed',
      order_type: 'take-out',
      branch: 'br-thu-duc',
      lines: [{ name: 'Cà phê đen', quantity: 2, line_total: 70000 }],
      total: 70000,
    });
  });

  it('accepts only the normalized payment QR fields', () => {
    expect(reduceCustomerDisplay(waitingState, displayEvent('A', {
      view: 'payment_qr',
      order_id: 'order-1',
      payment_slug: 'payment-1',
      status: 'pending',
      qr_code: 'merchant-opaque-qr',
      total: 45000,
      html: '<img src=x onerror=alert(1)>',
      receipt_id: 'receipt-that-must-not-be-shown',
    }), 'A')).toEqual({
      view: 'payment_qr',
      order_id: 'order-1',
      payment_slug: 'payment-1',
      status: 'pending',
      qr_code: 'merchant-opaque-qr',
      total: 45000,
    });
  });

  it('inherits total from prior bill/cart state if omitted in payment_qr event', () => {
    const priorBill: CustomerDisplayState = {
      view: 'bill',
      order_id: 'order-1',
      status: 'placed',
      order_type: 'take-out',
      branch: 'br-thu-duc',
      lines: [{ name: 'Cà phê đen', quantity: 1, line_total: 40000 }],
      total: 40000,
    };

    expect(reduceCustomerDisplay(priorBill, displayEvent('A', {
      view: 'payment_qr',
      order_id: 'order-1',
      payment_slug: 'payment-1',
      status: 'pending',
      qr_code: 'merchant-opaque-qr',
    }), 'A')).toEqual({
      view: 'payment_qr',
      order_id: 'order-1',
      payment_slug: 'payment-1',
      status: 'pending',
      qr_code: 'merchant-opaque-qr',
      total: 40000,
    });
  });
});

describe('isSafeQrImageSource', () => {
  it('allows only HTTPS and inline image values to load as images', () => {
    expect(isSafeQrImageSource('https://payments.example/qr.png')).toBe(true);
    expect(isSafeQrImageSource('data:image/png;base64,abc')).toBe(true);
    expect(isSafeQrImageSource('http://payments.example/qr.png')).toBe(false);
    expect(isSafeQrImageSource('javascript:alert(1)')).toBe(false);
    expect(isSafeQrImageSource('merchant-opaque-qr')).toBe(false);
  });
});
