const logger = require('../helpers/logger');
const { fetchSiteRevenueSnapshot } = require('../helpers/revenue-engine');

async function fetchWooMetrics() {
  if (!process.env.WOOCOMMERCE_KEY || !process.env.WOOCOMMERCE_SECRET || !process.env.WORDPRESS_URL) {
    return null;
  }

  const base = process.env.WORDPRESS_URL.replace(/\/$/, '');
  const creds = Buffer.from(`${process.env.WOOCOMMERCE_KEY}:${process.env.WOOCOMMERCE_SECRET}`).toString('base64');
  const monthStart = new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString();
  const response = await fetch(`${base}/wp-json/wc/v3/orders?status=completed&after=${monthStart}&per_page=100`, {
    headers: { Authorization: `Basic ${creds}` }
  });

  if (!response.ok) return null;
  const orders = await response.json();
  const totalRevenue = orders.reduce((sum, order) => sum + parseFloat(order.total || 0), 0);

  return {
    orderCount: orders.length,
    totalRevenue: totalRevenue.toFixed(2)
  };
}

async function fetchTelemetrySummary(db) {
  if (!db) return null;

  const latestRows = await db.all(
    'SELECT payload, created_at FROM telemetry_events ORDER BY created_at DESC LIMIT 12'
  ).catch(() => []);
  const pendingApprovals = await db.get(
    'SELECT COUNT(*) AS count FROM approval_queue WHERE status = ?',
    ['pending']
  ).catch(() => ({ count: 0 }));

  if (!latestRows.length) {
    return {
      snapshots: 0,
      avgDispatches: 0,
      avgAiTokens: 0,
      pendingApprovals: pendingApprovals?.count || 0
    };
  }

  const parsed = latestRows
    .map((row) => {
      try {
        return JSON.parse(row.payload);
      } catch (_) {
        return null;
      }
    })
    .filter(Boolean);

  const avgDispatches = parsed.reduce((sum, item) => sum + (item.dispatches?.recent || 0), 0) / parsed.length;
  const avgAiTokens = parsed.reduce((sum, item) => sum + (item.ai?.totalTokens || 0), 0) / parsed.length;
  const avgSkillFailures = parsed.reduce((sum, item) => sum + (item.skills?.failures || 0), 0) / parsed.length;

  return {
    snapshots: parsed.length,
    avgDispatches: Math.round(avgDispatches),
    avgAiTokens: Math.round(avgAiTokens),
    avgSkillFailures: Number(avgSkillFailures.toFixed(2)),
    pendingApprovals: pendingApprovals?.count || 0
  };
}

module.exports = {
  id: '12-analytics',
  name: 'Analytics & Business Intelligence',
  description: 'Pull website, business, and Serena runtime analytics into one operational report.',
  triggers: ['ANALYTICS REPORT', 'SITE ANALYTICS'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_12_analytics',
      description: 'Generate an analytics report for the website, business runtime, and Serena operational health.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['ANALYTICS REPORT', 'SITE ANALYTICS']
          },
          payload: { type: 'string' }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const targetUrl = String(payload || '').trim() || process.env.WORDPRESS_URL || 'https://drpiet.co.za';
      const snapshot = await fetchSiteRevenueSnapshot(targetUrl);
      const wooMetrics = await fetchWooMetrics();

      const patientCount = context.db ? await context.db.get('SELECT COUNT(*) AS total FROM patients') : null;
      const invoiceStats = context.db ? await context.db.get('SELECT COUNT(*) AS total, COALESCE(SUM(total), 0) AS revenue FROM invoices') : null;
      const taskStats = context.db ? await context.db.get('SELECT COUNT(*) AS total FROM tasks WHERE status = ?', ['pending']) : null;
      const telemetrySummary = await fetchTelemetrySummary(context.db);

      return {
        response:
          `Analytics Report\n\n` +
          `URL: ${targetUrl}\n` +
          `Title: ${snapshot.title || 'Not detected'}\n` +
          `Primary H1: ${snapshot.h1 || 'Not detected'}\n` +
          `Forms found: ${snapshot.formCount}\n` +
          `Booking mentions: ${snapshot.bookingMentions}\n` +
          `Membership mentions: ${snapshot.membershipMentions}\n` +
          `Product mentions: ${snapshot.productMentions}\n` +
          `Trust signals: ${snapshot.trustSignals.join(', ') || 'None found'}\n\n` +
          `Business Data\n` +
          `• Patients in DB: ${patientCount?.total ?? 'N/A'}\n` +
          `• Invoices in DB: ${invoiceStats?.total ?? 'N/A'}\n` +
          `• Invoice revenue tracked: R${invoiceStats?.revenue ?? '0.00'}\n` +
          `• Pending internal tasks: ${taskStats?.total ?? 'N/A'}\n` +
          `• Woo orders this month: ${wooMetrics?.orderCount ?? 'N/A'}\n` +
          `• Woo revenue this month: R${wooMetrics?.totalRevenue ?? 'N/A'}\n\n` +
          `Serena Runtime\n` +
          `• Telemetry snapshots stored: ${telemetrySummary?.snapshots ?? 0}\n` +
          `• Avg recent dispatch volume: ${telemetrySummary?.avgDispatches ?? 0}\n` +
          `• Avg recent AI tokens: ${telemetrySummary?.avgAiTokens ?? 0}\n` +
          `• Avg recent skill failures: ${telemetrySummary?.avgSkillFailures ?? 0}\n` +
          `• Pending approvals: ${telemetrySummary?.pendingApprovals ?? 0}`
      };
    } catch (error) {
      logger.error('[ANALYTICS] Error: ' + error.message);
      return { response: `Analytics error: ${error.message}` };
    }
  }
};
