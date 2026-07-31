"""Deterministic quarantine rules for candidate metadata."""

from __future__ import annotations

import base64
import binascii
import re

from openjarvis.learning.candidates.models import (
    CandidateContent,
    LearningCandidate,
    QuarantineReason,
    SecuritySignal,
    SkillCandidateContent,
    StructuredCandidateRequest,
    UntrustedSourceKind,
)
from openjarvis.learning.evaluation.models import (
    ConfidenceBasis,
    EvidenceState,
    TraceEvaluation,
)

_PROMPT_INJECTION_PATTERNS = (
    re.compile(
        r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+"
        r"(?:instructions?|prompts?|rules?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdisregard\s+(?:all\s+)?(?:previous|prior|your)\s+"
        r"(?:instructions?|rules?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"<\|(?:im_start|im_end|system|assistant)\|>", re.IGNORECASE),
    re.compile(r"```(?:system|assistant)\b", re.IGNORECASE),
)
_FORBIDDEN_CODE_PATTERNS = (
    re.compile(r"\beval\s*\(", re.IGNORECASE),
    re.compile(r"\bexec\s*\(", re.IGNORECASE),
    re.compile(r"\bpickle\s*\.\s*(?:load|loads)\s*\(", re.IGNORECASE),
    re.compile(r"\b__import__\s*\(", re.IGNORECASE),
    re.compile(r"\b(?:powershell|cmd\.exe|bash|sh)\s+(?:-|/)", re.IGNORECASE),
    re.compile(r"\b(?:curl|wget)\s+", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
    re.compile(r"\bremove-item\s+", re.IGNORECASE),
)
_APPROVAL_PATTERNS = (
    re.compile(r"\balways\s+allow\b", re.IGNORECASE),
    re.compile(r"\bauto(?:matically)?[- ]?approve\b", re.IGNORECASE),
    re.compile(r"\bgrant\s+(?:the\s+)?approval\b", re.IGNORECASE),
    re.compile(r"\bapprove\s+(?:all|this)\b", re.IGNORECASE),
)
_PRIVATE_PAYLOAD_PATTERN = re.compile(
    r"\braw\s+(?:chat|prompt|response|tool\s+output|webpage|document|note|"
    r"browser\s+dom|cookie|token|credential)s?\b",
    re.IGNORECASE,
)
_BASE64_TOKEN = re.compile(r"(?<![A-Za-z0-9+/])(?:[A-Za-z0-9+/]{4}){8,}={0,2}")
_BASE64_EXECUTION_MARKERS = (
    "eval(",
    "exec(",
    "pickle.",
    "__import__(",
    "import ",
    "powershell",
    "cmd.exe",
    "bash ",
    "python ",
    "curl ",
    "wget ",
)

_UNTRUSTED_REASON = {
    UntrustedSourceKind.RAW_MODEL_ANSWER: QuarantineReason.UNKNOWN_PROVENANCE,
    UntrustedSourceKind.MODEL_JUDGE_SCORE: QuarantineReason.UNKNOWN_PROVENANCE,
    UntrustedSourceKind.RAW_WEBPAGE: QuarantineReason.RAW_PRIVATE_PAYLOAD,
    UntrustedSourceKind.RAW_DOCUMENT: QuarantineReason.RAW_PRIVATE_PAYLOAD,
    UntrustedSourceKind.RAW_TOOL_OUTPUT: QuarantineReason.RAW_PRIVATE_PAYLOAD,
    UntrustedSourceKind.IMPORTED_SKILL_TEXT: QuarantineReason.UNKNOWN_PROVENANCE,
    UntrustedSourceKind.LEGACY_TRACE_SUCCESS: QuarantineReason.LEGACY_ONLY,
    UntrustedSourceKind.OPTIMIZER_RECOMMENDATION: (QuarantineReason.UNKNOWN_PROVENANCE),
}
_SECURITY_REASON = {
    SecuritySignal.CAPABILITY_ESCALATION: QuarantineReason.CAPABILITY_ESCALATION,
    SecuritySignal.RISK_LEVEL_LOWERING: QuarantineReason.RISK_LEVEL_LOWERING,
    SecuritySignal.RAW_PRIVATE_PAYLOAD: QuarantineReason.RAW_PRIVATE_PAYLOAD,
    SecuritySignal.CHAIN_OF_THOUGHT: QuarantineReason.CHAIN_OF_THOUGHT,
}


def _contains_encoded_code(text: str) -> bool:
    for match in _BASE64_TOKEN.finditer(text):
        token = match.group(0)
        try:
            decoded = base64.b64decode(token, validate=True)
        except (binascii.Error, ValueError):
            continue
        try:
            decoded_text = decoded.decode("utf-8").casefold()
        except UnicodeDecodeError:
            continue
        if any(marker in decoded_text for marker in _BASE64_EXECUTION_MARKERS):
            return True
    return False


def scan_text(text: str) -> tuple[QuarantineReason, ...]:
    """Scan bounded candidate text without executing or fetching anything."""

    reasons: set[QuarantineReason] = set()
    if any(pattern.search(text) for pattern in _PROMPT_INJECTION_PATTERNS):
        reasons.add(QuarantineReason.PROMPT_INJECTION)
    if any(pattern.search(text) for pattern in _FORBIDDEN_CODE_PATTERNS):
        reasons.add(QuarantineReason.FORBIDDEN_CODE)
    if _contains_encoded_code(text):
        reasons.add(QuarantineReason.BASE64_CODE)
    if re.search(r"\bfull_access\b", text, re.IGNORECASE):
        reasons.add(QuarantineReason.FULL_ACCESS)
    if any(pattern.search(text) for pattern in _APPROVAL_PATTERNS):
        reasons.add(QuarantineReason.APPROVAL_INSTRUCTION)
    if re.search(r"https?://", text, re.IGNORECASE):
        reasons.add(QuarantineReason.HIDDEN_EXTERNAL_URL)
    if _PRIVATE_PAYLOAD_PATTERN.search(text):
        reasons.add(QuarantineReason.RAW_PRIVATE_PAYLOAD)
    if re.search(r"\bchain[- ]of[- ]thought\b", text, re.IGNORECASE):
        reasons.add(QuarantineReason.CHAIN_OF_THOUGHT)
    return tuple(sorted(reasons, key=lambda value: value.value))


def scan_content(
    content: CandidateContent, *texts: str
) -> tuple[QuarantineReason, ...]:
    serialized = content.model_dump_json(exclude_none=False)
    return scan_text(" ".join((serialized, *texts)))


def reasons_from_evaluation(
    evaluation: TraceEvaluation,
) -> tuple[QuarantineReason, ...]:
    reasons: set[QuarantineReason] = set()
    if evaluation.recompute_hash() != evaluation.evaluation_hash:
        reasons.add(QuarantineReason.MANIPULATED_EVALUATION)
    if evaluation.evidence_state is EvidenceState.CONFLICTING:
        reasons.add(QuarantineReason.CONFLICTING_EVIDENCE)
    if ConfidenceBasis.LEGACY_HINTS_IGNORED in evaluation.confidence_basis:
        reasons.add(QuarantineReason.LEGACY_ONLY)
    return tuple(sorted(reasons, key=lambda value: value.value))


def reasons_from_request(
    request: StructuredCandidateRequest,
) -> tuple[QuarantineReason, ...]:
    reasons = set(
        scan_content(
            request.content,
            request.title,
            *request.proposed_tests,
            *request.proposed_verification,
        )
    )
    reasons.update(_SECURITY_REASON[signal] for signal in request.security_signals)
    reasons.update(_UNTRUSTED_REASON[source] for source in request.untrusted_sources)
    if isinstance(request.content, SkillCandidateContent) and (
        request.content.maximum_risk_level < request.minimum_required_risk_level
    ):
        reasons.add(QuarantineReason.RISK_LEVEL_LOWERING)
    return tuple(sorted(reasons, key=lambda value: value.value))


def reasons_from_candidate(
    candidate: LearningCandidate,
) -> tuple[QuarantineReason, ...]:
    return scan_content(
        candidate.structured_content,
        candidate.title,
        *candidate.proposed_tests,
        *candidate.proposed_verification,
    )


__all__ = [
    "reasons_from_candidate",
    "reasons_from_evaluation",
    "reasons_from_request",
    "scan_content",
    "scan_text",
]
