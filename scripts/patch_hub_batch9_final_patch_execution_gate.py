from pathlib import Path

ROOT = Path.cwd()
tool_path = ROOT / "src" / "openjarvis" / "tools" / "serena_hub.py"
cli_path = ROOT / "src" / "openjarvis" / "cli" / "hub_cmd.py"

tool = tool_path.read_text(encoding="utf-8")
cli = cli_path.read_text(encoding="utf-8")

insert_before = tool.index("def hub_patch_prep(")

batch9_functions = r'''
def _find_latest_patch_prep_for_approval(approval_id: str) -> dict[str, Any] | None:
    prep_root = HUB_ROOT / "patch-prep"
    if not prep_root.exists():
        return None

    candidates: list[dict[str, Any]] = []
    for path in sorted(prep_root.glob("patch_prep_*.json")):
        payload = _safe_read_json(path)
        if isinstance(payload, dict) and payload.get("approval_id") == approval_id:
            payload["_path"] = str(path).replace("\\", "/")
            candidates.append(payload)

    if not candidates:
        return None

    return sorted(candidates, key=lambda item: item.get("timestamp", ""), reverse=True)[0]


def hub_final_patch_execution_gate(
    approval_id: str,
    final_confirmation: bool = False,
    smoke_test_command: str = "",
    secret_scan_status: str = "not_run",
    execute: bool = False,
) -> dict[str, Any]:
    """Create the final CLI-only patch execution gate.

    This command may execute only a generated draft patch script if all gates pass.
    The default behavior remains no execution. Browser execution is never allowed.
    """
    _ensure_base_state()

    patch_prep = _find_latest_patch_prep_for_approval(approval_id)
    if patch_prep is None or patch_prep.get("status") != "patch_prep_ready":
        payload = {
            "status": "blocked",
            "reason": "No ready patch-prep artifact exists for this approval.",
            "approval_id": approval_id,
            "execution_performed": False,
            "external_action_taken": False,
            "timestamp": _utc_now(),
        }
        path = HUB_ROOT / "final-execution-gates" / f"blocked_final_gate_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        _write_json(path, payload)
        hub_blocked_unapproved_action(
            action=f"final_patch_execution_without_patch_prep:{approval_id}",
            operator="hub",
            reason=payload["reason"],
        )
        return payload

    draft_path = Path(str(patch_prep.get("draft_patch_script", "")))
    gates = {
        "patch_prep_ready": patch_prep.get("status") == "patch_prep_ready",
        "draft_script_exists": draft_path.exists(),
        "draft_only": bool(patch_prep.get("draft_only")),
        "source_files_not_modified_by_prep": patch_prep.get("source_files_modified") is False,
        "patch_script_not_previously_executed": patch_prep.get("patch_script_executed") is False,
        "final_confirmation": bool(final_confirmation),
        "secret_scan_passed": str(secret_scan_status).strip().lower() == "passed",
        "smoke_test_declared": bool(str(smoke_test_command).strip()),
        "browser_trigger_allowed": False,
    }

    missing = [name for name, ok in gates.items() if not ok and name != "browser_trigger_allowed"]

    status = "ready_for_cli_execution" if not missing else "blocked"

    payload = {
        "status": status,
        "approval_id": approval_id,
        "patch_prep": patch_prep,
        "draft_patch_script": str(draft_path).replace("\\", "/"),
        "gates": gates,
        "missing": missing,
        "final_confirmation": final_confirmation,
        "secret_scan_status": secret_scan_status,
        "smoke_test_command": smoke_test_command,
        "execute_requested": execute,
        "browser_trigger_allowed": False,
        "arbitrary_shell_allowed": False,
        "external_action_taken": False,
        "execution_performed": False,
        "timestamp": _utc_now(),
    }

    if status != "ready_for_cli_execution":
        path = HUB_ROOT / "final-execution-gates" / f"blocked_final_gate_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        _write_json(path, payload)
        hub_blocked_unapproved_action(
            action=f"final_patch_execution_gate_blocked:{approval_id}",
            operator="hub",
            reason=f"Final patch execution gate blocked. Missing: {', '.join(missing)}",
        )
        return payload

    if not execute:
        payload["status"] = "ready_but_not_executed"
        payload["reason"] = "Final gate is ready, but execute flag was not provided."
        path = HUB_ROOT / "final-execution-gates" / f"ready_final_gate_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        _write_json(path, payload)
        hub_activity_event(
            operator="hub",
            event_type="final_patch_execution_gate",
            message=f"Final patch execution gate ready but not executed for approval {approval_id}.",
            status="ready_but_not_executed",
            artifact_path=str(path).replace("\\", "/"),
        )
        hub_web_sync_data()
        return payload

    # Final explicit CLI-only execution of the generated draft patch script.
    # This intentionally runs only the specific draft script path from patch-prep.
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(draft_path)],
        cwd=str(Path.cwd()),
        text=True,
        capture_output=True,
        check=False,
    )

    payload["execution_performed"] = True
    payload["patch_script_executed"] = True
    payload["returncode"] = result.returncode
    payload["stdout"] = result.stdout[-4000:]
    payload["stderr"] = result.stderr[-4000:]
    payload["status"] = "executed" if result.returncode == 0 else "execution_failed"
    payload["source_files_expected_to_change"] = False

    path = HUB_ROOT / "final-execution-gates" / f"final_execution_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    _write_json(path, payload)

    hub_activity_event(
        operator="hub",
        event_type="final_patch_execution_gate",
        message=f"Final CLI-only patch execution gate completed for approval {approval_id}.",
        status=payload["status"],
        artifact_path=str(path).replace("\\", "/"),
    )

    hub_orb_state(
        orb_state="completed" if result.returncode == 0 else "blocked",
        active_operator="hub",
        active_task=f"Final patch execution gate {payload['status']}: {approval_id}",
        active_section="safety",
    )

    hub_web_sync_data()
    return payload


def hub_final_execution_gate_list(status: str = "all") -> dict[str, Any]:
    """List final execution gate artifacts."""
    root = HUB_ROOT / "final-execution-gates"
    items: list[dict[str, Any]] = []

    if root.exists():
        for path in sorted(root.glob("*.json")):
            payload = _safe_read_json(path)
            if isinstance(payload, dict):
                payload["_path"] = str(path).replace("\\", "/")
                items.append(payload)

    if status != "all":
        items = [item for item in items if item.get("status") == status]

    return {
        "status": "listed",
        "filter": status,
        "final_gate_count": len(items),
        "items": items,
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }


'''

if "def hub_final_patch_execution_gate(" not in tool:
    tool = tool[:insert_before] + batch9_functions + tool[insert_before:]

for name in ["hub_final_patch_execution_gate", "hub_final_execution_gate_list"]:
    if f'"{name}",' not in tool:
        tool = tool.replace('    "hub_patch_prep",\n', f'    "{name}",\n    "hub_patch_prep",\n')

tool_path.write_text(tool, encoding="utf-8")

for name in [
    "    hub_final_execution_gate_list,\n",
    "    hub_final_patch_execution_gate,\n",
]:
    if name not in cli:
        cli = cli.replace("    hub_finance_rollup,\n", "    hub_finance_rollup,\n" + name)

marker = '@hub.command("patch-prep")\n@click.option("--approval-id", required=True)\n'
commands = '''@hub.command("final-patch-execution-gate")
@click.option("--approval-id", required=True)
@click.option("--final-confirmation", is_flag=True)
@click.option("--secret-scan-status", default="not_run")
@click.option("--smoke-test-command", default="")
@click.option("--execute", is_flag=True)
def final_patch_execution_gate(approval_id, final_confirmation, secret_scan_status, smoke_test_command, execute):
    """Validate final CLI-only patch execution gate. Executes only with explicit flags."""
    _print(
        hub_final_patch_execution_gate(
            approval_id=approval_id,
            final_confirmation=final_confirmation,
            secret_scan_status=secret_scan_status,
            smoke_test_command=smoke_test_command,
            execute=execute,
        )
    )


@hub.command("final-execution-gate-list")
@click.option("--status", "gate_status", default="all")
def final_execution_gate_list(gate_status):
    """List final execution gate artifacts."""
    _print(hub_final_execution_gate_list(status=gate_status))


'''

if '@hub.command("final-patch-execution-gate")' not in cli:
    cli = cli.replace(marker, commands + marker)

cli_path.write_text(cli, encoding="utf-8")

print("[OK] Patched Serena Hub Batch 9 final patch execution gate")
print("[OK] Added final-patch-execution-gate and final-execution-gate-list")