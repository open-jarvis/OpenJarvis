import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router';

import { useAgentEvents, type AgentEvent } from '@/lib/useAgentEvents';
import {
  isSafeQrImageSource,
  reduceCustomerDisplay,
  waitingState,
  type CustomerDisplayLine,
  type CustomerDisplayState,
  type CustomerMenuItem,
} from './customerDisplayState';

const vnd = new Intl.NumberFormat('vi-VN');

function money(value: number | undefined): string {
  return `${vnd.format(value ?? 0)}đ`;
}

// Striped Band Components
function StripedBand() {
  return (
    <div
      className="h-6 w-full shrink-0"
      style={{
        background: 'repeating-linear-gradient(90deg, #fae7cd, #fae7cd 14px, #cbb196 14px, #cbb196 28px)',
      }}
    />
  );
}

// Swallowtail Ribbon Header
function ColumnRibbon({
  title,
  dotsLeft = true,
  dotsRight = true,
}: {
  title: string;
  dotsLeft?: boolean;
  dotsRight?: boolean;
}) {
  return (
    <div className="relative mb-5 flex w-full min-w-0 items-center">
      {dotsLeft && (
        <div
          className="h-1.5 min-w-[12px] flex-1"
          style={{
            backgroundImage: 'radial-gradient(circle, #8c6239 1.6px, transparent 1.6px)',
            backgroundSize: '10px 6px',
            backgroundRepeat: 'repeat-x',
            backgroundPosition: 'center',
          }}
        />
      )}
      <div
        className="relative z-10 flex h-8 min-w-0 max-w-full items-center justify-center bg-[#8c6239] px-4 sm:px-7 text-xs font-semibold tracking-[0.22em] sm:tracking-[0.32em] text-white uppercase shadow-sm shrink-0 truncate"
        style={{
          clipPath: 'polygon(0% 0%, 100% 0%, calc(100% - 14px) 50%, 100% 100%, 0% 100%, 14px 50%)',
        }}
      >
        {title}
      </div>
      {dotsRight && (
        <div
          className="h-1.5 min-w-[12px] flex-1"
          style={{
            backgroundImage: 'radial-gradient(circle, #8c6239 1.6px, transparent 1.6px)',
            backgroundSize: '10px 6px',
            backgroundRepeat: 'repeat-x',
            backgroundPosition: 'center',
          }}
        />
      )}
    </div>
  );
}

// Restaurant Editorial Header (Only on Menu View)
function RestaurantHeader() {
  return (
    <header className="grid grid-cols-1 items-center gap-4 px-8 pt-5 pb-3 md:grid-cols-3 text-[#8c6239]">
      <div className="text-left text-[12px] leading-[1.42] tracking-[0.12em]">
        <div className="font-semibold uppercase">OPEN AT 10AM-10PM</div>
        <div>Club Ministère, 4TH Avenue</div>
        <div className="mt-0.5 font-semibold">FOR RESERVATION, CALL :</div>
        <div className="tracking-[0.14em]">(+1)989-466-3731</div>
      </div>

      <div className="flex flex-col items-center justify-center text-center">
        <div className="mb-0.5 text-[9px] font-semibold tracking-[0.28em]">EST. 1996</div>
        <div className="relative my-0.5 flex w-full items-center justify-center">
          <svg className="h-8 w-16 text-[#8c6239]" viewBox="0 0 80 40" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <path d="M75,35 C50,35 25,28 10,12 C20,10 28,15 32,22 C18,16 12,6 18,2 C22,10 30,16 42,24 C30,10 32,2 40,2 C44,12 50,20 58,30"/>
          </svg>
          <div className="mx-1 font-['Alex_Brush',cursive] text-4xl leading-none sm:text-5xl text-[#8c6239]">Restaurant</div>
          <svg className="h-8 w-16 text-[#8c6239]" viewBox="0 0 80 40" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <path d="M5,35 C30,35 55,28 70,12 C60,10 52,15 48,22 C62,16 68,6 62,2 C58,10 50,16 38,24 C50,10 48,2 40,2 C36,12 30,20 22,30"/>
          </svg>
        </div>
        <div className="mt-0.5 text-2xl font-bold tracking-[0.35em] uppercase leading-none sm:text-3xl text-[#8c6239]">MENU</div>
        <div className="mt-1 text-[10.5px] font-semibold tracking-[0.26em] uppercase text-[#8c6239]">BEST FOOD IN TOWN</div>
      </div>

      <div className="flex flex-col items-end justify-center text-right font-['Alex_Brush',cursive] text-3xl leading-none sm:text-4xl text-[#8c6239]">
        <div>Special</div>
        <div className="-mt-1">Dishes</div>
      </div>
    </header>
  );
}

// Editorial Footer Bar
function EditorialFooter() {
  return (
    <footer className="mt-auto shrink-0 font-['Josefin_Sans',sans-serif]">
      <div className="flex flex-wrap items-center justify-center gap-6 bg-[#c0a386] px-8 py-2 text-[11px] font-medium tracking-wider text-white">
        <div>@trendcoffee.vn</div>
        <div>Trend Coffee Vietnam</div>
        <div>trendcoffee.net</div>
        <div>Số 03 Nguyễn Công Trứ, TP. Thủ Đức</div>
      </div>
      <StripedBand />
    </footer>
  );
}

interface MenuCategorySection {
  title: string;
  items: {
    name: string;
    price: string | number;
  }[];
}

const vintageMenuSections: MenuCategorySection[] = [
  {
    title: 'CÀ PHÊ',
    items: [
      { name: 'Espresso', price: 45 },
      { name: 'Bạc xỉu', price: 55 },
      { name: 'Cold Brew', price: 60 },
      { name: 'Cappuccino', price: 65 },
    ],
  },
  {
    title: 'MÓN TRÀ',
    items: [
      { name: 'Trà đen', price: 40 },
      { name: 'Trà nhài', price: 45 },
      { name: 'Trà sữa', price: 55 },
      { name: 'Trà ô long', price: 50 },
    ],
  },
  {
    title: 'SINH TỐ',
    items: [
      { name: 'Sinh tố bơ', price: 55 },
      { name: 'Sinh tố dâu', price: 55 },
      { name: 'Sinh tố xoài', price: 55 },
      { name: 'Nước dừa tươi', price: 45 },
    ],
  },
  {
    title: 'NƯỚC GIẢI KHÁT',
    items: [
      { name: 'Coca Cola', price: 25 },
      { name: 'Soda chanh', price: 35 },
      { name: 'Nước cam', price: 40 },
      { name: 'Nước ép dứa', price: 45 },
    ],
  },
  {
    title: 'MÓN BÁNH',
    items: [
      { name: 'Croissant', price: 35 },
      { name: 'Cheesecake', price: 55 },
      { name: 'Tiramisu', price: 60 },
      { name: 'Panna Cotta', price: 50 },
    ],
  },
  {
    title: 'MÓN ĂN',
    items: [
      { name: 'Súp', price: 45 },
      { name: 'Khoai tây chiên', price: 50 },
      { name: 'Burger', price: 85 },
      { name: 'Pasta', price: 95 },
    ],
  },
  {
    title: 'BIA/ RƯỢU VANG',
    items: [
      { name: 'Corona Extra', price: 55 },
      { name: 'Bia Hà', price: 35 },
      { name: 'Vang đỏ ly', price: 90 },
      { name: 'Vang trắng ly', price: 90 },
    ],
  },
  {
    title: 'GIÁ TÙY CHỈNH',
    items: [
      { name: 'Combo nhỏ', price: 79 },
      { name: 'Combo vừa', price: 99 },
      { name: 'Combo lớn', price: 129 },
      { name: 'Theo yêu cầu', price: '-' },
    ],
  },
];

// VIEW 1: APPROVED MENU
export function MenuView({
  items,
  resultComplete,
  projectedCount,
  publishedCount,
  preview,
}: {
  items: CustomerMenuItem[];
  resultComplete: boolean;
  projectedCount: number;
  publishedCount: number;
  preview: boolean;
}) {
  const demoMenuItems: CustomerMenuItem[] = [
    {
      name: 'MÌ Ý BÒ BẰM',
      price: 107000,
      note: 'Special gourmet recipe prepared fresh daily with premium ingredients.',
    },
    {
      name: 'MÌ Ý CARBONARA',
      price: 150000,
      note: 'Special gourmet recipe prepared fresh daily with premium ingredients.',
    },
    {
      name: 'MÌ Ý TÔM',
      price: 172000,
      note: 'Special gourmet recipe prepared fresh daily with premium ingredients.',
    },
  ];
  const mainDishes = preview ? demoMenuItems : items;

  if (resultComplete && !preview && items.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center px-8 py-16 text-center text-[#8c6239]">
        <p className="font-['Cormorant_Garamond',serif] text-2xl">
          Không có kết quả phù hợp.
        </p>
      </div>
    );
  }

  return (
    <div
      className="flex flex-1 flex-col w-full min-w-0 px-3 sm:px-6 md:px-8 pb-6 text-[#8c6239]"
      data-projected-count={projectedCount}
      data-published-count={publishedCount}
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 lg:gap-x-12 gap-y-8 w-full min-w-0">
        {/* LEFT COLUMN: MENU */}
        <div className="flex flex-col min-w-0 w-full">
          <ColumnRibbon title="MENU" dotsLeft={true} dotsRight={true} />
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-1 lg:grid-cols-2 gap-x-4 sm:gap-x-6 lg:gap-x-8 gap-y-6 sm:gap-y-8 w-full min-w-0">
            {vintageMenuSections.map((section) => (
              <div key={section.title} className="flex flex-col min-w-0">
                <h3 className="mb-2 text-center font-bold text-[14.5px] sm:text-[15.5px] tracking-[0.1em] uppercase text-[#8c6239]">
                  {section.title}
                </h3>
                <div className="flex flex-col space-y-2 min-w-0">
                  {section.items.map((it) => (
                    <div
                      key={it.name}
                      className="flex items-baseline justify-between text-[15px] sm:text-[16px] font-semibold tracking-[0.03em] text-[#8c6239] min-w-0"
                    >
                      <span className="truncate pr-1">{it.name}</span>
                      <span className="tabular-nums font-bold shrink-0">{it.price}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* RIGHT COLUMN: RECOMMENDATIONS */}
        <div className="flex flex-col min-w-0 w-full">
          <ColumnRibbon title="RECOMMENDATIONS" dotsLeft={true} dotsRight={true} />
          <div className="flex flex-col space-y-4 w-full min-w-0">
            {mainDishes.map((item, index) => {
              const displayPrice =
                item.price !== undefined
                  ? item.price >= 1000
                    ? Math.round(item.price / 1000)
                    : item.price
                  : '10';
              return (
                <div
                  key={item.id ?? `${item.name}-${index}`}
                  className="flex flex-col min-w-0"
                  data-menu-item
                >
                  <div className="flex items-center justify-between font-bold text-[15px] sm:text-[16px] tracking-[0.12em] uppercase text-[#8c6239] min-w-0">
                    <span className="truncate pr-2">{item.name}</span>
                    <span className="tabular-nums font-bold shrink-0 ml-4">{displayPrice}</span>
                  </div>
                  <p className="mt-0.5 font-['Cormorant_Garamond',serif] text-[14px] sm:text-[14.5px] italic leading-tight text-[#9b7352]">
                    {item.note || 'Special gourmet recipe prepared fresh daily with premium ingredients.'}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function orderTypeLabel(orderType: string): string {
  if (orderType === 'at-table') return 'TẠI BÀN';
  if (orderType === 'take-out') return 'MANG ĐI';
  return 'CHƯA CHỌN';
}

// VIEW 2: LOCAL CART DRAFT
export function CartView({
  lines,
  total,
  order_note,
  order_type,
  table_name,
}: {
  lines: CustomerDisplayLine[];
  total: number;
  order_note: string;
  order_type: string;
  table_name: string;
}) {
  return (
    <div className="mx-auto w-full max-w-[680px] flex-1 px-10 py-8 text-left font-['Josefin_Sans',sans-serif] text-[#783820]">
      <div className="flex items-baseline justify-between border-b-[1.5px] border-[#783820] pb-2">
        <h1 className="font-['Playfair_Display',serif] text-4xl font-normal tracking-wide uppercase sm:text-5xl">
          CART
        </h1>
        <div className="text-right text-[11px] font-semibold tracking-wider uppercase leading-tight">
          CHƯA TẠO ĐƠN HÀNG
        </div>
      </div>

      <div className="flex flex-wrap gap-x-8 gap-y-1 pt-3 pb-6 text-[11px] font-semibold tracking-wider uppercase leading-relaxed">
        <div>HÌNH THỨC: {orderTypeLabel(order_type)}</div>
        {order_type === 'at-table' && table_name && <div>BÀN: {table_name}</div>}
      </div>

      <div className="grid grid-cols-12 border-b-[1.5px] border-[#783820] pb-1.5 text-[12px] font-bold tracking-widest uppercase">
        <div className="col-span-6">ITEM</div>
        <div className="col-span-2 text-center">QTY</div>
        <div className="col-span-2 text-right">UNIT PRICE</div>
        <div className="col-span-2 text-right">SUBTOTAL</div>
      </div>

      <div className="space-y-2.5 py-3 text-[12.5px] font-medium tracking-wide">
        {lines.length > 0 ? (
          lines.map((line, index) => {
            const qty = line.quantity ?? 1;
            const lineTotal = line.line_total ?? ((line.unit_price ?? 0) * qty);
            const unitPrice = line.unit_price ?? (qty > 0 ? Math.round(lineTotal / qty) : 0);
            return (
              <div
                key={line.line_id ?? `${line.name}-${index}`}
                className="grid grid-cols-12 items-start"
                data-cart-line={line.line_id ?? ''}
              >
                <div className="col-span-6 font-semibold uppercase">
                  <div>{line.name}{line.size ? ` (${line.size})` : ''}</div>
                  {line.note && (
                    <div className="mt-1 text-[10px] font-normal normal-case tracking-normal text-[#9b7352]">
                      Ghi chú: {line.note}
                    </div>
                  )}
                </div>
                <div className="col-span-2 text-center font-normal">{qty}</div>
                <div className="col-span-2 text-right tabular-nums">{money(unitPrice)}</div>
                <div className="col-span-2 text-right font-semibold tabular-nums">{money(lineTotal)}</div>
              </div>
            );
          })
        ) : (
          <div className="py-4 text-center text-sm normal-case tracking-normal text-[#9b7352]">
            Giỏ hàng trống.
          </div>
        )}
      </div>

      <div className="flex justify-end border-t-[1.5px] border-[#783820] pt-3 pb-6">
        <div className="w-64 space-y-1.5 text-[12px] font-semibold tracking-wider uppercase">
          <div className="flex justify-between pt-1 text-[14px] font-bold">
            <span>TỔNG TẠM TÍNH</span>
            <span className="text-[15px] font-extrabold tabular-nums">{money(total)}</span>
          </div>
        </div>
      </div>

      {order_note && (
        <div className="border-t-[1.5px] border-[#783820] pt-4 text-[11px] leading-relaxed">
          <span className="font-bold tracking-wider uppercase">GHI CHÚ ĐƠN: </span>
          <span>{order_note}</span>
        </div>
      )}
    </div>
  );
}

// VIEW 3: BILL (INVOICE LUXURY INVOICE)
export function BillView({
  order_id,
  branch,
  order_type,
  status,
  lines,
  total,
}: {
  order_id: string;
  branch: string;
  order_type?: string;
  status: string;
  lines: CustomerDisplayLine[];
  total: number;
}) {
  return (
    <div className="mx-auto w-full max-w-[680px] flex-1 px-10 py-8 text-left font-['Josefin_Sans',sans-serif] text-[#783820]">
      <div className="flex items-baseline justify-between border-b-[1.5px] border-[#783820] pb-2">
        <h1 className="font-['Playfair_Display',serif] text-4xl font-normal tracking-wide uppercase sm:text-5xl">
          INVOICE
        </h1>
        <div className="text-right text-[11px] font-semibold tracking-wider uppercase leading-tight">
          <div>INVOICE NO.: {order_id}</div>
          <div>STATUS: {status.toUpperCase()}</div>
        </div>
      </div>

      <div className="flex flex-wrap gap-x-8 gap-y-1 pt-3 pb-6 text-[11px] font-semibold tracking-wider uppercase leading-relaxed">
        <div>BRANCH: {branch}</div>
        <div>HÌNH THỨC: {orderTypeLabel(order_type ?? '')}</div>
      </div>

      <div className="grid grid-cols-12 border-b-[1.5px] border-[#783820] pb-1.5 text-[12px] font-bold tracking-widest uppercase">
        <div className="col-span-6">ITEM</div>
        <div className="col-span-2 text-center">QTY</div>
        <div className="col-span-2 text-right">UNIT PRICE</div>
        <div className="col-span-2 text-right">SUBTOTAL</div>
      </div>

      <div className="space-y-2.5 py-3 text-[12.5px] font-medium tracking-wide">
        {lines.length > 0 ? (
          lines.map((line, index) => {
            const qty = line.quantity ?? 1;
            const lineTotal = line.line_total ?? ((line.unit_price ?? 0) * qty);
            const unitPrice = line.unit_price ?? (qty > 0 ? Math.round(lineTotal / qty) : 0);
            return (
              <div key={line.line_id ?? `${line.name}-${index}`} className="grid grid-cols-12 items-start">
                <div className="col-span-6 font-semibold uppercase">
                  <div>{line.name}{line.size ? ` (${line.size})` : ''}</div>
                  {line.note && (
                    <div className="mt-1 text-[10px] font-normal normal-case tracking-normal text-[#9b7352]">
                      Ghi chú: {line.note}
                    </div>
                  )}
                </div>
                <div className="col-span-2 text-center font-normal">{qty}</div>
                <div className="col-span-2 text-right tabular-nums">{money(unitPrice)}</div>
                <div className="col-span-2 text-right font-semibold tabular-nums">{money(lineTotal)}</div>
              </div>
            );
          })
        ) : (
          <div className="py-4 text-center text-sm normal-case tracking-normal text-[#9b7352]">
            Provider không trả về dòng món nào.
          </div>
        )}
      </div>

      <div className="flex justify-end border-t-[1.5px] border-[#783820] pt-3 pb-6">
        <div className="w-64 space-y-1.5 text-[12px] font-semibold tracking-wider uppercase">
          <div className="flex justify-between pt-1 text-[14px] font-bold">
            <span>TOTAL AMOUNT DUE</span>
            <span className="text-[15px] font-extrabold tabular-nums">{money(total)}</span>
          </div>
        </div>
      </div>

    </div>
  );
}

// VIEW 4: PAYMENT QR (MINIMALIST SAMPLE)
export function PaymentQrView({
  qr_code,
  total,
  order_id,
}: {
  qr_code: string;
  total?: number;
  order_id: string;
}) {
  const isImage = isSafeQrImageSource(qr_code);

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-8 py-10 text-center font-['Josefin_Sans',sans-serif]">
      <div className="mb-4 -rotate-2 font-['Alex_Brush',cursive] text-6xl leading-none text-[#6e2b14] sm:text-7xl">
        Payment
      </div>

      {isImage ? (
        <div className="mb-4 inline-block overflow-hidden rounded-2xl border border-[#c4ab91] bg-white p-1 shadow-xl">
          <div className="overflow-hidden rounded-xl">
            <img
              src={qr_code}
              alt="Mã thanh toán QR"
              className="mx-auto h-64 w-64 scale-112 object-contain sm:h-72 sm:w-72"
            />
          </div>
        </div>
      ) : (
        <div className="mb-4 rounded-xl border border-[#c4ab91] px-6 py-8 text-sm font-semibold text-[#6e2b14]">
          Không thể hiển thị mã QR an toàn.
        </div>
      )}

      {isImage && (
        <div className="mb-1 text-base font-medium tracking-[0.2em] uppercase text-[#6e2b14] sm:text-lg">
          Scan Now
        </div>
      )}

      <div className="mt-2 space-y-0.5 text-xs text-[#8c6239]">
        {total !== undefined && total > 0 && (
          <div className="text-lg font-bold tabular-nums text-[#6e2b14]">
            {money(total)}
          </div>
        )}
        {order_id && (
          <div className="text-[10px] text-[#9b7352] opacity-75">
            Mã đơn hàng: {order_id}
          </div>
        )}
      </div>
    </div>
  );
}

// VIEW 5: WAITING (VINTAGE POSTER - NO CORNER BRACKETS - Trend COFFEE)
function WaitingView() {
  return (
    <div className="flex flex-1 items-center justify-center px-8 py-8">
      <div className="relative w-full max-w-[580px] p-6 sm:p-8">
        <div className="relative border-[2px] border-[#8c6239] bg-transparent p-6 sm:p-9">
          <div className="mb-2 flex items-center justify-center gap-3 px-10">
            <div className="h-[2px] flex-1 bg-[#8c6239]" />
            <div className="flex items-center gap-2 font-['Josefin_Sans',sans-serif]">
              <span className="text-2xl font-extrabold tracking-tight text-[#5c3717] sm:text-3xl">Trend</span>
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-[#5c3717]" />
              <span className="text-xs font-medium tracking-[0.24em] text-[#9b7352] uppercase sm:text-[13px]">COFFEE</span>
            </div>
            <div className="h-[2px] flex-1 bg-[#8c6239]" />
          </div>

          <div className="my-4 text-center font-['Josefin_Sans',sans-serif]">
            <div className="mb-1 text-sm font-semibold tracking-[0.28em] text-[#8c6239] uppercase sm:text-base">
              CLASSIC RESTAURANT
            </div>
            <div className="my-2 text-6xl font-extrabold tracking-[0.15em] uppercase leading-[0.88] text-[#8c6239] sm:text-7xl lg:text-[84px]">
              <div>BREAK</div>
              <div>FAST</div>
            </div>
          </div>

          <div className="relative mt-2 grid min-h-[160px] grid-cols-2 items-start gap-4 pt-4">
            <div className="space-y-3.5 pl-1 text-left font-['Josefin_Sans',sans-serif]">
              <div className="space-y-2.5 text-xs font-bold tracking-[0.16em] uppercase text-[#8c6239] sm:text-[13px]">
                <div className="flex items-center gap-2">
                  <span className="inline-block h-2.5 w-2.5 rounded-full bg-[#8c6239]" />
                  <span>ORANGE JUICE</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="inline-block h-2.5 w-2.5 rounded-full bg-[#8c6239]" />
                  <span>CROISSANT</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="inline-block h-2.5 w-2.5 rounded-full bg-[#8c6239]" />
                  <span>INFUSION</span>
                </div>
              </div>

              <div className="pt-1.5">
                <div className="text-4xl font-bold tracking-tight leading-none text-[#8c6239] sm:text-[44px]">
                  $12
                </div>
              </div>

              <div className="flex items-center gap-1.5 pt-2 text-[10.5px] font-semibold text-[#8c6239]">
                <div>
                  <span className="block text-[8.5px] tracking-wider uppercase opacity-75">Delivery</span>
                  <span className="tracking-wider">00 54 9 34154777</span>
                </div>
              </div>
            </div>

            <div className="absolute top-4 bottom-2 left-1/2 w-[1.5px] -translate-x-1/2 bg-[#8c6239]" />

            <div className="space-y-3 pl-3 text-left font-['Josefin_Sans',sans-serif]">
              <p className="text-[11.5px] font-medium leading-[1.4] text-[#9b7352]">
                Khởi đầu ngày mới tràn đầy năng lượng cùng hương vị cà phê phin mộc thơm nồng nàn và bánh sừng bò giòn tan chuẩn vị Pháp.
              </p>

              <div className="flex items-center gap-2 pt-1 text-[#8c6239]">
                <span className="flex h-6 w-6 items-center justify-center rounded-full border border-[#8c6239] text-[10px] font-bold">f</span>
                <span className="flex h-6 w-6 items-center justify-center rounded-full border border-[#8c6239] text-[10px] font-bold">ig</span>
                <span className="flex h-6 w-6 items-center justify-center rounded-full border border-[#8c6239] text-[10px] font-bold">tt</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function CustomerDisplayPage() {
  const [searchParams] = useSearchParams();
  const sessionId = searchParams.get('session')?.trim() || undefined;
  const preview = searchParams.get('preview')?.trim();
  const [state, setState] = useState<CustomerDisplayState>(() => {
    if (preview === 'menu') return {
      view: 'menu',
      items: [],
      resultComplete: false,
      projectedCount: 0,
      publishedCount: 0,
      preview: true,
    };
    if (preview === 'waiting') return { view: 'waiting' };
    return waitingState;
  });

  useEffect(() => {
    if (preview === 'menu') {
      setState({
        view: 'menu',
        items: [],
        resultComplete: false,
        projectedCount: 0,
        publishedCount: 0,
        preview: true,
      });
    } else {
      setState(waitingState);
    }
  }, [sessionId, preview]);

  const handleEvent = useCallback((event: AgentEvent) => {
    if (!sessionId) return;
    setState((current) => reduceCustomerDisplay(current, event, sessionId));
  }, [sessionId]);

  useAgentEvents(undefined, handleEvent, ['display_update'], sessionId);

  return (
    <div className="h-screen w-full bg-[#fae7cd] text-[#8c6239] font-['Josefin_Sans',sans-serif] flex flex-col justify-between overflow-x-hidden overflow-y-auto selection:bg-[#8c6239] selection:text-white">
      {/* Top Striped Band on Full Page */}
      <StripedBand />

      {/* Main Container */}
      <main className="w-full flex-1 flex flex-col justify-between max-w-[1440px] xl:max-w-[1600px] mx-auto py-2 px-2 sm:px-4 md:px-6">
        {!sessionId && !preview ? (
          <div className="my-auto flex flex-col items-center justify-center p-8 text-center">
            <h2 className="font-['Alex_Brush',cursive] text-5xl text-[#8c6239] mb-2">Trend Coffee</h2>
            <p className="text-sm font-semibold tracking-widest uppercase text-[#9b7352]">
              Sẵn sàng phục vụ &bull; Đang chờ kết nối phiên hiển thị
            </p>
          </div>
        ) : (
          <>
            {state.view === 'menu' && (
              <>
                <RestaurantHeader />
                <MenuView
                  items={state.items}
                  resultComplete={state.resultComplete}
                  projectedCount={state.projectedCount}
                  publishedCount={state.publishedCount}
                  preview={state.preview}
                />
              </>
            )}

            {state.view === 'cart' && (
              <CartView
                lines={state.lines}
                total={state.total}
                order_note={state.order_note}
                order_type={state.order_type}
                table_name={state.table_name}
              />
            )}

            {state.view === 'bill' && (
              <BillView
                order_id={state.order_id}
                branch={state.branch}
                order_type={state.order_type}
                status={state.status}
                lines={state.lines}
                total={state.total}
              />
            )}

            {state.view === 'payment_qr' && (
              <PaymentQrView
                qr_code={state.qr_code}
                total={state.total}
                order_id={state.order_id}
              />
            )}

            {state.view === 'waiting' && (
              <WaitingView />
            )}
          </>
        )}
      </main>

      {/* Bottom Editorial Footer */}
      <EditorialFooter />
    </div>
  );
}
