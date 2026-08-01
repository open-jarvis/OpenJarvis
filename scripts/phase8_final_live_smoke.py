"""One-shot Phase-8 Codex SDK smoke with a durable pre-call claim.

Default execution runs only the hermetic fake preflight.  The live path needs
the explicit ``--execute-live-once`` switch and can never reuse a proof path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from openjarvis.codex.redaction import sanitized_codex_environment
from openjarvis.learning.evaluation.classifier import TraceClassifier
from openjarvis.learning.evaluation.models import (
    ApprovalState,
    BudgetState,
    EvidenceState,
    ExternalEffectState,
    PolicyResult,
    VerificationState,
)
from openjarvis.learning.evaluation.normalization import snapshot_from_runtime
from openjarvis.tasks import ExecutionLane, TaskOutcome, TaskRecord, TaskStatus

PROMPT = "Return exactly: JARVIS-FINAL-LIVE-OK"
MARKER = "JARVIS-FINAL-LIVE-OK"
BACKEND = "openai-codex-python-sdk"
_ALLOWED_TEXT_ITEM_TYPES = frozenset(
    {"userMessage", "agentMessage", "reasoning", "plan"}
)
_PROHIBITED_ITEM_TYPES = frozenset(
    {
        "commandExecution",
        "fileChange",
        "mcpToolCall",
        "dynamicToolCall",
        "collabAgentToolCall",
        "subAgentActivity",
        "webSearch",
        "imageView",
        "imageGeneration",
        "sleep",
    }
)


@dataclass(frozen=True, slots=True)
class AttemptIdentity:
    task_id: str
    session_id: str
    correlation_id: str
    trace_id: str
    timestamp: datetime

    @classmethod
    def create(cls) -> "AttemptIdentity":
        suffix = uuid.uuid4().hex
        return cls(
            task_id=f"task_{suffix}",
            session_id=f"session_{uuid.uuid4().hex}",
            correlation_id=f"correlation_{uuid.uuid4().hex}",
            trace_id=f"trace_{uuid.uuid4().hex}",
            timestamp=datetime.now(timezone.utc),
        )


def _evaluation(identity: AttemptIdentity, *, status: str):
    success = status == "passed"
    failed = status == "failed_no_retry"
    now = identity.timestamp.isoformat()
    task = TaskRecord(
        task_id=identity.task_id,
        session_id=identity.session_id,
        correlation_id=identity.correlation_id,
        description="redacted final live marker check",
        status=(
            TaskStatus.DONE
            if success
            else TaskStatus.FAILED
            if failed
            else TaskStatus.PENDING
        ),
        outcome=(
            TaskOutcome.COMPLETED if success else TaskOutcome.FAILED if failed else None
        ),
        execution_lane=ExecutionLane.MODEL,
        backend="codex",
        risk_level=0,
        created_at=now,
        updated_at=now,
        version=1,
        result=MARKER if success else "",
    )
    snapshot = snapshot_from_runtime(
        task,
        trace_id=identity.trace_id,
        task_type="phase8_final_live_smoke",
        requested_goal="verify exact final marker",
        verification_state=(
            VerificationState.PASSED
            if success
            else VerificationState.FAILED
            if failed
            else VerificationState.PENDING
        ),
        approval_state=ApprovalState.NOT_REQUIRED,
        policy_result=PolicyResult.NOT_REQUIRED,
        evidence_state=EvidenceState.SUFFICIENT if success else EvidenceState.UNKNOWN,
        budget_state=BudgetState.WITHIN_LIMITS if success else BudgetState.UNKNOWN,
        external_effect_state=ExternalEffectState.NONE,
        model_claimed_success=success,
    )
    return TraceClassifier().evaluate(snapshot)


def _proof(identity: AttemptIdentity, *, status: str) -> dict[str, Any]:
    return {
        "task_id": identity.task_id,
        "session_id": identity.session_id,
        "time": identity.timestamp.isoformat(),
        "backend": BACKEND,
        "status": status,
        "marker": MARKER,
        "trace_evaluation": _evaluation(identity, status=status).model_dump(
            mode="json"
        ),
    }


def _exclusive_claim(path: Path, identity: AttemptIdentity) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            _proof(identity, status="claimed_before_sdk_call"),
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("durable claim write made no progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace_proof(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    try:
        os.chmod(temporary, 0o600)
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _item_type(item: Any) -> str:
    value = getattr(item, "root", item)
    for key in ("type", "item_type"):
        item_type = getattr(value, key, None)
        if item_type:
            return str(getattr(item_type, "value", item_type))
    return type(value).__name__


def _validate_result(result: Any) -> None:
    if result.final_response != MARKER:
        raise RuntimeError("Codex did not return the exact final marker")
    item_types = {_item_type(item) for item in result.items}
    if item_types.intersection(_PROHIBITED_ITEM_TYPES):
        raise RuntimeError("Codex returned a prohibited tool, file, or external item")
    if not item_types.issubset(_ALLOWED_TEXT_ITEM_TYPES):
        raise RuntimeError("Codex returned an unexpected non-textual item")


async def _sdk_turn(
    cwd: Path, client_factory: Callable[[Any], Any] | None = None
) -> None:
    from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox

    config = CodexConfig(
        cwd=str(cwd),
        env=sanitized_codex_environment(),
        client_name="openjarvis-phase8-final-smoke",
        client_title="OpenJarvis Phase 8 Final Live Smoke",
        experimental_api=False,
    )
    factory = client_factory or AsyncCodex
    client_context = factory(config)
    async with client_context as codex:
        account = await codex.account(refresh_token=False)
        account_data = account.model_dump(mode="json")
        if account_data.get("account", {}).get("type") != "chatgpt":
            raise RuntimeError("existing ChatGPT authentication is required")
        thread = await codex.thread_start(
            approval_mode=ApprovalMode.deny_all,
            cwd=str(cwd),
            developer_instructions=(
                "Return only the exact requested marker. Do not use tools, files, "
                "commands, browsing, external context, or external actions."
            ),
            ephemeral=True,
            sandbox=Sandbox.read_only,
        )
        result = await thread.run(
            PROMPT,
            approval_mode=ApprovalMode.deny_all,
            cwd=str(cwd),
            sandbox=Sandbox.read_only,
        )
    _validate_result(result)


async def execute_once(
    proof_path: Path,
    *,
    client_factory: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    """Claim durably, then make exactly one SDK turn; never remove the claim."""

    repository = Path(__file__).resolve().parents[1]
    if proof_path.expanduser().resolve(strict=False).is_relative_to(repository):
        raise ValueError("live proof must be stored outside the repository")
    identity = AttemptIdentity.create()
    _exclusive_claim(proof_path, identity)
    try:
        with tempfile.TemporaryDirectory(prefix="openjarvis-final-live-") as raw:
            cwd = Path(raw)
            before = tuple(cwd.iterdir())
            await _sdk_turn(cwd, client_factory)
            after = tuple(cwd.iterdir())
            if before != after or after:
                raise RuntimeError("the empty read-only SDK workspace changed")
        payload = _proof(identity, status="passed")
        _replace_proof(proof_path, payload)
        return payload
    except Exception:
        _replace_proof(proof_path, _proof(identity, status="failed_no_retry"))
        raise


class _FakeAccount:
    def model_dump(self, **_kwargs: Any) -> dict[str, Any]:
        return {"account": {"type": "chatgpt"}}


class _FakeResult:
    final_response = MARKER
    items: tuple[Any, ...] = ()


class _FakeThread:
    def __init__(self, owner: "_FakeCodex") -> None:
        self.owner = owner

    async def run(self, prompt: str, **kwargs: Any) -> _FakeResult:
        if (
            prompt != PROMPT
            or getattr(kwargs["approval_mode"], "value", "") != "deny_all"
        ):
            raise AssertionError("fake preflight policy mismatch")
        self.owner.turns += 1
        return _FakeResult()


class _FakeCodex:
    def __init__(self, _config: Any) -> None:
        self.turns = 0

    async def __aenter__(self) -> "_FakeCodex":
        return self

    async def __aexit__(self, exc_type: Any, *_args: Any) -> None:
        if exc_type is None and self.turns != 1:
            raise AssertionError("fake preflight did not execute exactly one turn")

    async def account(self, *, refresh_token: bool) -> _FakeAccount:
        if refresh_token:
            raise AssertionError("token refresh is forbidden")
        return _FakeAccount()

    async def thread_start(self, **kwargs: Any) -> _FakeThread:
        if not kwargs.get("ephemeral"):
            raise AssertionError("preflight thread must be ephemeral")
        return _FakeThread(self)


async def fake_preflight() -> None:
    with tempfile.TemporaryDirectory(prefix="openjarvis-final-preflight-") as raw:
        proof = Path(raw) / "proof.json"
        payload = await execute_once(proof, client_factory=_FakeCodex)
        if payload["status"] != "passed" or not proof.is_file():
            raise AssertionError("fake preflight proof failed")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-shot final Codex live smoke")
    parser.add_argument("--proof", type=Path)
    parser.add_argument("--execute-live-once", action="store_true")
    args = parser.parse_args(argv)
    asyncio.run(fake_preflight())
    if not args.execute_live_once:
        print("Hermetic fake preflight passed; no live turn was started.")
        return 0
    if args.proof is None:
        parser.error("--proof is required with --execute-live-once")
    payload = asyncio.run(execute_once(args.proof))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
