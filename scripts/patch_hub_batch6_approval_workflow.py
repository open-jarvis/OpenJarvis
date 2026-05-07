from pathlib import Path

ROOT = Path.cwd()
tool_path = ROOT / "src" / "openjarvis" / "tools" / "serena_hub.py"
cli_path = ROOT / "src" / "openjarvis" / "cli" / "hub_cmd.py"

tool = tool_path.read_text(encoding="utf-8")
cli = cli_path.read_text(encoding="utf-8")

# -------------------------------------------------------------------
# 1. Add approval list/decision functions before self-upgrade plan.
# -------------------------------------------------------------------
insert_before = tool.index("def hub_self_upgrade_plan(")

batch6_functions = r'''def hub_approval_list(status: str = "all") -> dict[str, Any]:
    """List local Hub approvals. No execution occurs."""
    _ensure_base_state()

    approvals_path = HUB_ROOT / "state" / "approvals.json"
    existing = _safe_read_json(approvals_path)
    if not isinstance(existing, dict):
        existing = {"approvals": []}

    approvals = existing.get("approvals", [])
    if status != "all":
        approvals = [item for item in approvals if item.get("status") == status]

    payload = {
        "status": "listed",
        "filter": status,
        "approval_count": len(approvals),
        "approvals": approvals,
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }
    return payload


def hub_approval_decision(
    approval_id: str,
    decision: str,
    reason: str = "",
    decided_by: str = "Kyle",
) -> dict[str, Any]:
    """Approve or deny a local approval record.

    Approval only changes local approval state. It never executes code,
    patches files, runs shell commands, commits, pushes, or touches secrets.
    """
    _ensure_base_state()

    normalized_decision = str(decision or "").strip().lower()
    if normalized_decision not in {"approved", "denied"}:
        return {
            "status": "error",
            "error": "decision must be approved or denied",
            "external_action_taken": False,
            "timestamp": _utc_now(),
        }

    approvals_path = HUB_ROOT / "state" / "approvals.json"
    existing = _safe_read_json(approvals_path)
    if not isinstance(existing, dict):
        existing = {"approvals": []}

    approvals = existing.setdefault("approvals", [])
    target = None
    for item in approvals:
        if item.get("id") == approval_id:
            target = item
            break

    if target is None:
        return {
            "status": "not_found",
            "approval_id": approval_id,
            "external_action_taken": False,
            "timestamp": _utc_now(),
        }

    target["status"] = normalized_decision
    target["decision_reason"] = reason
    target["decided_by"] = decided_by
    target["decided_at"] = _utc_now()
    target["execution_allowed_by_this_decision"] = False
    target["execution_requires_separate_cli_path"] = True
    target["required_execution_gates"] = [
        "explicit approval id",
        "explicit file list",
        "patch plan",
        "secret scan pass",
        "smoke test pass",
        "rollback note",
    ]

    existing["last_approval"] = target
    existing["timestamp"] = _utc_now()
    _write_json(approvals_path, existing)

    if normalized_decision == "approved":
        hub_orb_state(
            orb_state="approval",
            active_operator="hub",
            active_task=f"Approval marked approved, execution still gated: {approval_id}",
            active_section="safety",
        )
        event_status = "approved"
        event_message = f"Approval marked approved but no execution performed: {approval_id}"
    else:
        blocked = hub_blocked_unapproved_action(
            action=f"approval_denied:{approval_id}",
            operator="hub",
            reason=reason or "Approval denied by user.",
        )
        target["blocked_action"] = blocked
        _write_json(approvals_path, existing)
        hub_orb_state(
            orb_state="blocked",
            active_operator="hub",
            active_task=f"Approval denied: {approval_id}",
            active_section="safety",
        )
        event_status = "denied"
        event_message = f"Approval denied and blocked-action recorded: {approval_id}"

    hub_activity_event(
        operator="hub",
        event_type="approval_decision",
        message=event_message,
        status=event_status,
        artifact_path=str(approvals_path).replace("\\", "/"),
    )

    hub_web_sync_data()

    return {
        "status": normalized_decision,
        "approval": target,
        "execution_performed": False,
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }


def hub_approved_execution_gate(
    approval_id: str,
    file_list: str,
    patch_plan: str,
    smoke_test: str,
    rollback_note: str,
) -> dict[str, Any]:
    """Create a local execution-gate record for a previously approved request.

    This is still plan/gate recording only. It does not execute code.
    """
    _ensure_base_state()

    approvals = hub_approval_list(status="approved").get("approvals", [])
    approval = next((item for item in approvals if item.get("id") == approval_id), None)

    if approval is None:
        payload = {
            "status": "blocked",
            "reason": "Approval id is not approved or does not exist.",
            "approval_id": approval_id,
            "execution_performed": False,
            "external_action_taken": False,
            "timestamp": _utc_now(),
        }
        _write_json(HUB_ROOT / "execution-gates" / f"blocked_execution_gate_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json", payload)
        hub_blocked_unapproved_action(
            action=f"execution_gate_without_approved_approval:{approval_id}",
            operator="hub",
            reason=payload["reason"],
        )
        return payload

    missing = []
    if not file_list.strip():
        missing.append("file_list")
    if not patch_plan.strip():
        missing.append("patch_plan")
    if not smoke_test.strip():
        missing.append("smoke_test")
    if not rollback_note.strip():
        missing.append("rollback_note")

    payload = {
        "status": "ready_for_future_execution_review" if not missing else "blocked",
        "approval_id": approval_id,
        "approval": approval,
        "file_list": file_list,
        "patch_plan": patch_plan,
        "smoke_test": smoke_test,
        "rollback_note": rollback_note,
        "missing": missing,
        "secret_scan_required_before_commit": True,
        "execution_performed": False,
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }

    path = HUB_ROOT / "execution-gates" / f"execution_gate_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    _write_json(path, payload)

    hub_activity_event(
        operator="hub",
        event_type="execution_gate",
        message=f"Execution gate record created for approval {approval_id}. No code executed.",
        status=payload["status"],
        artifact_path=str(path).replace("\\", "/"),
    )

    hub_web_sync_data()
    return payload


'''

if "def hub_approval_list(" not in tool:
    tool = tool[:insert_before] + batch6_functions + tool[insert_before:]

# -------------------------------------------------------------------
# 2. Add approval decision endpoint to server handler.
# -------------------------------------------------------------------
if 'self.path != "/api/command-intake"' in tool and '/api/approval-decision' not in tool:
    tool = tool.replace(
        '''            if self.path != "/api/command-intake":
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
''',
        '''            if self.path not in {"/api/command-intake", "/api/approval-decision"}:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"status":"not_found"}')
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8", errors="replace")
                data = parse_qs(raw)

                if self.path == "/api/command-intake":
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
                else:
                    approval_id = (data.get("approval_id", [""])[0] or "").strip()
                    decision = (data.get("decision", [""])[0] or "").strip()
                    reason = (data.get("reason", [""])[0] or "").strip()
                    decided_by = (data.get("decided_by", ["Kyle"])[0] or "Kyle").strip()

                    if not approval_id or not decision:
                        self.send_response(400)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"status":"error","error":"approval_id and decision are required"}')
                        return

                    result = hub_approval_decision(
                        approval_id=approval_id,
                        decision=decision,
                        reason=reason,
                        decided_by=decided_by,
                    )

                hub_web_sync_data()
'''
    )

# -------------------------------------------------------------------
# 3. Patch JS data and approval display.
# -------------------------------------------------------------------
if 'approvals: "data/approvals.json",' not in tool:
    tool = tool.replace(
        '  activity: "data/activity_events.json",\n',
        '  activity: "data/activity_events.json",\n  approvals: "data/approvals.json",\n',
    )

if "function renderApprovals(data)" not in tool:
    tool = tool.replace(
        '''function renderTimeline(data) {''',
        '''function renderApprovals(data) {
  const approvals = data.approvals?.approvals || [];
  const pending = approvals.filter(item => item.status === "pending").slice(-3).reverse();
  if (!pending.length) return "";
  return `
    <h3>Pending Approvals</h3>
    ${pending.map(item => `
      <div class="event">
        <b>${item.id}</b><br>
        <span>${item.request || ""}</span><br>
        <span>Status: ${item.status}</span>
      </div>
    `).join("")}
  `;
}

function renderTimeline(data) {'''
    )

tool = tool.replace(
    '''    ${eventHtml || '<div class="event">No activity events yet.</div>'}
    <h3>Newest Artifacts</h3>''',
    '''    ${renderApprovals(data)}
    ${eventHtml || '<div class="event">No activity events yet.</div>'}
    <h3>Newest Artifacts</h3>'''
)

# -------------------------------------------------------------------
# 4. Update __all__.
# -------------------------------------------------------------------
for name in ["hub_approval_list", "hub_approval_decision", "hub_approved_execution_gate"]:
    if f'"{name}",' not in tool:
        tool = tool.replace('    "hub_self_upgrade_plan",\n', f'    "{name}",\n    "hub_self_upgrade_plan",\n')

tool_path.write_text(tool, encoding="utf-8")

# -------------------------------------------------------------------
# 5. Patch CLI imports.
# -------------------------------------------------------------------
for name in [
    "    hub_approval_decision,\n",
    "    hub_approval_list,\n",
    "    hub_approved_execution_gate,\n",
]:
    if name not in cli:
        cli = cli.replace("    hub_action_routing_plan,\n", "    hub_action_routing_plan,\n" + name)

# -------------------------------------------------------------------
# 6. Add CLI commands before self-upgrade-plan.
# -------------------------------------------------------------------
marker = '@hub.command("self-upgrade-plan")\n@click.argument("request")\n'
commands = r'''@hub.command("approval-list")
@click.option("--status", "approval_status", default="all")
def approval_list(approval_status):
    """List local Hub approvals."""
    _print(hub_approval_list(status=approval_status))


@hub.command("approval-decision")
@click.option("--approval-id", required=True)
@click.option("--decision", required=True)
@click.option("--reason", default="")
@click.option("--decided-by", default="Kyle")
def approval_decision(approval_id, decision, reason, decided_by):
    """Mark a local approval approved or denied. No execution occurs."""
    _print(
        hub_approval_decision(
            approval_id=approval_id,
            decision=decision,
            reason=reason,
            decided_by=decided_by,
        )
    )


@hub.command("approved-execution-gate")
@click.option("--approval-id", required=True)
@click.option("--file-list", required=True)
@click.option("--patch-plan", required=True)
@click.option("--smoke-test", required=True)
@click.option("--rollback-note", required=True)
def approved_execution_gate(approval_id, file_list, patch_plan, smoke_test, rollback_note):
    """Create a local execution gate record for an approved request. No execution occurs."""
    _print(
        hub_approved_execution_gate(
            approval_id=approval_id,
            file_list=file_list,
            patch_plan=patch_plan,
            smoke_test=smoke_test,
            rollback_note=rollback_note,
        )
    )


'''

if '@hub.command("approval-list")' not in cli:
    cli = cli.replace(marker, commands + marker)

cli_path.write_text(cli, encoding="utf-8")

print("[OK] Patched Serena Hub Batch 6 approval workflow")
print("[OK] Added approval-list, approval-decision, and approved-execution-gate")