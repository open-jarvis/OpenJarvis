from pathlib import Path

ROOT = Path.cwd()
tool_path = ROOT / "src" / "openjarvis" / "tools" / "serena_hub.py"
cli_path = ROOT / "src" / "openjarvis" / "cli" / "hub_cmd.py"

tool = tool_path.read_text(encoding="utf-8")
cli = cli_path.read_text(encoding="utf-8")

# -----------------------------
# 1. Add imports for local server and copy
# -----------------------------
if "import shutil" not in tool:
    tool = tool.replace("import os\n", "import os\nimport shutil\n")
if "from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler" not in tool:
    tool = tool.replace(
        "from pathlib import Path\n",
        "from pathlib import Path\nfrom http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler\n",
    )

# -----------------------------
# 2. Add web sync + serve functions before hub_web_build
# -----------------------------
insert_before = tool.index("def hub_web_build()")

batch3_functions = r'''def hub_web_sync_data() -> dict[str, Any]:
    """Copy Hub state and rollup JSON into web/data for browser fetch."""
    _ensure_base_state()
    hub_widget_registry()
    hub_dashboard_sections()
    hub_artifact_summary()
    hub_operator_rollup()
    hub_crm_rollup()
    hub_finance_rollup()
    hub_schedule_rollup()
    hub_document_rollup()
    hub_safety_rollup()

    web_data = HUB_ROOT / "web" / "data"
    web_data.mkdir(parents=True, exist_ok=True)

    sources = {
        "hub_state.json": HUB_ROOT / "state" / "hub_state.json",
        "widgets.json": HUB_ROOT / "state" / "widgets.json",
        "activity_events.json": HUB_ROOT / "state" / "activity_events.json",
        "approvals.json": HUB_ROOT / "state" / "approvals.json",
        "dashboard_sections.json": HUB_ROOT / "state" / "dashboard_sections.json",
        "artifact_summary.json": HUB_ROOT / "rollups" / "artifact_summary.json",
        "operator_rollup.json": HUB_ROOT / "rollups" / "operator_rollup.json",
        "crm_rollup.json": HUB_ROOT / "rollups" / "crm_rollup.json",
        "finance_rollup.json": HUB_ROOT / "rollups" / "finance_rollup.json",
        "schedule_rollup.json": HUB_ROOT / "rollups" / "schedule_rollup.json",
        "document_rollup.json": HUB_ROOT / "rollups" / "document_rollup.json",
        "safety_rollup.json": HUB_ROOT / "rollups" / "safety_rollup.json",
    }

    copied = []
    missing = []

    for name, source in sources.items():
        target = web_data / name
        if source.exists():
            shutil.copyfile(source, target)
            copied.append(str(target).replace("\\", "/"))
        else:
            missing.append(str(source).replace("\\", "/"))

    payload = {
        "status": "synced",
        "web_data_root": str(web_data).replace("\\", "/"),
        "copied_count": len(copied),
        "copied": copied,
        "missing": missing,
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }
    _write_json(web_data / "sync_status.json", payload)
    return payload


def hub_serve_web(host: str = "127.0.0.1", port: int = 8765, build: bool = True) -> dict[str, Any]:
    """Serve the local Hub web directory over HTTP for dynamic JSON fetch."""
    if build:
        hub_web_build()
    else:
        hub_web_sync_data()

    web_root = (HUB_ROOT / "web").resolve()
    if not web_root.exists():
        return {
            "status": "failed",
            "reason": "Hub web root does not exist.",
            "web_root": str(web_root),
            "external_action_taken": False,
            "timestamp": _utc_now(),
        }

    class HubHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(web_root), **kwargs)

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    server = ThreadingHTTPServer((host, int(port)), HubHandler)
    url = f"http://{host}:{int(port)}/index.html"

    print(f"Serena Hub serving at {url}")
    print(f"Web root: {web_root}")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    return {
        "status": "stopped",
        "url": url,
        "web_root": str(web_root),
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }


'''

if "def hub_web_sync_data()" not in tool:
    tool = tool[:insert_before] + batch3_functions + tool[insert_before:]

# -----------------------------
# 3. Replace hub_web_build with dynamic version
# -----------------------------
start = tool.index("def hub_web_build()")
end = tool.index("\n\n__all__ = [")

new_web_build = r'''def hub_web_build() -> dict[str, Any]:
    _ensure_base_state()
    widget_registry = hub_widget_registry()
    dashboard_sections = hub_dashboard_sections()
    artifact_summary = hub_artifact_summary()
    operator_rollup = hub_operator_rollup()
    safety_rollup = hub_safety_rollup()
    crm_rollup = hub_crm_rollup()
    finance_rollup = hub_finance_rollup()
    schedule_rollup = hub_schedule_rollup()
    document_rollup = hub_document_rollup()

    web_root = HUB_ROOT / "web"
    assets_root = web_root / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    css = """\
:root {
  --bg: #05060a;
  --panel: rgba(10, 18, 32, 0.62);
  --panel2: rgba(1, 7, 18, 0.78);
  --cyan: #00f0ff;
  --blue: #2f7bff;
  --purple: #a020f0;
  --green: #33ff99;
  --amber: #ffcc66;
  --red: #ff4d6d;
  --text: #e8fbff;
  --muted: #89a7b5;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  height: 100vh;
  overflow: hidden;
  font-family: Inter, Segoe UI, system-ui, sans-serif;
  color: var(--text);
  background:
    radial-gradient(circle at 50% 42%, rgba(0, 240, 255, .17), transparent 20%),
    radial-gradient(circle at 82% 18%, rgba(160, 32, 240, .15), transparent 25%),
    radial-gradient(circle at 20% 82%, rgba(47, 123, 255, .12), transparent 22%),
    linear-gradient(135deg, #05060a 0%, #0a0a0f 50%, #10111a 100%);
}
body:before {
  content: "";
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(rgba(0,240,255,.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,240,255,.05) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(circle at center, black, transparent 78%);
  pointer-events: none;
}
.shell {
  height: 100vh;
  display: grid;
  grid-template-rows: 58px 1fr 92px;
  grid-template-columns: 235px 1fr 350px;
  gap: 12px;
  padding: 12px;
}
.top, .rail, .stage, .timeline, .chat {
  border: 1px solid rgba(0, 240, 255, .25);
  background: var(--panel);
  backdrop-filter: blur(18px);
  box-shadow: 0 0 30px rgba(0, 240, 255, .08), inset 0 0 32px rgba(255,255,255,.025);
  border-radius: 22px;
}
.top {
  grid-column: 1 / 4;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  letter-spacing: .08em;
  text-transform: uppercase;
  font-size: 12px;
}
.rail { padding: 16px; overflow: auto; }
.stage { position: relative; overflow: hidden; padding: 22px; }
.timeline { padding: 16px; overflow: auto; }
.chat {
  grid-column: 1 / 4;
  display: grid;
  grid-template-columns: 72px 1fr 210px;
  align-items: center;
  gap: 14px;
  padding: 14px;
}
.brand { color: var(--cyan); text-shadow: 0 0 18px var(--cyan); font-weight: 900; }
.pill {
  padding: 7px 10px;
  border: 1px solid rgba(0, 240, 255, .25);
  border-radius: 999px;
  color: var(--muted);
  background: rgba(0,0,0,.2);
}
.operator {
  padding: 10px 12px;
  margin-bottom: 8px;
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 14px;
  color: var(--muted);
  background: rgba(255,255,255,.035);
}
.operator.active, .operator:hover {
  color: var(--cyan);
  border-color: rgba(0, 240, 255, .48);
  box-shadow: inset 0 0 18px rgba(0,240,255,.08);
}
.orb {
  position: absolute;
  right: 5%;
  top: 9%;
  width: 118px;
  height: 118px;
  border-radius: 50%;
  background:
    radial-gradient(circle at 38% 36%, #ffffff, var(--cyan) 11%, var(--blue) 32%, rgba(160,32,240,.8) 56%, transparent 72%);
  box-shadow:
    0 0 40px rgba(0,240,255,.95),
    0 0 110px rgba(47,123,255,.48),
    0 0 160px rgba(160,32,240,.32);
  animation: breathe 3.6s ease-in-out infinite;
}
.orb.approval {
  box-shadow: 0 0 42px rgba(255,204,102,.95), 0 0 120px rgba(255,204,102,.35);
}
.orb.blocked {
  box-shadow: 0 0 42px rgba(255,77,109,.95), 0 0 120px rgba(255,77,109,.35);
}
.orb.completed {
  box-shadow: 0 0 42px rgba(51,255,153,.95), 0 0 120px rgba(51,255,153,.35);
}
.orb:before, .orb:after {
  content: "";
  position: absolute;
  inset: -22px;
  border-radius: 50%;
  border: 1px solid rgba(0,240,255,.32);
  animation: spin 8s linear infinite;
}
.orb:after {
  inset: -42px;
  border-color: rgba(160,32,240,.22);
  animation-duration: 13s;
  animation-direction: reverse;
}
@keyframes breathe {
  0%, 100% { filter: brightness(.9); transform: scale(.98); }
  50% { filter: brightness(1.25); transform: scale(1.05); }
}
@keyframes spin { to { rotate: 360deg; } }
.hero {
  max-width: 720px;
  padding: 22px;
  border-radius: 24px;
  border: 1px solid rgba(0,240,255,.17);
  background: linear-gradient(135deg, rgba(0,240,255,.08), rgba(160,32,240,.06));
}
.hero h1 { margin: 0; font-size: 38px; letter-spacing: -.03em; }
.hero p { color: var(--muted); line-height: 1.6; }
.state-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
.state {
  font-size: 11px;
  color: var(--muted);
  border: 1px solid rgba(255,255,255,.1);
  padding: 6px 8px;
  border-radius: 999px;
  background: rgba(0,0,0,.22);
}
.state.active { color: var(--cyan); border-color: rgba(0,240,255,.5); }
.widget-grid {
  position: absolute;
  left: 24px;
  right: 24px;
  bottom: 24px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}
.widget {
  min-height: 132px;
  padding: 16px;
  border-radius: 18px;
  border: 1px solid rgba(0,240,255,.18);
  background: var(--panel2);
  box-shadow: 0 16px 60px rgba(0,0,0,.22);
}
.widget h3 { margin: 0 0 8px; color: var(--cyan); }
.metric { font-size: 34px; font-weight: 900; }
.muted { color: var(--muted); font-size: 13px; line-height: 1.5; }
.event {
  border-left: 2px solid var(--cyan);
  padding: 8px 0 8px 12px;
  margin: 0 0 10px;
  color: var(--muted);
  font-size: 13px;
  word-break: break-word;
}
.event b { color: var(--text); }
.input {
  height: 46px;
  border-radius: 999px;
  border: 1px solid rgba(0,240,255,.25);
  background: rgba(0,0,0,.28);
  display: flex;
  align-items: center;
  padding: 0 18px;
  color: var(--muted);
}
.mic {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: rgba(0,240,255,.12);
  color: var(--cyan);
  border: 1px solid rgba(0,240,255,.35);
  box-shadow: 0 0 22px rgba(0,240,255,.22);
}
@media (max-width: 1100px) {
  .shell { grid-template-columns: 190px 1fr; }
  .timeline { display: none; }
  .top, .chat { grid-column: 1 / 3; }
  .widget-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
"""

    js = """\
const dataFiles = {
  hubState: "data/hub_state.json",
  widgets: "data/widgets.json",
  activity: "data/activity_events.json",
  sections: "data/dashboard_sections.json",
  artifactSummary: "data/artifact_summary.json",
  operatorRollup: "data/operator_rollup.json",
  crmRollup: "data/crm_rollup.json",
  financeRollup: "data/finance_rollup.json",
  scheduleRollup: "data/schedule_rollup.json",
  documentRollup: "data/document_rollup.json",
  safetyRollup: "data/safety_rollup.json"
};

async function loadJson(path) {
  const response = await fetch(path + "?t=" + Date.now(), { cache: "no-store" });
  if (!response.ok) throw new Error(path + " failed: " + response.status);
  return response.json();
}

async function loadAll() {
  const entries = await Promise.all(
    Object.entries(dataFiles).map(async ([key, path]) => {
      try { return [key, await loadJson(path)]; }
      catch (error) { return [key, { error: String(error) }]; }
    })
  );
  return Object.fromEntries(entries);
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function renderSections(sections, activeSection) {
  const rail = document.getElementById("operatorRail");
  if (!rail) return;
  const list = sections?.sections || [];
  rail.innerHTML = list.map(section => `
    <div class="operator ${section.id === activeSection ? "active" : ""}">
      ${section.title}
      <div class="muted">${section.operator}</div>
    </div>
  `).join("");
}

function renderOrb(state) {
  const orb = document.getElementById("serenaOrb");
  if (!orb) return;
  const key = state?.orb_state || "idle";
  orb.className = "orb " + key;
  setText("voiceState", "Voice: " + key);
  setText("activeOperator", "Active Operator: " + (state?.active_operator || "hub"));
  setText("safetyState", "Safety: " + (state?.safety_state || "green") + " / local-only");
  setText("orbPill", "Orb state: " + key);
  setText("heroTitle", "Serena Command Center");
  setText("heroText", state?.active_task || state?.orb_state_description || "Local-first operating cockpit.");
  document.querySelectorAll(".state").forEach(el => {
    el.classList.toggle("active", el.textContent === key);
  });
}

function metricCard(title, metric, description) {
  return `
    <div class="widget">
      <h3>${title}</h3>
      <div class="metric">${metric ?? 0}</div>
      <div class="muted">${description}</div>
    </div>
  `;
}

function renderMetrics(data) {
  const grid = document.getElementById("widgetGrid");
  if (!grid) return;
  grid.innerHTML = [
    metricCard("Operators", data.operatorRollup?.operator_count, "Local operator sources discovered."),
    metricCard("CRM Signals", data.crmRollup?.artifact_count, "Contact, customer, lead, lifecycle artifacts."),
    metricCard("Safety", data.safetyRollup?.artifact_count, "Blocked, approval, sensitive-signal artifacts."),
    metricCard("Finance", data.financeRollup?.artifact_count, "Accounting, revenue, billing, invoice signals."),
    metricCard("Schedule", data.scheduleRollup?.artifact_count, "Calendar, booking, appointment signals."),
    metricCard("Documents", data.documentRollup?.artifact_count, "Docs, files, PDF, and Drive signals."),
  ].join("");
}

function renderTimeline(data) {
  const timeline = document.getElementById("timeline");
  if (!timeline) return;

  const events = (data.activity?.events || []).slice(-8).reverse();
  const newest = data.artifactSummary?.newest_artifacts || [];

  const eventHtml = events.map(event => `
    <div class="event">
      <b>${event.operator || "hub"} | ${event.status || "event"}</b><br>
      <span>${event.event_type || "event"}: ${event.message || ""}</span>
    </div>
  `).join("");

  const newestHtml = newest.slice(0, 5).map(item => `
    <div class="event">
      <b>${item.operator || "unknown"} | ${item.artifact_type || "artifact"}</b><br>
      <span>${item.path || ""}</span>
    </div>
  `).join("");

  timeline.innerHTML = `
    <h3>Activity Timeline</h3>
    <div class="event"><b>Dynamic State</b><br><span>Reading local JSON over HTTP every 3 seconds.</span></div>
    ${eventHtml || '<div class="event">No activity events yet.</div>'}
    <h3>Newest Artifacts</h3>
    ${newestHtml || '<div class="event">No artifacts found.</div>'}
  `;
}

async function refresh() {
  const data = await loadAll();
  renderOrb(data.hubState);
  renderSections(data.sections, data.hubState?.active_section || "overview");
  renderMetrics(data);
  renderTimeline(data);
  setText("syncStatus", "Last refresh: " + new Date().toLocaleTimeString());
}

refresh();
setInterval(refresh, 3000);
"""

    html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Serena Hub Command Center</title>
  <link rel="stylesheet" href="assets/hub.css">
</head>
<body>
  <main class="shell">
    <section class="top">
      <div><span class="brand">SERENA HUB</span> | Dynamic Command Center</div>
      <div class="pill" id="voiceState">Voice: loading</div>
      <div class="pill" id="safetyState">Safety: loading</div>
      <div class="pill" id="activeOperator">Active Operator: loading</div>
    </section>

    <aside class="rail" id="operatorRail">
      <div class="operator active">Loading sections...</div>
    </aside>

    <section class="stage">
      <div class="orb" id="serenaOrb" aria-label="Serena Orb"></div>
      <div class="hero">
        <h1 id="heroTitle">Serena Command Center</h1>
        <p id="heroText">Loading local Hub state...</p>
        <div class="state-row">
          <span class="state">idle</span>
          <span class="state">wake</span>
          <span class="state">listening</span>
          <span class="state">thinking</span>
          <span class="state">speaking</span>
          <span class="state">working</span>
          <span class="state">approval</span>
          <span class="state">blocked</span>
          <span class="state">completed</span>
        </div>
      </div>

      <div class="widget-grid" id="widgetGrid">
        <div class="widget"><h3>Loading</h3><div class="metric">...</div><div class="muted">Reading local JSON.</div></div>
      </div>
    </section>

    <aside class="timeline" id="timeline">
      <h3>Activity Timeline</h3>
      <div class="event">Loading activity events...</div>
    </aside>

    <section class="chat">
      <div class="mic">ORB</div>
      <div class="input">Dynamic local Hub. Use serena hub serve so browser JSON fetch works.</div>
      <div class="pill" id="orbPill">Orb state: loading</div>
    </section>
  </main>
  <script src="assets/hub.js"></script>
</body>
</html>
"""

    (assets_root / "hub.css").write_text(css, encoding="utf-8")
    (assets_root / "hub.js").write_text(js, encoding="utf-8")
    (web_root / "index.html").write_text(html, encoding="utf-8")

    sync_payload = hub_web_sync_data()

    hub_activity_event(
        operator="hub",
        event_type="web_build",
        message="Local Serena Hub Batch 3 dynamic web shell generated.",
        status="completed",
        artifact_path=str(web_root / "index.html").replace("\\", "/"),
    )

    return {
        "status": "built",
        "web_path": str(web_root / "index.html").replace("\\", "/"),
        "css_path": str(assets_root / "hub.css").replace("\\", "/"),
        "js_path": str(assets_root / "hub.js").replace("\\", "/"),
        "data_sync": sync_payload,
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }
'''

tool = tool[:start] + new_web_build + tool[end:]

# -----------------------------
# 4. Update __all__
# -----------------------------
for name in ["hub_web_sync_data", "hub_serve_web"]:
    if f'"{name}",' not in tool:
        tool = tool.replace('    "hub_web_build",\n', f'    "{name}",\n    "hub_web_build",\n')

tool_path.write_text(tool, encoding="utf-8")

# -----------------------------
# 5. Patch CLI imports
# -----------------------------
import_marker = "    hub_web_build,\n"
for name in [
    "    hub_serve_web,\n",
    "    hub_web_sync_data,\n",
]:
    if name not in cli:
        cli = cli.replace(import_marker, name + import_marker)

# -----------------------------
# 6. Add CLI commands before web-build
# -----------------------------
web_marker = '@hub.command("web-build")\ndef web_build():\n'
commands = r'''@hub.command("web-sync-data")
def web_sync_data():
    """Copy Hub JSON state/rollups into web/data for dynamic browser fetch."""
    _print(hub_web_sync_data())


@hub.command("serve")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8765, type=int)
@click.option("--no-build", is_flag=True)
def serve(host, port, no_build):
    """Serve local Serena Hub over HTTP for dynamic JSON loading."""
    _print(hub_serve_web(host=host, port=port, build=not no_build))


'''

if '@hub.command("web-sync-data")' not in cli:
    cli = cli.replace(web_marker, commands + web_marker)

cli_path.write_text(cli, encoding="utf-8")

print("[OK] Patched Serena Hub Batch 3 dynamic web")
print("[OK] Added web-sync-data and serve CLI commands")