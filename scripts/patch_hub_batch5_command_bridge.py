from pathlib import Path

ROOT = Path.cwd()
tool_path = ROOT / "src" / "openjarvis" / "tools" / "serena_hub.py"
cli_path = ROOT / "src" / "openjarvis" / "cli" / "hub_cmd.py"

tool = tool_path.read_text(encoding="utf-8")
cli = cli_path.read_text(encoding="utf-8")

# -------------------------------------------------------------------
# 1. Add request parsing import for POST command bridge.
# -------------------------------------------------------------------
if "from urllib.parse import parse_qs" not in tool:
    tool = tool.replace(
        "from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler\n",
        "from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler\nfrom urllib.parse import parse_qs\n",
    )

# -------------------------------------------------------------------
# 2. Add approval/self-upgrade functions before command intake.
# -------------------------------------------------------------------
insert_before = tool.index("def hub_command_intake(")

batch5_functions = r'''def _looks_like_self_upgrade(command: str) -> bool:
    text = str(command or "").lower()
    terms = [
        "fix yourself",
        "upgrade yourself",
        "self upgrade",
        "self-upgrade",
        "improve yourself",
        "edit your code",
        "patch serena",
        "modify serena",
        "update serena",
        "upgrade skill",
        "convert skill",
        "create skill",
        "change code",
        "write code to repo",
        "commit",
    ]
    return any(term in text for term in terms)


def hub_self_upgrade_plan(
    request: str,
    operator: str = "hub",
    target_area: str = "unknown",
    risk_level: str = "review_required",
) -> dict[str, Any]:
    """Create a local plan-only self-upgrade artifact.

    This function never patches files, executes shell commands, or commits.
    """
    _ensure_base_state()

    safe_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "id": f"self-upgrade-plan-{safe_id}",
        "request": request,
        "operator": operator,
        "target_area": target_area,
        "risk_level": risk_level,
        "status": "plan_only_pending_approval",
        "allowed_now": [
            "create local plan artifact",
            "record Hub activity",
            "request human approval",
        ],
        "blocked_without_approval": [
            "modify source files",
            "delete files",
            "run shell commands",
            "install dependencies",
            "commit changes",
            "push changes",
            "touch credentials",
            "read or export secrets",
        ],
        "required_before_execution": [
            "human approval",
            "explicit file list",
            "patch plan",
            "secret scan pass",
            "smoke test plan",
            "rollback note",
        ],
        "secret_scan_required_before_commit": True,
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }

    path = HUB_ROOT / "self-upgrade-plans" / f"{payload['id']}.json"
    _write_json(path, payload)

    approval = {
        "id": f"approval-{safe_id}",
        "type": "self_upgrade",
        "status": "pending",
        "request": request,
        "plan_path": str(path).replace("\\", "/"),
        "requires_explicit_user_approval": True,
        "timestamp": _utc_now(),
    }

    approvals_path = HUB_ROOT / "state" / "approvals.json"
    existing = _safe_read_json(approvals_path)
    if not isinstance(existing, dict):
        existing = {"approvals": []}
    approvals = existing.setdefault("approvals", [])
    approvals.append(approval)
    existing["approvals"] = approvals[-100:]
    existing["last_approval"] = approval
    existing["timestamp"] = _utc_now()
    _write_json(approvals_path, existing)

    hub_orb_state(
        orb_state="approval",
        active_operator=operator,
        active_task=f"Approval needed: {request}",
        active_section="safety",
    )

    hub_activity_event(
        operator=operator,
        event_type="self_upgrade_plan",
        message=f"Self-upgrade plan created and blocked pending approval: {request}",
        status="approval_required",
        artifact_path=str(path).replace("\\", "/"),
    )

    return payload


def hub_secret_scan_status() -> dict[str, Any]:
    """Create a conservative local secret scan status placeholder.

    Full secret scanning is intentionally run from PowerShell/git grep before commit.
    This records the policy gate for Hub/self-upgrade.
    """
    payload = {
        "status": "required_before_commit",
        "policy": "Serena may not commit code until local secret scans pass.",
        "blocked_patterns": [
            "api keys",
            "application passwords",
            "oauth refresh tokens",
            "github tokens",
            "openai keys",
            "wordpress application passwords",
            "google credentials",
            "payment provider secrets",
            ".env files",
        ],
        "recommended_commands": [
            "git grep tracked files for secret assignments",
            "git grep tracked files for common token formats",
            "do not paste findings into chat",
            "rotate any real leaked credential",
        ],
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }
    _write_json(HUB_ROOT / "state" / "secret_scan_status.json", payload)
    return payload


'''

if "def hub_self_upgrade_plan(" not in tool:
    tool = tool[:insert_before] + batch5_functions + tool[insert_before:]

# -------------------------------------------------------------------
# 3. Patch command intake to create self-upgrade plans for risky commands.
# -------------------------------------------------------------------
old = '''    hub_orb_state(
        orb_state="thinking",
        active_operator=operator,
        active_task=command,
        active_section=target_section,
    )

    hub_activity_event(
        operator=operator,
        event_type="command_intake",
        message=f"Command received: {command}",
        status="received",
        artifact_path=str(queue_path).replace("\\\\", "/"),
    )

    return payload
'''

new = '''    if _looks_like_self_upgrade(command):
        plan = hub_self_upgrade_plan(
            request=command,
            operator=operator,
            target_area=target_section,
            risk_level="approval_required",
        )
        payload["self_upgrade_plan"] = plan.get("id")
        payload["status"] = "plan_only_pending_approval"
        _write_json(queue_path, existing)
    else:
        hub_orb_state(
            orb_state="thinking",
            active_operator=operator,
            active_task=command,
            active_section=target_section,
        )

    hub_activity_event(
        operator=operator,
        event_type="command_intake",
        message=f"Command received: {command}",
        status=payload["status"],
        artifact_path=str(queue_path).replace("\\\\", "/"),
    )

    return payload
'''

if old in tool and "self_upgrade_plan" not in tool[tool.index("def hub_command_intake("):tool.index("def hub_live_tick(")]:
    tool = tool.replace(old, new)

# -------------------------------------------------------------------
# 4. Add secret scan to web sync sources.
# -------------------------------------------------------------------
sync_marker = '''        "live_tick.json": HUB_ROOT / "state" / "live_tick.json",
        "artifact_summary.json": HUB_ROOT / "rollups" / "artifact_summary.json",
'''

sync_replacement = '''        "live_tick.json": HUB_ROOT / "state" / "live_tick.json",
        "secret_scan_status.json": HUB_ROOT / "state" / "secret_scan_status.json",
        "artifact_summary.json": HUB_ROOT / "rollups" / "artifact_summary.json",
'''

if sync_marker in tool and '"secret_scan_status.json": HUB_ROOT / "state" / "secret_scan_status.json",' not in tool:
    tool = tool.replace(sync_marker, sync_replacement)

# -------------------------------------------------------------------
# 5. Patch server handler with safe local POST command bridge.
# -------------------------------------------------------------------
old_handler = '''        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()
'''

new_handler = r'''        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_POST(self) -> None:
            if self.path != "/api/command-intake":
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"status":"not_found"}')
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8", errors="replace")
                data = parse_qs(raw)

                command = (data.get("command", [""])[0] or "").strip()
                operator = (data.get("operator", ["hub"])[0] or "hub").strip()
                target_section = (data.get("target_section", ["overview"])[0] or "overview").strip()
                priority = (data.get("priority", ["normal"])[0] or "normal").strip()

                if not command:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"error","error":"command is required"}')
                    return

                result = hub_command_intake(
                    command=command,
                    operator=operator,
                    target_section=target_section,
                    priority=priority,
                )
                hub_web_sync_data()

                body = json.dumps(result, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                body = json.dumps({"status": "error", "error": str(exc)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
'''

if old_handler in tool and "def do_POST(self) -> None:" not in tool:
    tool = tool.replace(old_handler, new_handler)

# -------------------------------------------------------------------
# 6. Patch JS to POST command bar to local endpoint.
# -------------------------------------------------------------------
if "async function submitCommand()" not in tool:
    tool = tool.replace(
        """async function refresh() {
  const data = await loadAll();
  renderOrb(data.hubState);
  renderSections(data.sections, data.hubState?.active_section || "overview");
  renderMetrics(data);
  renderTimeline(data);
  setText("syncStatus", "Last refresh: " + new Date().toLocaleTimeString());
}

refresh();
setInterval(refresh, 3000);
""",
        """async function refresh() {
  const data = await loadAll();
  renderOrb(data.hubState);
  renderSections(data.sections, data.hubState?.active_section || "overview");
  renderMetrics(data);
  renderTimeline(data);
  setText("syncStatus", "Last refresh: " + new Date().toLocaleTimeString());
}

async function submitCommand() {
  const input = document.getElementById("commandInput");
  const status = document.getElementById("commandStatus");
  const command = (input?.value || "").trim();
  if (!command) {
    if (status) status.textContent = "Enter a command first.";
    return;
  }

  const body = new URLSearchParams({
    command,
    operator: "hub",
    target_section: "overview",
    priority: "normal"
  });

  try {
    const response = await fetch("/api/command-intake", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body
    });
    const result = await response.json();
    if (status) status.textContent = "Command recorded: " + (result.status || "received");
    if (input) input.value = "";
    await refresh();
  } catch (error) {
    if (status) status.textContent = "Command bridge unavailable. Use serena hub serve.";
  }
}

refresh();
setInterval(refresh, 3000);
document.addEventListener("DOMContentLoaded", () => {
  const button = document.getElementById("commandSubmit");
  const input = document.getElementById("commandInput");
  if (button) button.addEventListener("click", submitCommand);
  if (input) {
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") submitCommand();
    });
  }
});
"""
    )

# Replace static command bar HTML.
tool = tool.replace(
    '''<div class="input">Dynamic local Hub. Use serena hub serve so browser JSON fetch works.</div>
      <div class="pill" id="orbPill">Orb state: loading</div>''',
    '''<div class="input">
        <input id="commandInput" placeholder="Type a local Serena command. Self-upgrade creates approval plan only." style="width:100%;background:transparent;border:0;color:#e8fbff;outline:none;">
      </div>
      <button id="commandSubmit" class="pill" style="cursor:pointer;">Send</button>
      <div class="pill" id="orbPill">Orb state: loading</div>
      <div class="pill" id="commandStatus">Command bridge ready</div>'''
)

# Chat grid needs more columns for button/status.
tool = tool.replace(
    "grid-template-columns: 72px 1fr 210px;",
    "grid-template-columns: 72px 1fr 92px 180px 190px;"
)

# -------------------------------------------------------------------
# 7. Update __all__.
# -------------------------------------------------------------------
for name in ["hub_self_upgrade_plan", "hub_secret_scan_status"]:
    if f'"{name}",' not in tool:
        tool = tool.replace('    "hub_command_intake",\n', f'    "{name}",\n    "hub_command_intake",\n')

tool_path.write_text(tool, encoding="utf-8")

# -------------------------------------------------------------------
# 8. Patch CLI imports.
# -------------------------------------------------------------------
for name in [
    "    hub_secret_scan_status,\n",
    "    hub_self_upgrade_plan,\n",
]:
    if name not in cli:
        cli = cli.replace("    hub_schedule_rollup,\n", "    hub_schedule_rollup,\n" + name)

# -------------------------------------------------------------------
# 9. Add CLI commands before command-intake.
# -------------------------------------------------------------------
marker = '@hub.command("command-intake")\n@click.argument("command")\n'
commands = r'''@hub.command("self-upgrade-plan")
@click.argument("request")
@click.option("--operator", default="hub")
@click.option("--target-area", default="unknown")
@click.option("--risk-level", default="review_required")
def self_upgrade_plan(request, operator, target_area, risk_level):
    """Create a local plan-only self-upgrade request pending approval."""
    _print(
        hub_self_upgrade_plan(
            request=request,
            operator=operator,
            target_area=target_area,
            risk_level=risk_level,
        )
    )


@hub.command("secret-scan-status")
def secret_scan_status():
    """Record Hub secret-scan policy gate status."""
    _print(hub_secret_scan_status())


'''

if '@hub.command("self-upgrade-plan")' not in cli:
    cli = cli.replace(marker, commands + marker)

cli_path.write_text(cli, encoding="utf-8")

print("[OK] Patched Serena Hub Batch 5 command bridge")
print("[OK] Added safe browser command intake and self-upgrade plan foundation")