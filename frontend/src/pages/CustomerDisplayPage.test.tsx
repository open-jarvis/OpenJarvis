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
    expect(markup).toContain('ORDER NOT CREATED');
    expect(markup).toContain('Cà phê sữa');
    expect(markup).toContain('ít đá');
    expect(markup).toContain('Làm nhanh giúp mình');
    expect(markup).toContain('ORDER TYPE: AT TABLE');
    expect(markup).toContain('73');
    expect(markup).not.toContain('ORDER SLIP');
    expect(markup).not.toContain('TC-000245');
    expect(markup).not.toContain('AUGUST 28, 2026');
    expect(markup).toContain('CREDIT &amp; DEBIT CARDS: VISA, MASTERCARD, NAPAS');
    expect(markup).toContain('ACCOUNT NAME: CONG TY CO PHAN TREND COFFEE');
    expect(markup).toContain('MB BANK: 9999.8888.68');
    expect(markup).toContain('SERVICE CHARGE (10%)');
    expect(markup).toContain('TOTAL ESTIMATED');
    expect(markup).toContain('STATUS: ORDER IN PROGRESS (PLEASE CHECK YOUR ITEMS).');
    expect(markup).toContain('TREND COFFEE &amp; RESTAURANT');
    expect(markup).toContain('THANK YOU FOR DINING WITH US.');
    expect(markup).not.toContain('HÌNH THỨC:');
    expect(markup).not.toContain('TỔNG TẠM TÍNH');
    expect(markup.indexOf('SUBTOTAL')).toBeLessThan(
      markup.indexOf('CREDIT &amp; DEBIT CARDS'),
    );
    expect(markup).toContain('mt-8 max-w-[440px]');
    expect(markup).toContain('mt-6 flex flex-wrap');
    expect(markup).not.toContain('mt-auto flex flex-wrap');
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
    expect(markup).toContain('ORDER TYPE: TAKE OUT');
    expect(markup).toContain('RESERVATIONS@TRENDCOFFEE.VN | +84 90 123 4567');
    expect(markup).toContain('WWW.TRENDCOFFEE.NET');
    expect(markup).toContain('SUBTOTAL');
    expect(markup).toContain('SERVICE CHARGE (10%)');
    expect(markup).toContain('TOTAL AMOUNT DUE');
    expect(markup).toContain('CREDIT &amp; DEBIT CARDS: VISA, MASTERCARD, AMERICAN EXPRESS, NAPAS');
    expect(markup).toContain('ACCOUNT NAME: CONG TY CO PHAN TREND COFFEE');
    expect(markup).toContain('MB BANK: 9999.8888.68');
    expect(markup).toContain('THANK YOU FOR DINING WITH US.');
    expect(markup).not.toContain('HÌNH THỨC:');
    expect(markup).not.toContain('INV-000245');
    expect(markup).not.toContain('30-71234567-8');
  });
});

describe('PaymentQrView', () => {
  it('renders a complete receipt with a compact safe QR image', () => {
    const imageMarkup = renderToStaticMarkup(
      <PaymentQrView
        qr_code="data:image/png;base64,abc"
        total={70000}
        order_id="order-1"
        status="pending"
        order_type="at-table"
        branch="ba9355f797"
        table_name="73"
        lines={[{
          name: 'Cà phê đen',
          size: 'tiêu chuẩn',
          quantity: 2,
          unit_price: 35000,
          line_total: 70000,
        }]}
      />,
    );
    const unsafeMarkup = renderToStaticMarkup(
      <PaymentQrView
        qr_code="merchant-opaque-qr"
        total={35000}
        order_id="order-1"
      />,
    );

    expect(imageMarkup).toContain('src="data:image/png;base64,abc"');
    expect(unsafeMarkup).not.toContain('<img');
    expect(unsafeMarkup).toContain('UNABLE TO DISPLAY A VERIFIED QR CODE.');
    expect(imageMarkup).toContain('INVOICE');
    expect(imageMarkup).toContain('INVOICE NO.: order-1');
    expect(imageMarkup).toContain('STATUS: PENDING PAYMENT');
    expect(imageMarkup).toContain('ORDER TYPE: AT TABLE');
    expect(imageMarkup).toContain('TABLE: 73');
    expect(imageMarkup).toContain('Cà phê đen');
    expect(imageMarkup).toContain('SERVICE CHARGE (10%)');
    expect(imageMarkup).toContain('TOTAL AMOUNT DUE');
    expect(imageMarkup).toContain('MB BANK: 9999.8888.68');
    expect(imageMarkup).toContain('THANK YOU FOR DINING WITH US.');
    expect(imageMarkup).toContain('h-36 w-36');
    expect(imageMarkup).toContain('mix-blend-multiply');
    expect(imageMarkup).not.toContain('bg-white');
    expect(imageMarkup).not.toContain('border border-[#c4ab91]');
    expect(imageMarkup).not.toContain('h-32 w-32');
    expect(imageMarkup).not.toContain('h-64 w-64');
  });
});
