"""Dashboard route — serves the savings dashboard HTML page."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

dashboard_router = APIRouter()

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenJarvis — Savings Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0a0e17; --surface: #131926; --border: #1e2a3d;
    --text: #e2e8f0; --muted: #8892a4; --accent: #38bdf8;
    --green: #22c55e; --green-dim: #166534; --orange: #f59e0b;
    --red: #ef4444; --purple: #a78bfa;
  }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg); color: var(--text);
    min-height: 100vh; padding: 0;
  }
  .header {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    border-bottom: 1px solid var(--border);
    padding: 24px 32px; display: flex; align-items: center; gap: 16px;
  }
  .header h1 { font-size: 22px; font-weight: 600; }
  .header h1 span { color: var(--accent); }
  .header .status {
    margin-left: auto; display: flex; align-items: center; gap: 8px;
    font-size: 13px; color: var(--muted);
  }
  .header .dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--green); animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; } 50% { opacity: 0.4; }
  }
  .container { max-width: 1280px; margin: 0 auto; padding: 32px; }

  /* Top stats row */
  .stats-row {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px;
    margin-bottom: 32px;
  }
  .stat-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px 24px;
  }
  .stat-card .label {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--muted); margin-bottom: 8px;
  }
  .stat-card .value {
    font-size: 28px; font-weight: 700;
    font-variant-numeric: tabular-nums;
  }
  .stat-card .sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .green { color: var(--green); }
  .accent { color: var(--accent); }
  .orange { color: var(--orange); }
  .purple { color: var(--purple); }

  /* Provider cards */
  .providers-heading {
    font-size: 16px; font-weight: 600; margin-bottom: 16px;
    color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em;
  }
  .providers {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px;
    margin-bottom: 32px;
  }
  .provider-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 24px; position: relative; overflow: hidden;
  }
  .provider-card::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
  }
  .provider-card.openai::before { background: var(--green); }
  .provider-card.anthropic::before { background: var(--orange); }
  .provider-card.google::before { background: var(--accent); }

  .provider-card .pname {
    font-size: 14px; font-weight: 600; margin-bottom: 4px;
  }
  .provider-card .pmodel {
    font-size: 12px; color: var(--muted); margin-bottom: 16px;
  }
  .provider-card .savings-amount {
    font-size: 36px; font-weight: 700; color: var(--green);
    margin-bottom: 8px; font-variant-numeric: tabular-nums;
  }
  .provider-card .breakdown {
    display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
    margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border);
  }
  .breakdown .item .blabel {
    font-size: 11px; color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .breakdown .item .bvalue {
    font-size: 16px; font-weight: 600; margin-top: 2px;
    font-variant-numeric: tabular-nums;
  }

  /* Bottom: energy and flops */
  .metrics-row {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px;
  }
  .metric-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 24px;
  }
  .metric-card .mheading {
    font-size: 13px; color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.05em; margin-bottom: 12px;
  }
  .metric-card .mvalue {
    font-size: 28px; font-weight: 700; font-variant-numeric: tabular-nums;
  }
  .metric-card .munit { font-size: 14px; color: var(--muted); font-weight: 400; }
  .metric-card .msub { font-size: 12px; color: var(--muted); margin-top: 6px; }

  /* Responsive */
  @media (max-width: 900px) {
    .stats-row { grid-template-columns: repeat(2, 1fr); }
    .providers { grid-template-columns: 1fr; }
    .metrics-row { grid-template-columns: 1fr; }
  }
  @media (max-width: 500px) {
    .stats-row { grid-template-columns: 1fr; }
    .container { padding: 16px; }
  }
</style>
</head>
<body>

<div class="header">
  <h1><span>OpenJarvis</span> Savings Dashboard</h1>
  <div class="status">
    <div class="dot"></div>
    <span id="status-text">Live — refreshing every 5s</span>
  </div>
</div>

<div class="container">

  <!-- Top stats -->
  <div class="stats-row">
    <div class="stat-card">
      <div class="label">Total Requests</div>
      <div class="value accent" id="total-calls">0</div>
      <div class="sub">inference calls served locally</div>
    </div>
    <div class="stat-card">
      <div class="label">Prompt Tokens</div>
      <div class="value" id="prompt-tokens">0</div>
      <div class="sub">input tokens processed</div>
    </div>
    <div class="stat-card">
      <div class="label">Completion Tokens</div>
      <div class="value" id="completion-tokens">0</div>
      <div class="sub">output tokens generated</div>
    </div>
    <div class="stat-card">
      <div class="label">Total Tokens</div>
      <div class="value" id="total-tokens">0</div>
      <div class="sub">tokens kept on-device</div>
    </div>
  </div>

  <!-- Provider savings -->
  <div class="providers-heading">Dollars Saved vs Cloud Providers</div>
  <div class="providers">
    <div class="provider-card openai">
      <div class="pname">OpenAI</div>
      <div class="pmodel">GPT-5.3 &mdash; $2.00 / $10.00 per 1M tokens</div>
      <div class="savings-amount" id="save-openai">$0.00</div>
      <div class="breakdown">
        <div class="item">
          <div class="blabel">Input saved</div>
          <div class="bvalue" id="save-openai-in">$0.00</div>
        </div>
        <div class="item">
          <div class="blabel">Output saved</div>
          <div class="bvalue" id="save-openai-out">$0.00</div>
        </div>
      </div>
    </div>
    <div class="provider-card anthropic">
      <div class="pname">Anthropic</div>
      <div class="pmodel">Claude Opus 4.6 &mdash; $5.00 / $25.00 per 1M tokens</div>
      <div class="savings-amount" id="save-anthropic">$0.00</div>
      <div class="breakdown">
        <div class="item">
          <div class="blabel">Input saved</div>
          <div class="bvalue" id="save-anthropic-in">$0.00</div>
        </div>
        <div class="item">
          <div class="blabel">Output saved</div>
          <div class="bvalue" id="save-anthropic-out">$0.00</div>
        </div>
      </div>
    </div>
    <div class="provider-card google">
      <div class="pname">Google</div>
      <div class="pmodel">Gemini 3.1 Pro &mdash; $2.00 / $12.00 per 1M tokens</div>
      <div class="savings-amount" id="save-google">$0.00</div>
      <div class="breakdown">
        <div class="item">
          <div class="blabel">Input saved</div>
          <div class="bvalue" id="save-google-in">$0.00</div>
        </div>
        <div class="item">
          <div class="blabel">Output saved</div>
          <div class="bvalue" id="save-google-out">$0.00</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Monthly Projection -->
  <div class="providers-heading">Monthly Projection</div>
  <div class="providers">
    <div class="provider-card openai">
      <div class="pname">vs OpenAI</div>
      <div class="pmodel">projected monthly savings</div>
      <div class="savings-amount green" id="proj-openai">$0.00</div>
      <div class="sub">per month at current rate</div>
    </div>
    <div class="provider-card anthropic">
      <div class="pname">vs Anthropic</div>
      <div class="pmodel">projected monthly savings</div>
      <div class="savings-amount green" id="proj-anthropic">$0.00</div>
      <div class="sub">per month at current rate</div>
    </div>
    <div class="provider-card google">
      <div class="pname">vs Google</div>
      <div class="pmodel">projected monthly savings</div>
      <div class="savings-amount green" id="proj-google">$0.00</div>
      <div class="sub">per month at current rate</div>
    </div>
  </div>

  <!-- Cloud Agent Platforms -->
  <div class="providers-heading">vs Cloud Agent Platforms</div>
  <div class="providers" style="grid-template-columns: 1fr;">
    <div class="provider-card" style="border-top: 3px solid var(--purple);">
      <div class="pname">Typical Cloud Agent Platform</div>
      <div class="pmodel">based on published API pricing tiers</div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;
        gap:20px;margin-top:16px">
        <div>
          <div class="blabel">MODERATE USE</div>
          <div class="bvalue orange">$15&ndash;60/mo</div>
        </div>
        <div>
          <div class="blabel">HEAVY USE</div>
          <div class="bvalue" style="color: var(--red);">$100&ndash;400+/mo</div>
        </div>
        <div>
          <div class="blabel">YOUR COST</div>
          <div class="bvalue green" style="font-size: 24px;">$0.00</div>
          <div class="sub">local inference</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Energy and FLOPs -->
  <div class="providers-heading">Energy &amp; Compute Avoided</div>
  <div class="metrics-row">
    <div class="metric-card">
      <div class="mheading">Energy Saved (vs GPT-5.3)</div>
      <div class="mvalue green" id="energy-joules">0 <span class="munit">J</span></div>
      <div class="msub" id="energy-kwh">0 kWh of cloud datacenter energy avoided</div>
    </div>
    <div class="metric-card">
      <div class="mheading">FLOPs Avoided (vs GPT-5.3)</div>
      <div class="mvalue purple" id="flops-val">0 <span class="munit">FLOP</span></div>
      <div class="msub" id="flops-sub">cloud compute operations not needed</div>
    </div>
    <div class="metric-card">
      <div class="mheading">CO&#8322; Equivalent Saved</div>
      <div class="mvalue orange" id="co2-val">0 <span class="munit">g</span></div>
      <div class="msub" id="co2-sub">based on US grid avg 0.39 kg CO&#8322;/kWh</div>
    </div>
  </div>

</div>

<script>
function fmt(n) {
  if (n >= 1e15) return (n / 1e15).toFixed(2) + ' PetaFLOP';
  if (n >= 1e12) return (n / 1e12).toFixed(2) + ' TeraFLOP';
  if (n >= 1e9) return (n / 1e9).toFixed(2) + ' GigaFLOP';
  if (n >= 1e6) return (n / 1e6).toFixed(2) + ' MegaFLOP';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + ' KiloFLOP';
  return n.toFixed(0) + ' FLOP';
}

function fmtNum(n) {
  return n.toLocaleString('en-US');
}

function fmtDollar(n) {
  if (n >= 1000) return '$' + n.toLocaleString(
    'en-US', {minimumFractionDigits: 2,
              maximumFractionDigits: 2});
  if (n >= 1) return '$' + n.toFixed(2);
  if (n >= 0.01) return '$' + n.toFixed(3);
  if (n > 0) return '$' + n.toFixed(4);
  return '$0.00';
}

function fmtEnergy(joules) {
  if (joules >= 3600000) return (joules / 3600000).toFixed(2) + ' kWh';
  if (joules >= 3600) return (joules / 3600).toFixed(2) + ' Wh';
  if (joules >= 1000) return (joules / 1000).toFixed(1) + ' kJ';
  return joules.toFixed(1) + ' J';
}

function fmtCO2(grams) {
  if (grams >= 1000) return (grams / 1000).toFixed(2) + ' kg';
  return grams.toFixed(1) + ' g';
}

async function refresh() {
  try {
    const resp = await fetch('/v1/savings');
    if (!resp.ok) return;
    const d = await resp.json();

    document.getElementById('total-calls').textContent = fmtNum(d.total_calls);
    document.getElementById('prompt-tokens')
      .textContent = fmtNum(d.total_prompt_tokens);
    document.getElementById('completion-tokens')
      .textContent = fmtNum(d.total_completion_tokens);
    document.getElementById('total-tokens')
      .textContent = fmtNum(d.total_tokens);

    const providerMap = {};
    (d.per_provider || []).forEach(p => {
      providerMap[p.provider] = p;
    });

    // OpenAI / GPT-5.3
    const oa = providerMap['gpt-5.3'] || {};
    document.getElementById('save-openai')
      .textContent = fmtDollar(oa.total_cost || 0);
    document.getElementById('save-openai-in')
      .textContent = fmtDollar(oa.input_cost || 0);
    document.getElementById('save-openai-out')
      .textContent = fmtDollar(oa.output_cost || 0);

    // Anthropic / Claude Opus 4.6
    const an = providerMap['claude-opus-4.6'] || {};
    document.getElementById('save-anthropic')
      .textContent = fmtDollar(an.total_cost || 0);
    document.getElementById('save-anthropic-in')
      .textContent = fmtDollar(an.input_cost || 0);
    document.getElementById('save-anthropic-out')
      .textContent = fmtDollar(an.output_cost || 0);

    // Google / Gemini 3.1 Pro
    const go = providerMap['gemini-3.1-pro'] || {};
    document.getElementById('save-google')
      .textContent = fmtDollar(go.total_cost || 0);
    document.getElementById('save-google-in')
      .textContent = fmtDollar(go.input_cost || 0);
    document.getElementById('save-google-out')
      .textContent = fmtDollar(go.output_cost || 0);

    // Monthly projections
    const proj = d.monthly_projection || {};
    document.getElementById('proj-openai')
      .textContent = fmtDollar(proj['gpt-5.3'] || 0);
    document.getElementById('proj-anthropic')
      .textContent = fmtDollar(proj['claude-opus-4.6'] || 0);
    document.getElementById('proj-google')
      .textContent = fmtDollar(proj['gemini-3.1-pro'] || 0);

    // Energy / FLOPs (use GPT-5.3 as reference)
    const ej = oa.energy_joules || 0;
    const eWh = oa.energy_wh || 0;
    const fl = oa.flops || 0;
    const co2 = (eWh / 1000) * 390; // grams CO2 (US grid avg 0.39 kg/kWh)

    document.getElementById('energy-joules')
      .innerHTML = fmtEnergy(ej) +
      ' <span class="munit"></span>';
    document.getElementById('energy-kwh')
      .textContent = (eWh / 1000).toFixed(4) +
      ' kWh of cloud datacenter energy avoided';
    document.getElementById('flops-val')
      .innerHTML = fmt(fl) +
      ' <span class="munit"></span>';
    document.getElementById('flops-sub')
      .textContent =
      'cloud compute operations not needed';
    document.getElementById('co2-val')
      .innerHTML = fmtCO2(co2) +
      ' <span class="munit"></span>';

  } catch (e) {
    document.getElementById('status-text')
      .textContent = 'Connection error — retrying...';
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


@dashboard_router.get("/savings-dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the savings dashboard page."""
    return HTMLResponse(content=DASHBOARD_HTML)


__all__ = ["dashboard_router"]
