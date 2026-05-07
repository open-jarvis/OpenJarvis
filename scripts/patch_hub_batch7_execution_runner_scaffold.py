from pathlib import Path

ROOT = Path.cwd()
tool_path = ROOT / "src" / "openjarvis" / "tools" / "serena_hub.py"
cli_path = ROOT / "src" / "openjarvis" / "cli" / "hub_cmd.py"

tool = tool_path.read_text(encoding="utf-8")
cli = cli_path.read_text(encoding="utf-8")

insert_before = tool.index("def hub_approved_execution_gate(")

batch7_functions = '''
def hub_execution_gate_list(status: str = "all") -> dict[str, Any]:
    """List local execution gate records. No execution occurs."""
    gate_root = HUB_ROOT / "execution-gates"
    gates: list[dict[str, Any]] = []

    if gate_root.exists():
        for path in sorted(gate_root.glob("*.json")):
            payload = _safe_read_json(path)
            if isinstance(payload, dict):
                payload["_path"] = str(path).replace("\\\\", "/")
                gates.append(payload)

    if status != "all":
        gates = [gate for gate in gates if gate.get("status") == status]

    return {
        "status": "listed",
        "filter": status,
        "gate_count": len(gates),
        "gates": gates,
        "execution_performed": False,
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }


def _find_execution_gate_for_approval(approval_id: str) -> dict[str, Any] | None:
    gate_root = HUB_ROOT / "execution-gates"
    if not gate_root.exists():
        return None

    candidates: list[dict[str, Any]] = []
    for path in sorted(gate_root.glob("*.json")):
        payload = _safe_read_json(path)
        if isinstance(payload, dict) and payload.get("approval_id") == approval_id:
            payload["_path"] = str(path).replace("\\\\", "/")
            candidates.append(payload)

    if not candidates:
        return None

    return sorted(candidates, key=lambda item: item.get("timestamp", ""), reverse=True)[0]


def hub_execution_runner_plan(
    approval_id: str,
    runner_mode: str = "plan_only",
    require_secret_scan: bool = True,
    require_smoke_test: bool = True,
) -> dict[str, Any]:
    """Create an explicit local runner plan for an approved execution gate.

    This scaffold validates approval/gate state and writes a plan artifact.
    It never patches files, runs shell commands, commits, pushes, or exposes secrets.
    """
    _ensure_base_state()

    approvals = hub_approval_list(status="approved").get("approvals", [])
    approval = next((item for item in approvals if item.get("id") == approval_id), None)

    if approval is None:
        payload = {
            "status": "blocked",
            "reason": "Approval is not approved or does not exist.",
            "approval_id": approval_id,
            "runner_mode": runner_mode,
            "execution_performed": False,
            "external_action_taken": False,
            "timestamp": _utc_now(),
        }
        path = HUB_ROOT / "execution-runner-plans" / f"blocked_runner_plan_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        _write_json(path, payload)
        hub_blocked_unapproved_action(
            action=f"execution_runner_without_approved_approval:{approval_id}",
            operator="hub",
            reason=payload["reason"],
        )
        return payload

    gate = _find_execution_gate_for_approval(approval_id)
    if gate is None or gate.get("status") != "ready_for_future_execution_review":
        payload = {
            "status": "blocked",
            "reason": "No ready execution gate exists for this approval.",
            "approval_id": approval_id,
            "approval": approval,
            "runner_mode": runner_mode,
            "execution_performed": False,
            "external_action_taken": False,
            "timestamp": _utc_now(),
        }
        path = HUB_ROOT / "execution-runner-plans" / f"blocked_runner_plan_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        _write_json(path, payload)
        hub_blocked_unapproved_action(
            action=f"execution_runner_without_ready_gate:{approval_id}",
            operator="hub",
            reason=payload["reason"],
        )
        return payload

    secret_scan_commands = [
        "git grep tracked files for suspicious secret assignments before commit",
        "git grep tracked files for common token formats before commit",
        "do not paste secret findings into chat",
        "rotate any real leaked credential",
    ]

    payload = {
        "status": "runner_plan_ready",
        "approval_id": approval_id,
        "approval": approval,
        "execution_gate": gate,
        "runner_mode": runner_mode,
        "execution_performed": False,
        "external_action_taken": False,
        "browser_trigger_allowed": False,
        "arbitrary_shell_allowed": False,
        "code_patch_allowed_now": False,
        "commit_allowed_now": False,
        "push_allowed_now": False,
        "required_preflight_gates": {
            "approval_is_approved": True,
            "execution_gate_ready": True,
            "secret_scan_required": require_secret_scan,
            "smoke_test_required": require_smoke_test,
            "human_confirms_runner_plan": True,
        },
        "future_manual_steps": [
            "review this runner plan",
            "run local secret scans without pasting secrets into chat",
            "run the declared smoke test",
            "create an explicit patch script if approved",
            "inspect git diff",
            "commit only approved source files",
            "push only after final status check",
        ],
        "secret_scan_commands": secret_scan_commands if require_secret_scan else [],
        "smoke_test_command": gate.get("smoke_test") if require_smoke_test else None,
        "file_list": gate.get("file_list"),
        "patch_plan": gate.get("patch_plan"),
        "rollback_note": gate.get("rollback_note"),
        "timestamp": _utc_now(),
    }

    path = HUB_ROOT / "execution-runner-plans" / f"execution_runner_plan_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    _write_json(path, payload)

    hub_orb_state(
        orb_state="approval",
        active_operator="hub",
        active_task=f"Execution runner plan ready for review: {approval_id}",
        active_section="safety",
    )

    hub_activity_event(
        operator="hub",
        event_type="execution_runner_plan",
        message=f"Execution runner plan created for approval {approval_id}. No execution performed.",
        status="runner_plan_ready",
        artifact_path=str(path).replace("\\\\", "/"),
    )

    hub_web_sync_data()
    return payload


'''

if "def hub_execution_runner_plan(" not in tool:
    tool = tool[:insert_before] + batch7_functions + tool[insert_before:]

for name in ["hub_execution_gate_list", "hub_execution_runner_plan"]:
    if f'"{name}",' not in tool:
        tool = tool.replace('    "hub_approved_execution_gate",\n', f'    "{name}",\n    "hub_approved_execution_gate",\n')

tool_path.write_text(tool, encoding="utf-8")

for name in [
    "    hub_execution_gate_list,\n",
    "    hub_execution_runner_plan,\n",
]:
    if name not in cli:
        cli = cli.replace("    hub_env_check,\n", "    hub_env_check,\n" + name)

marker = '@hub.command("approved-execution-gate")\n@click.option("--approval-id", required=True)\n'
commands = '''@hub.command("execution-gate-list")
@click.option("--status", "gate_status", default="all")
def execution_gate_list(gate_status):
    """List local execution gate records. No execution occurs."""
    _print(hub_execution_gate_list(status=gate_status))


@hub.command("execution-runner-plan")
@click.option("--approval-id", required=True)
@click.option("--runner-mode", default="plan_only")
@click.option("--no-secret-scan", is_flag=True)
@click.option("--no-smoke-test", is_flag=True)
def execution_runner_plan(approval_id, runner_mode, no_secret_scan, no_smoke_test):
    """Create explicit runner plan for approved execution gate. No execution occurs."""
    _print(
        hub_execution_runner_plan(
            approval_id=approval_id,
            runner_mode=runner_mode,
            require_secret_scan=not no_secret_scan,
            require_smoke_test=not no_smoke_test,
        )
    )


'''

if '@hub.command("execution-gate-list")' not in cli:
    cli = cli.replace(marker, commands + marker)

cli_path.write_text(cli, encoding="utf-8")

print("[OK] Patched Serena Hub Batch 7 execution runner scaffold")
print("[OK] Added execution-gate-list and execution-runner-plan")