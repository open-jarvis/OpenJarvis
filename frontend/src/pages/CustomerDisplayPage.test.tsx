import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';

import {
  BillView,
  CartView,
  CustomerDisplayPage,
  MenuView,
  PaymentQrView,
} from './CustomerDisplayPage';

function renderMenu(count: number, preview = false): string {
  const items = Array.from({ length: count }, (_, index) => ({
    id: `item-${index}`,
    name: `Item ${index}`,
    price: index,
  }));
  return renderToStaticMarkup(
    <MenuView
      items={items}
      resultComplete={!preview}
      projectedCount={count}
      publishedCount={count}
      preview={preview}
    />,
  );
}

describe('MenuView', () => {
  it('renders every one of 100 verified menu items', () => {
    const markup = renderMenu(100);

    expect(markup.match(/data-menu-item=/g)).toHaveLength(100);
  });

  it('gives the customer display route its own viewport scroll container', () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/customer-display?preview=menu']}>
        <CustomerDisplayPage />
      </MemoryRouter>,
    );
    const rootClass = markup.match(/<div class="([^"]+)"/)?.[1].split(' ') ?? [];

    expect(rootClass).toContain('h-screen');
    expect(rootClass).toContain('overflow-y-auto');
    expect(rootClass).not.toContain('min-h-screen');
  });

  it('renders verified zero as no results, never demo content', () => {
    const markup = renderMenu(0);

    expect(markup).not.toContain('data-menu-item=');
    expect(markup).toContain('Không có kết quả phù hợp');
    expect(markup).not.toContain('MÌ Ý BÒ BẰM');
    expect(markup).not.toContain('CATEGORIES');
  });

  it('keeps intentional menu preview demo content', () => {
    const markup = renderMenu(0, true);

    expect(markup).toContain('MÌ Ý BÒ BẰM');
    expect(markup).toContain('data-menu-item=');
  });
});

describe('CartView', () => {
  it('renders only the local cart facts and never invents an order', () => {
    const markup = renderToStaticMarkup(
      <CartView
        lines={[{
          line_id: 'line-1',
          name: 'Cà phê sữa',
          size: 'tiêu chuẩn',
          note: 'ít đá',
          quantity: 3,
          unit_price: 40000,
          line_total: 120000,
        }]}
        total={120000}
        order_note="Làm nhanh giúp mình"
        order_type="at-table"
        table_name="73"
      />,
    );

    expect(markup).toContain('CART');
    expect(markup).toContain('CHƯA TẠO ĐƠN HÀNG');
    expect(markup).toContain('Cà phê sữa');
    expect(markup).toContain('ít đá');
    expect(markup).toContain('Làm nhanh giúp mình');
    expect(markup).toContain('TẠI BÀN');
    expect(markup).toContain('73');
    expect(markup).not.toContain('ORDER SLIP');
    expect(markup).not.toContain('TC-000245');
    expect(markup).not.toContain('AUGUST 28, 2026');
    expect(markup).not.toContain('9999.8888.68');
  });
});

describe('BillView', () => {
  it('renders invoice luxury layout and items', () => {
    const markup = renderToStaticMarkup(
      <BillView
        order_id="order-1"
        branch="Trend Coffee Thủ Đức"
        order_type="take-out"
        status="pending"
        lines={[{
          line_id: 'line-1',
          name: 'Cà phê đen',
          quantity: 1,
          unit_price: 35000,
          line_total: 35000,
        }]}
        total={35000}
      />,
    );

    expect(markup).toContain('INVOICE');
    expect(markup).toContain('order-1');
    expect(markup).toContain('PENDING');
    expect(markup).toContain('Trend Coffee Thủ Đức');
    expect(markup).toContain('TOTAL AMOUNT DUE');
    expect(markup).not.toContain('INV-000245');
    expect(markup).not.toContain('9999.8888.68');
    expect(markup).not.toContain('30-71234567-8');
  });
});

describe('PaymentQrView', () => {
  it('renders only a verified safe QR image and never fabricates a fallback', () => {
    const imageMarkup = renderToStaticMarkup(
      <PaymentQrView
        qr_code="data:image/png;base64,abc"
        total={35000}
        order_id="order-1"
      />,
    );
    const svgMarkup = renderToStaticMarkup(
      <PaymentQrView
        qr_code="merchant-opaque-qr"
        total={35000}
        order_id="order-1"
      />,
    );

    expect(imageMarkup).toContain('src="data:image/png;base64,abc"');
    expect(svgMarkup).not.toContain('<svg');
    expect(svgMarkup).toContain('Không thể hiển thị mã QR an toàn.');
    expect(imageMarkup).toContain('Scan Now');
    expect(imageMarkup).not.toContain('9999.8888.68');
  });
});
