// 29-ecommerce.js — WooCommerce Orders & Products
// Uses WooCommerce REST API v3 directly via native fetch.
// Requires: WORDPRESS_URL, WOOCOMMERCE_KEY, WOOCOMMERCE_SECRET in .env

const logger = require('../helpers/logger');

function wcUrl(endpoint) {
  const base = (process.env.WORDPRESS_URL || '').replace(/\/$/, '');
  return `${base}/wp-json/wc/v3/${endpoint}`;
}

async function wcGet(endpoint) {
  const key    = process.env.WOOCOMMERCE_KEY;
  const secret = process.env.WOOCOMMERCE_SECRET;

  if (!key || !secret) throw new Error('WOOCOMMERCE_KEY or WOOCOMMERCE_SECRET not set in .env');

  const creds = Buffer.from(`${key}:${secret}`).toString('base64');
  const res   = await fetch(wcUrl(endpoint), {
    headers: { 'Authorization': `Basic ${creds}` }
  });

  if (!res.ok) throw new Error(`WooCommerce error ${res.status}: ${res.statusText}`);
  return res.json();
}

async function wcPost(endpoint, body) {
  const key    = process.env.WOOCOMMERCE_KEY;
  const secret = process.env.WOOCOMMERCE_SECRET;
  const creds  = Buffer.from(`${key}:${secret}`).toString('base64');

  const res = await fetch(wcUrl(endpoint), {
    method:  'POST',
    headers: { 'Authorization': `Basic ${creds}`, 'Content-Type': 'application/json' },
    body:    JSON.stringify(body)
  });

  if (!res.ok) throw new Error(`WooCommerce error ${res.status}`);
  return res.json();
}

module.exports = {
  id: '29-ecommerce',
  name: 'WooCommerce Store Manager',
  description: 'View orders, manage products, and check revenue from drpiet.co.za WooCommerce store.',
  triggers: ['WC ORDERS', 'WC ORDER:', 'WC PRODUCTS', 'WC REVENUE', 'WC PRODUCT:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[ECOMMERCE] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      const configured = !!(process.env.WOOCOMMERCE_KEY && process.env.WOOCOMMERCE_SECRET && process.env.WORDPRESS_URL);

      if (!configured) {
        return {
          response:
            '🛒 *WooCommerce Store Manager*\n\n' +
            '⚠️ Not configured. Add to .env:\n' +
            '• `WORDPRESS_URL=https://drpiet.co.za`\n' +
            '• `WOOCOMMERCE_KEY=ck_...`\n' +
            '• `WOOCOMMERCE_SECRET=cs_...`\n\n' +
            'Get API keys: WooCommerce → Settings → Advanced → REST API → Add Key\n\n' +
            '**Available commands once configured:**\n' +
            '• `WC ORDERS` — recent orders\n' +
            '• `WC REVENUE` — revenue summary\n' +
            '• `WC PRODUCTS` — product list\n' +
            '• `WC ORDER: 123` — single order details'
        };
      }

      // ── RECENT ORDERS ────────────────────────────────────────────
      if (context.triggerUsed === 'WC ORDERS') {
        const orders = await wcGet('orders?per_page=10&orderby=date&order=desc');

        if (!orders.length) return { response: '🛒 No orders found.' };

        const statusEmoji = { processing: '🔄', completed: '✅', pending: '⏳', cancelled: '❌', refunded: '↩️' };
        const list = orders.map(o => {
          const icon = statusEmoji[o.status] || '📦';
          return `${icon} #${o.id} — R${parseFloat(o.total).toFixed(2)} — ${o.billing.first_name} ${o.billing.last_name} (${o.status})`;
        }).join('\n');

        return {
          response:
            `🛒 *Recent Orders (${orders.length})*\n\n${list}\n\n` +
            `For details: \`WC ORDER: [order number]\``
        };
      }

      // ── SINGLE ORDER ─────────────────────────────────────────────
      if (context.triggerUsed === 'WC ORDER:') {
        const orderId = payload.trim();
        if (!orderId) return { response: '⚠️ Usage: `WC ORDER: 123`' };

        const order = await wcGet(`orders/${orderId}`);
        const items = (order.line_items || []).map(i => `  • ${i.name} × ${i.quantity} = R${parseFloat(i.total).toFixed(2)}`).join('\n');

        return {
          response:
            `🛒 *Order #${order.id}*\n\n` +
            `👤 *Customer:* ${order.billing.first_name} ${order.billing.last_name}\n` +
            `📧 *Email:* ${order.billing.email}\n` +
            `📌 *Status:* ${order.status}\n` +
            `📅 *Date:* ${new Date(order.date_created).toLocaleDateString('en-ZA')}\n\n` +
            `*Items:*\n${items}\n\n` +
            `💰 *Total: R${parseFloat(order.total).toFixed(2)}*`
        };
      }

      // ── REVENUE SUMMARY ──────────────────────────────────────────
      if (context.triggerUsed === 'WC REVENUE') {
        const now        = new Date();
        const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString();
        const orders     = await wcGet(`orders?status=completed&after=${monthStart}&per_page=100`);

        const total    = orders.reduce((sum, o) => sum + parseFloat(o.total || 0), 0);
        const count    = orders.length;
        const avgOrder = count > 0 ? total / count : 0;

        return {
          response:
            `💰 *Revenue Summary — This Month*\n\n` +
            `📦 *Orders:* ${count}\n` +
            `💵 *Revenue:* R${total.toFixed(2)}\n` +
            `📊 *Average order:* R${avgOrder.toFixed(2)}\n\n` +
            `_Data from WooCommerce completed orders_`
        };
      }

      // ── PRODUCTS ─────────────────────────────────────────────────
      if (context.triggerUsed === 'WC PRODUCTS') {
        const products = await wcGet('products?per_page=15&status=publish');

        if (!products.length) return { response: '🛒 No products found in your WooCommerce store.' };

        const list = products.map(p => {
          const price = p.price ? `R${parseFloat(p.price).toFixed(2)}` : 'Variable';
          const stock = p.stock_status === 'instock' ? '✅' : '❌';
          return `${stock} ${p.name} — ${price}`;
        }).join('\n');

        return { response: `🛒 *WooCommerce Products (${products.length})*\n\n${list}` };
      }

      return { response: '⚠️ Usage: `WC ORDERS`, `WC REVENUE`, `WC PRODUCTS`, `WC ORDER: id`' };

    } catch (err) {
      logger.error('[ECOMMERCE] Error:', err.message);
      return { response: `❌ WooCommerce error: ${err.message}` };
    }
  }
};
