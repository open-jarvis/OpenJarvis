"""Validate the fixed metadata proof for the final local product pilot.

The real pilot remains centrally orchestrated through OpenJarvis' public APIs.
This collector intentionally does not implement another workflow engine or
accept arbitrary HTTP steps.  It validates one closed evidence schema, checks
the current Vault and cleanup state, and emits the payload-safe
``final-pilot-report.json``.
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import json
import os
import re
import socket
import stat
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlsplit

from openjarvis.migration.vault_schema_pilot import build_manifest

SCHEMA_VERSION = "1.0"
FINAL_RUNTIME_MARKER = "OPENJARVIS-FINAL-RUNTIME"
FINAL_WEBSITE_WORKSPACE_ID = "phase8-final-website-pilot"
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|authentication|token|cookie|secret|credential|password|api[_-]?key|content|body|payload|query|text)",
    re.IGNORECASE,
)

_TOP_KEYS = {
    "health",
    "learning",
    "offline_guard",
    "origin",
    "restart",
    "retrieval",
    "schema_version",
    "tool_action",
    "vault_stability",
    "website",
}
_HEALTH_KEYS = {
    "backend",
    "learning_status",
    "memory_fts_documents",
    "memory_note_count",
    "memory_parser_errors",
    "memory_schema_valid",
    "memory_type_supported",
    "pid",
    "runtime",
    "runtime_marker",
    "skill_count",
    "skill_registry_readable",
    "status",
}
_RETRIEVAL_ROLES = {
    "explicit_system_policy",
    "explicit_system_profile",
    "normal",
    "normal_authority_exclusion",
    "project_exact",
    "project_missing",
    "project_wrong",
    "review_memory_proposal",
    "structure_category",
    "structure_navigation",
}
_RETRIEVAL_FIELDS = {
    "authority_classes",
    "note_types",
    "retrieval_classes",
    "selected_count",
}


class PilotEvidenceError(RuntimeError):
    """The supplied final pilot evidence is incomplete or unsafe."""


class OfflineSocketViolation(PilotEvidenceError):
    """A non-loopback socket target was attempted."""


def _is_reparse(path: Path) -> bool:
    info = path.lstat()
    return path.is_symlink() or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _root(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise PilotEvidenceError(f"{label} must be absolute")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PilotEvidenceError(f"{label} does not exist") from exc
    if not resolved.is_dir() or _is_reparse(resolved):
        raise PilotEvidenceError(f"{label} must be a normal directory")
    return resolved


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    try:
        loopback = bool(parsed.hostname) and (
            parsed.hostname.casefold() == "localhost"
            or ipaddress.ip_address(parsed.hostname).is_loopback
        )
    except ValueError:
        loopback = False
    if (
        parsed.scheme != "http"
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not loopback
    ):
        raise PilotEvidenceError("origin must be an explicit loopback HTTP origin")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"http://{host}:{parsed.port}"


def _address_is_loopback(address: Any) -> bool:
    if not isinstance(address, tuple) or not address:
        return False
    try:
        return ipaddress.ip_address(str(address[0]).split("%", 1)[0]).is_loopback
    except ValueError:
        return str(address[0]).casefold() == "localhost"


@contextlib.contextmanager
def loopback_socket_guard() -> Iterator[None]:
    """Block outbound socket connects outside loopback during central probes."""

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create = socket.create_connection

    def connect(sock: socket.socket, address: Any) -> Any:
        if not _address_is_loopback(address):
            raise OfflineSocketViolation("non-loopback socket blocked")
        return original_connect(sock, address)

    def connect_ex(sock: socket.socket, address: Any) -> int:
        if not _address_is_loopback(address):
            raise OfflineSocketViolation("non-loopback socket blocked")
        return original_connect_ex(sock, address)

    def create_connection(
        address: Any,
        timeout: float | object = socket._GLOBAL_DEFAULT_TIMEOUT,
        source_address: Any = None,
        **kwargs: Any,
    ) -> socket.socket:
        if not _address_is_loopback(address):
            raise OfflineSocketViolation("non-loopback socket blocked")
        return original_create(address, timeout, source_address, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.create_connection = create_connection
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex
        socket.create_connection = original_create


def _exact(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PilotEvidenceError(f"{label} evidence schema differs")
    return value


def _true(value: Mapping[str, Any], fields: set[str], label: str) -> None:
    if any(value[field] is not True for field in fields):
        raise PilotEvidenceError(f"{label} contains a failed gate")


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise PilotEvidenceError(f"{label} identifier is invalid")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise PilotEvidenceError(f"{label} digest is invalid")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not _ID.fullmatch(item) for item in value
    ):
        raise PilotEvidenceError(f"{label} is not a metadata-safe string list")
    return sorted(set(value))


def _health(value: Any, label: str) -> dict[str, Any]:
    health = _exact(value, _HEALTH_KEYS, label)
    expected = {
        "backend": "python_sdk",
        "learning_status": "healthy",
        "memory_fts_documents": 46,
        "memory_note_count": 46,
        "memory_parser_errors": 0,
        "memory_schema_valid": 46,
        "memory_type_supported": 46,
        "runtime": "phase8-final",
        "runtime_marker": FINAL_RUNTIME_MARKER,
        "skill_registry_readable": True,
        "status": "ready",
    }
    if any(health[key] != expected_value for key, expected_value in expected.items()):
        raise PilotEvidenceError(f"{label} is not final-runtime healthy")
    if (
        not isinstance(health["pid"], int)
        or isinstance(health["pid"], bool)
        or health["pid"] < 1
        or not isinstance(health["skill_count"], int)
        or health["skill_count"] < 0
    ):
        raise PilotEvidenceError(f"{label} process or skill count is invalid")
    return dict(health)


def _retrieval(value: Any) -> dict[str, Any]:
    retrieval = _exact(value, _RETRIEVAL_ROLES, "retrieval")
    result: dict[str, Any] = {}
    for role, raw in retrieval.items():
        item = _exact(raw, _RETRIEVAL_FIELDS, f"retrieval.{role}")
        count = item["selected_count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise PilotEvidenceError(f"retrieval.{role} count is invalid")
        classes = _string_list(item["retrieval_classes"], role)
        note_types = _string_list(item["note_types"], role)
        authorities = _string_list(item["authority_classes"], role)
        gates = {
            "normal": count > 0
            and classes == ["normal"]
            and authorities in ([], ["none"]),
            "project_exact": count > 0
            and "project_profile" in note_types
            and set(classes) <= {"normal", "project_scoped"},
            "project_wrong": count == 0,
            "project_missing": count == 0,
            "review_memory_proposal": count > 0
            and "memory_proposal" in note_types
            and classes == ["review_only"],
            "structure_category": count > 0
            and "category" in note_types
            and classes == ["taxonomy_only"],
            "structure_navigation": count > 0
            and "navigation" in note_types
            and classes == ["navigation_only"],
            "explicit_system_policy": count > 0
            and "system_policy" in note_types
            and classes == ["explicit_review_only"],
            "explicit_system_profile": count > 0
            and "system_profile" in note_types
            and classes == ["explicit_review_only"],
            "normal_authority_exclusion": "prohibited_runtime_authority"
            not in authorities
            and "explicit_review_only" not in classes,
        }
        if gates[role] is not True:
            raise PilotEvidenceError(f"retrieval.{role} boundary failed")
        result[role] = {
            "selected_count": count,
            "retrieval_classes": classes,
            "note_types": note_types,
            "authority_classes": authorities,
        }
    return result


def _tool(value: Any) -> dict[str, Any]:
    booleans = {
        "allow_once",
        "apply",
        "cleanup",
        "policy",
        "preview",
        "rollback",
        "timeline",
        "verification",
        "workspace_removed",
    }
    tool = _exact(
        value,
        booleans | {"action_id", "timeline_events", "verification_status"},
        "ToolAction",
    )
    _true(tool, booleans, "ToolAction")
    if (
        tool["verification_status"] != "passed"
        or not isinstance(tool["timeline_events"], int)
        or tool["timeline_events"] < 1
    ):
        raise PilotEvidenceError("ToolAction verification or timeline failed")
    return {
        **{key: True for key in sorted(booleans)},
        "action_id": _identifier(tool["action_id"], "ToolAction"),
        "timeline_events": tool["timeline_events"],
        "verification_status": "passed",
    }


def _website(value: Any) -> dict[str, Any]:
    booleans = {
        "apply",
        "artifact_manifest",
        "cleanup",
        "no_javascript",
        "no_network",
        "no_publish",
        "preview",
        "restart_readback",
        "rollback",
        "rollback_byte_identical",
        "verification",
    }
    website = _exact(
        value,
        booleans | {"execution_id", "manifest_sha256", "workspace_id"},
        "website",
    )
    _true(website, booleans, "website")
    if website["workspace_id"] != FINAL_WEBSITE_WORKSPACE_ID:
        raise PilotEvidenceError("website workspace identity differs")
    return {
        **{key: True for key in sorted(booleans)},
        "workspace_id": FINAL_WEBSITE_WORKSPACE_ID,
        "execution_id": _identifier(website["execution_id"], "website"),
        "manifest_sha256": _digest(website["manifest_sha256"], "website"),
    }


def _learning(value: Any) -> dict[str, Any]:
    fields = {
        "activation_count_delta",
        "candidate_states",
        "evaluation_id",
        "feedback_revisions",
        "learning_readback",
        "productive_route_changed",
        "promotion_count_delta",
        "shadow_mode",
        "trace_evaluation",
    }
    learning = _exact(value, fields, "learning")
    states = _string_list(learning["candidate_states"], "candidate states")
    if (
        learning["trace_evaluation"] is not True
        or learning["learning_readback"] is not True
        or not states
        or not set(states) <= {"proposed", "quarantined"}
        or learning["promotion_count_delta"] != 0
        or learning["activation_count_delta"] != 0
        or learning["shadow_mode"] is not True
        or learning["productive_route_changed"] is not False
        or not isinstance(learning["feedback_revisions"], int)
        or learning["feedback_revisions"] < 2
    ):
        raise PilotEvidenceError("learning authority boundary failed")
    return {
        "trace_evaluation": True,
        "evaluation_id": _identifier(learning["evaluation_id"], "learning"),
        "candidate_states": states,
        "promotion_count_delta": 0,
        "activation_count_delta": 0,
        "shadow_mode": True,
        "productive_route_changed": False,
        "feedback_revisions": learning["feedback_revisions"],
        "learning_readback": True,
    }


def _safe(value: Any, private_roots: Sequence[Path]) -> None:
    private = tuple(str(path).casefold() for path in private_roots)

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if _SENSITIVE_KEY.search(str(key)):
                    raise PilotEvidenceError("evidence contains a sensitive field")
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
        elif isinstance(item, str):
            lowered = item.casefold()
            if _WINDOWS_PATH.match(item) or any(root in lowered for root in private):
                raise PilotEvidenceError("evidence contains a private path")

    visit(value)


def validate_final_pilot_evidence(
    *,
    evidence: Mapping[str, Any],
    base_url: str,
    runtime_root: Path,
    vault_root: Path,
) -> dict[str, Any]:
    """Validate fixed per-gate metadata produced by the central real pilot."""

    runtime = _root(runtime_root, "runtime root")
    vault = _root(vault_root, "vault root")
    if runtime == vault or _inside(runtime, vault) or _inside(vault, runtime):
        raise PilotEvidenceError("runtime and vault roots must be disjoint")
    origin = _origin(base_url)
    proof = _exact(evidence, _TOP_KEYS, "pilot")
    if proof["schema_version"] != SCHEMA_VERSION or proof["origin"] != origin:
        raise PilotEvidenceError("pilot identity or origin differs")
    before_health = _health(
        _exact(proof["health"], {"after", "before"}, "health")["before"],
        "health.before",
    )
    after_health = _health(proof["health"]["after"], "health.after")
    if before_health["pid"] == after_health["pid"]:
        raise PilotEvidenceError("restart retained the original process")
    restart = _exact(
        proof["restart"],
        {"calls", "controlled_shutdown", "health_after_restart", "new_process"},
        "restart",
    )
    if restart != {
        "calls": 1,
        "controlled_shutdown": True,
        "health_after_restart": True,
        "new_process": True,
    }:
        raise PilotEvidenceError("controlled restart evidence failed")
    offline = _exact(
        proof["offline_guard"],
        {"codex_live_calls", "enabled", "external_calls", "non_loopback_denied"},
        "offline guard",
    )
    if offline != {
        "codex_live_calls": 0,
        "enabled": True,
        "external_calls": 0,
        "non_loopback_denied": True,
    }:
        raise PilotEvidenceError("offline guard evidence failed")
    vault_state = _exact(
        proof["vault_stability"],
        {"after_manifest_sha256", "before_manifest_sha256", "file_count", "stable"},
        "vault stability",
    )
    before_digest = _digest(vault_state["before_manifest_sha256"], "vault before")
    after_digest = _digest(vault_state["after_manifest_sha256"], "vault after")
    current_manifest, current_digest = build_manifest(vault)
    if (
        vault_state["stable"] is not True
        or before_digest != after_digest
        or after_digest != current_digest
        or vault_state["file_count"] != 59
        or len(current_manifest) != 59
    ):
        raise PilotEvidenceError("vault changed during the product pilot")
    tool = _tool(proof["tool_action"])
    website = _website(proof["website"])
    learning = _learning(proof["learning"])
    retrieval = _retrieval(proof["retrieval"])
    cleanup_paths = (
        runtime / "phase8-final-product-pilot-workspace",
        runtime / "website-staging" / "workspaces" / FINAL_WEBSITE_WORKSPACE_ID,
        runtime
        / "website-staging"
        / "state"
        / "workspaces"
        / f"{FINAL_WEBSITE_WORKSPACE_ID}.json",
    )
    if any(path.exists() or path.is_symlink() for path in cleanup_paths):
        raise PilotEvidenceError("synthetic pilot workspace cleanup is incomplete")
    report = {
        "schema_version": SCHEMA_VERSION,
        "pilot_id": "phase8-final-product-pilot",
        "status": "passed",
        "origin": origin,
        "health": {"before": before_health, "after": after_health},
        "retrieval": retrieval,
        "tool_action": tool,
        "website": website,
        "learning": learning,
        "restart": dict(restart),
        "offline_guard": dict(offline),
        "vault_stability": {
            "before_manifest_sha256": before_digest,
            "after_manifest_sha256": after_digest,
            "file_count": 59,
            "stable": True,
        },
        "cleanup": {
            "tool_workspace_removed": True,
            "website_workspace_removed": True,
            "website_state_removed": True,
        },
    }
    _safe(report, (runtime, vault))
    return report


def write_report_atomic(
    path: Path, report: Mapping[str, Any], vault_root: Path
) -> None:
    target = path.resolve(strict=False)
    vault = vault_root.resolve(strict=True)
    if target == vault or _inside(target, vault):
        raise PilotEvidenceError("report target is inside the vault")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    payload = (
        json.dumps(report, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PilotEvidenceError("evidence is not readable UTF-8 JSON") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--vault-root", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = validate_final_pilot_evidence(
            evidence=_load(args.evidence.resolve(strict=True)),
            base_url=args.base_url,
            runtime_root=args.runtime_root,
            vault_root=args.vault_root,
        )
        write_report_atomic(args.output, report, args.vault_root)
    except (OSError, PilotEvidenceError) as exc:
        print(f"phase8-final-product-pilot: blocked ({type(exc).__name__})")
        return 1
    print("phase8-final-product-pilot: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
