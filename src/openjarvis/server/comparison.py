"""Comparison page -- static cost comparison of local vs cloud inference."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

comparison_router = APIRouter()

COMPARISON_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenJarvis — Cost Comparison</title>
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

  /* Header */
  .header {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    border-bottom: 1px solid var(--border);
    padding: 24px 32px; display: flex; align-items: center; gap: 16px;
  }
  .header h1 { font-size: 22px; font-weight: 600; }
  .header h1 span { color: var(--accent); }
  .header .nav {
    margin-left: auto; display: flex; gap: 16px; font-size: 13px;
  }
  .header .nav a {
    color: var(--muted); text-decoration: none; transition: color .2s;
  }
  .header .nav a:hover { color: var(--accent); }

  .container { max-width: 1100px; margin: 0 auto; padding: 32px; }

  /* Hero */
  .hero {
    text-align: center; padding: 48px 24px 40px;
  }
  .hero h2 {
    font-size: 38px; font-weight: 700; margin-bottom: 12px;
    background: linear-gradient(135deg, var(--green), var(--accent));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
  }
  .hero .annual {
    font-size: 56px; font-weight: 800; color: var(--green);
    margin: 16px 0 8px; font-variant-numeric: tabular-nums;
  }
  .hero .annual-label {
    font-size: 16px; color: var(--muted); margin-bottom: 8px;
  }
  .hero .sub { font-size: 15px; color: var(--muted); max-width: 600px; margin: 0 auto; }

  /* Scenario picker */
  .section-heading {
    font-size: 16px; font-weight: 600; margin-bottom: 16px;
    color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em;
  }
  .scenario-picker {
    display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 28px;
    justify-content: center;
  }
  .scenario-btn {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 10px 18px; color: var(--text);
    font-size: 13px; font-weight: 500; cursor: pointer;
    transition: all .2s; font-family: inherit;
  }
  .scenario-btn:hover { border-color: var(--accent); color: var(--accent); }
  .scenario-btn.active {
    background: var(--accent); color: #0a0e17; border-color: var(--accent);
    font-weight: 600;
  }

  /* Comparison table */
  .comp-table-wrap {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; overflow-x: auto; margin-bottom: 40px;
  }
  .comp-table {
    width: 100%; border-collapse: collapse; font-size: 14px;
  }
  .comp-table th, .comp-table td {
    padding: 14px 20px; text-align: right; white-space: nowrap;
  }
  .comp-table th:first-child, .comp-table td:first-child { text-align: left; }
  .comp-table thead th {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--muted); border-bottom: 1px solid var(--border);
    font-weight: 600;
  }
  .comp-table tbody tr { border-bottom: 1px solid var(--border); }
  .comp-table tbody tr:last-child { border-bottom: none; }
  .comp-table .local { color: var(--green); font-weight: 700; }
  .comp-table .expensive { color: var(--red); }
  .comp-table .row-label { color: var(--muted); font-weight: 500; }

  /* Interactive calculator */
  .calc-section {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 28px 32px; margin-bottom: 40px;
  }
  .calc-section h3 {
    font-size: 18px; font-weight: 600; margin-bottom: 20px;
  }
  .sliders {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 28px; margin-bottom: 24px;
  }
  .slider-group label {
    display: block; font-size: 13px; color: var(--muted); margin-bottom: 8px;
  }
  .slider-group .slider-value {
    font-size: 24px; font-weight: 700; color: var(--accent);
    margin-bottom: 10px; font-variant-numeric: tabular-nums;
  }
  .slider-group input[type=range] {
    width: 100%; accent-color: var(--accent); cursor: pointer;
  }
  .calc-results {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px;
  }
  .calc-card {
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px; text-align: center;
  }
  .calc-card .cc-label {
    font-size: 11px; text-transform: uppercase; color: var(--muted);
    letter-spacing: 0.04em; margin-bottom: 6px;
  }
  .calc-card .cc-value {
    font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums;
  }
  .calc-card.free .cc-value { color: var(--green); }
  .calc-card.cloud .cc-value { color: var(--red); }

  /* CTA */
  .cta {
    text-align: center; padding: 40px 24px;
    border-top: 1px solid var(--border); margin-top: 8px;
  }
  .cta h3 { font-size: 24px; font-weight: 700; margin-bottom: 12px; }
  .cta .cta-sub { font-size: 15px; color: var(--muted); margin-bottom: 24px; }
  .code-block {
    display: inline-flex; align-items: center; gap: 12px;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 14px 20px; font-size: 16px;
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    color: var(--accent);
  }
  .copy-btn {
    background: none; border: 1px solid var(--border); border-radius: 6px;
    color: var(--muted); cursor: pointer; padding: 6px 12px; font-size: 12px;
    font-family: inherit; transition: all .2s;
  }
  .copy-btn:hover { border-color: var(--accent); color: var(--accent); }

  @media (max-width: 800px) {
    .sliders { grid-template-columns: 1fr; }
    .calc-results { grid-template-columns: repeat(2, 1fr); }
    .hero h2 { font-size: 28px; }
    .hero .annual { font-size: 40px; }
  }
  @media (max-width: 500px) {
    .container { padding: 16px; }
    .calc-results { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>

<div class="header">
  <h1><span>OpenJarvis</span> Cost Comparison</h1>
  <div class="nav">
    <a href="/savings-dashboard">Savings Dashboard</a>
    <a href="/comparison">Comparison</a>
  </div>
</div>

<div class="container">

  <!-- Hero -->
  <div class="hero">
    <h2>Run AI Locally &mdash; $0 API Costs</h2>
    <div class="annual" id="hero-annual">$0</div>
    <div class="annual-label">estimated annual savings vs cloud APIs</div>
    <div class="sub">
      OpenJarvis runs models on your own hardware. Every inference call that would
      cost money on a cloud API is completely free when running locally.
    </div>
  </div>

  <!-- Scenario picker -->
  <div class="section-heading">Choose a Use Case</div>
  <div class="scenario-picker" id="scenario-picker"></div>

  <!-- Comparison table -->
  <div class="comp-table-wrap">
    <table class="comp-table">
      <thead>
        <tr>
          <th></th>
          <th>OpenJarvis (Local)</th>
          <th>GPT-5.3</th>
          <th>Claude Opus 4.6</th>
          <th>Gemini 3.1 Pro</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td class="row-label">Monthly Cost</td>
          <td class="local" id="t-local-m">$0.00</td>
          <td class="expensive" id="t-gpt-m">--</td>
          <td class="expensive" id="t-claude-m">--</td>
          <td class="expensive" id="t-gemini-m">--</td>
        </tr>
        <tr>
          <td class="row-label">Annual Cost</td>
          <td class="local" id="t-local-a">$0.00</td>
          <td class="expensive" id="t-gpt-a">--</td>
          <td class="expensive" id="t-claude-a">--</td>
          <td class="expensive" id="t-gemini-a">--</td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- Interactive calculator -->
  <div class="calc-section">
    <h3>Interactive Cost Calculator</h3>
    <div class="sliders">
      <div class="slider-group">
        <label>Calls per Day</label>
        <div class="slider-value" id="cpd-value">50</div>
        <input type="range" id="cpd-slider" min="1" max="500" value="50">
      </div>
      <div class="slider-group">
        <label>Average Tokens per Call (input + output)</label>
        <div class="slider-value" id="tpc-value">1000</div>
        <input type="range" id="tpc-slider"
          min="100" max="5000" step="100" value="1000">
      </div>
    </div>
    <div class="calc-results">
      <div class="calc-card free">
        <div class="cc-label">OpenJarvis</div>
        <div class="cc-value">$0.00/mo</div>
      </div>
      <div class="calc-card cloud">
        <div class="cc-label">GPT-5.3</div>
        <div class="cc-value" id="calc-gpt">--</div>
      </div>
      <div class="calc-card cloud">
        <div class="cc-label">Claude Opus 4.6</div>
        <div class="cc-value" id="calc-claude">--</div>
      </div>
      <div class="calc-card cloud">
        <div class="cc-label">Gemini 3.1 Pro</div>
        <div class="cc-value" id="calc-gemini">--</div>
      </div>
    </div>
  </div>

  <!-- CTA -->
  <div class="cta">
    <h3>Start Saving Today</h3>
    <div class="cta-sub">Install OpenJarvis and run AI locally
      with zero API costs.</div>
    <div class="code-block">
      <code>git clone https://github.com/open-jarvis/OpenJarvis.git
&& cd OpenJarvis && uv sync</code>
      <button class="copy-btn" id="copy-btn">Copy</button>
    </div>
  </div>

</div>

<script>
// Embedded data -- avoids API calls, keeps the page static and fast.
const CLOUD_PRICING = {
  "gpt-5.3": {
    input_per_1m: 2.00, output_per_1m: 10.00,
    label: "GPT-5.3"
  },
  "claude-opus-4.6": {
    input_per_1m: 5.00, output_per_1m: 25.00,
    label: "Claude Opus 4.6"
  },
  "gemini-3.1-pro": {
    input_per_1m: 2.00, output_per_1m: 12.00,
    label: "Gemini 3.1 Pro"
  }
};

const SCENARIOS = {
  daily_briefing: {
    label: "Daily Briefing",
    description: "Morning brief every 5 minutes, 24/7",
    calls_per_month: 8640, avg_input_tokens: 500, avg_output_tokens: 200
  },
  email_triage: {
    label: "Email Triage",
    description: "Email classification and drafting every 5 minutes",
    calls_per_month: 8640, avg_input_tokens: 800, avg_output_tokens: 300
  },
  research_assistant: {
    label: "Research Assistant",
    description: "Deep research queries, ~20 per day",
    calls_per_month: 600, avg_input_tokens: 2000, avg_output_tokens: 1500
  },
  overnight_coder: {
    label: "Overnight Coder",
    description: "Automated coding tasks, ~100 per night",
    calls_per_month: 3000, avg_input_tokens: 3000, avg_output_tokens: 2000
  },
  always_on: {
    label: "Always-On (All Above)",
    description: "All use cases combined",
    calls_per_month: 20880, avg_input_tokens: 1200, avg_output_tokens: 700
  }
};

function fmtDollar(n) {
  if (n >= 1000) return '$' + n.toLocaleString(
    'en-US', {minimumFractionDigits: 2,
              maximumFractionDigits: 2});
  if (n >= 1) return '$' + n.toFixed(2);
  if (n >= 0.01) return '$' + n.toFixed(3);
  if (n > 0) return '$' + n.toFixed(4);
  return '$0.00';
}

function calcMonthlyCost(callsPerMonth, avgIn, avgOut, providerKey) {
  const p = CLOUD_PRICING[providerKey];
  const inputCost = (callsPerMonth * avgIn / 1e6) * p.input_per_1m;
  const outputCost = (callsPerMonth * avgOut / 1e6) * p.output_per_1m;
  return inputCost + outputCost;
}

// -- Scenario picker --
const picker = document.getElementById('scenario-picker');
let activeScenario = 'always_on';

Object.entries(SCENARIOS).forEach(([key, sc]) => {
  const btn = document.createElement('button');
  btn.className = 'scenario-btn' + (key === activeScenario ? ' active' : '');
  btn.textContent = sc.label;
  btn.dataset.scenario = key;
  btn.addEventListener('click', () => selectScenario(key));
  picker.appendChild(btn);
});

function selectScenario(key) {
  activeScenario = key;
  document.querySelectorAll('.scenario-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.scenario === key);
  });
  updateTable();
}

function updateTable() {
  const sc = SCENARIOS[activeScenario];
  const i = sc.avg_input_tokens, o = sc.avg_output_tokens;
  const c = sc.calls_per_month;
  const gpt = calcMonthlyCost(c, i, o, 'gpt-5.3');
  const claude = calcMonthlyCost(c, i, o, 'claude-opus-4.6');
  const gemini = calcMonthlyCost(c, i, o, 'gemini-3.1-pro');

  document.getElementById('t-gpt-m').textContent = fmtDollar(gpt);
  document.getElementById('t-claude-m').textContent = fmtDollar(claude);
  document.getElementById('t-gemini-m').textContent = fmtDollar(gemini);

  document.getElementById('t-gpt-a').textContent = fmtDollar(gpt * 12);
  document.getElementById('t-claude-a').textContent = fmtDollar(claude * 12);
  document.getElementById('t-gemini-a').textContent = fmtDollar(gemini * 12);

  // Hero: max annual savings across providers
  const maxAnnual = Math.max(gpt, claude, gemini) * 12;
  document.getElementById('hero-annual').textContent = fmtDollar(maxAnnual);
}

// -- Interactive calculator --
const cpdSlider = document.getElementById('cpd-slider');
const tpcSlider = document.getElementById('tpc-slider');
const cpdValue = document.getElementById('cpd-value');
const tpcValue = document.getElementById('tpc-value');

function updateCalc() {
  const cpd = parseInt(cpdSlider.value, 10);
  const tpc = parseInt(tpcSlider.value, 10);
  cpdValue.textContent = cpd;
  tpcValue.textContent = tpc.toLocaleString('en-US');

  // Assume 60% input, 40% output split
  const avgIn = Math.round(tpc * 0.6);
  const avgOut = tpc - avgIn;
  const callsPerMonth = cpd * 30;

  const gpt = calcMonthlyCost(callsPerMonth, avgIn, avgOut, 'gpt-5.3');
  const claude = calcMonthlyCost(callsPerMonth, avgIn, avgOut, 'claude-opus-4.6');
  const gemini = calcMonthlyCost(callsPerMonth, avgIn, avgOut, 'gemini-3.1-pro');

  document.getElementById('calc-gpt').textContent = fmtDollar(gpt) + '/mo';
  document.getElementById('calc-claude').textContent = fmtDollar(claude) + '/mo';
  document.getElementById('calc-gemini').textContent = fmtDollar(gemini) + '/mo';
}

cpdSlider.addEventListener('input', updateCalc);
tpcSlider.addEventListener('input', updateCalc);

// -- Copy button --
document.getElementById('copy-btn').addEventListener('click', () => {
  const cmd = 'git clone https://github.com/open-jarvis/'
    + 'OpenJarvis.git && cd OpenJarvis && uv sync';
  navigator.clipboard.writeText(cmd).then(() => {
    const btn = document.getElementById('copy-btn');
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = 'Copy'; }, 2000);
  });
});

// Initialize
updateTable();
updateCalc();
</script>
</body>
</html>
"""


@comparison_router.get("/comparison", response_class=HTMLResponse)
async def comparison():
    """Serve the cost comparison page."""
    return HTMLResponse(content=COMPARISON_HTML)


__all__ = ["comparison_router"]
