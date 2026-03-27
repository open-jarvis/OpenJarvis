"""security_scanner scorer — vulnerability detection evaluation.

Tier 1: Pattern-match model output against vulnerability manifest.
Tier 2: Binary checklist for severity correctness and fix quality.

Score formula:
  (vulns_found/total) * 0.6
  + (severity_correct/found) * 0.2
  + max(0, 1 - FP/3) * 0.1
  + checklist_score * 0.1
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.scorers._checklist import ChecklistScorer, normalize_str

LOGGER = logging.getLogger(__name__)

# Common aliases for vulnerability types
_VULN_TYPE_ALIASES: Dict[str, List[str]] = {
    "sql_injection": ["sql injection", "sqli", "sql inject"],
    "hardcoded_secret": [
        "hardcoded secret",
        "hardcoded credential",
        "hardcoded password",
        "hardcoded api key",
        "hard coded",
        "embedded secret",
        "embedded credential",
    ],
    "command_injection": [
        "command injection",
        "os command injection",
        "shell injection",
        "subprocess injection",
    ],
    "xss": [
        "xss",
        "cross site scripting",
        "cross-site scripting",
        "reflected xss",
        "stored xss",
    ],
    "path_traversal": [
        "path traversal",
        "directory traversal",
        "lfi",
        "local file inclusion",
    ],
    "ssrf": ["ssrf", "server side request forgery", "server-side request forgery"],
    "insecure_deserialization": [
        "insecure deserialization",
        "pickle",
        "yaml load",
        "unsafe deserialization",
    ],
    "weak_crypto": [
        "weak crypto",
        "weak cryptography",
        "md5",
        "sha1",
        "ecb mode",
        "weak hash",
    ],
    "timing_attack": [
        "timing attack",
        "timing side channel",
        "constant time",
        "timing vulnerability",
    ],
    "redos": ["redos", "regex denial", "catastrophic backtracking", "regex dos"],
    "race_condition": ["race condition", "toctou", "time of check"],
    "xxe": ["xxe", "xml external entity"],
    "open_redirect": ["open redirect"],
    "csrf": ["csrf", "cross site request forgery", "cross-site request forgery"],
    "idor": ["idor", "insecure direct object reference"],
    "mass_assignment": ["mass assignment"],
    "jwt_none": ["jwt none", "jwt algorithm none", "alg none"],
}


def _vuln_type_matches(model_text_norm: str, vuln_type: str) -> bool:
    """Check if normalized model text mentions the given vulnerability type."""
    vuln_norm = normalize_str(vuln_type)
    if vuln_norm in model_text_norm:
        return True
    # Check aliases
    for key, aliases in _VULN_TYPE_ALIASES.items():
        key_norm = normalize_str(key)
        if key_norm == vuln_norm or vuln_norm in [normalize_str(a) for a in aliases]:
            for alias in aliases:
                if normalize_str(alias) in model_text_norm:
                    return True
    return False


def _file_mentioned(model_text_norm: str, filename: str) -> bool:
    """Check if the model mentions a specific filename."""
    fname_norm = normalize_str(filename)
    return fname_norm in model_text_norm


def _count_false_positives(
    model_text: str,
    vulnerabilities: List[Dict[str, Any]],
    safe_patterns: List[str],
) -> int:
    """Count findings that don't match any manifest entry.

    Heuristic: count lines that look like vulnerability reports
    (contain keywords like "vulnerability", "injection", "insecure")
    but don't correspond to any known vulnerability.
    """
    model_norm = normalize_str(model_text)
    fp_count = 0

    # Check if model flags any safe patterns as vulnerabilities
    for pattern in safe_patterns:
        pattern_norm = normalize_str(pattern)
        # If the model mentions this safe pattern in a vulnerability context
        if pattern_norm in model_norm:
            # Check if it's flagged as a vulnerability (near vuln keywords)
            for keyword in ["vulnerab", "insecure", "unsafe", "exploit", "risk"]:
                # Look for the pattern and keyword near each other
                pat_idx = model_norm.find(pattern_norm)
                if pat_idx >= 0:
                    surrounding = model_norm[
                        max(0, pat_idx - 200) : pat_idx + len(pattern_norm) + 200
                    ]
                    if keyword in surrounding:
                        fp_count += 1
                        break

    return fp_count


class SecurityScannerScorer(Scorer):
    """Score security scanner output by vulnerability detection accuracy."""

    scorer_id = "security_scanner"

    def __init__(self, judge_backend=None, judge_model: str = "") -> None:
        self._judge_backend = judge_backend
        self._judge_model = judge_model

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response"}

        vulnerabilities = record.metadata.get("vulnerabilities", [])
        safe_patterns = record.metadata.get("safe_patterns", [])

        if not vulnerabilities:
            return None, {"reason": "no_vulnerabilities_in_manifest"}

        model_norm = normalize_str(model_answer)

        # --- Tier 1: Pattern match against vulnerability manifest ---
        vulns_found = 0
        severity_correct = 0
        vuln_details: List[Dict[str, Any]] = []

        for vuln in vulnerabilities:
            file_match = _file_mentioned(model_norm, vuln["file"])
            type_match = _vuln_type_matches(model_norm, vuln["type"])
            found = file_match and type_match

            sev_match = False
            if found and vuln.get("severity"):
                sev_norm = normalize_str(vuln["severity"])
                sev_match = sev_norm in model_norm

            if found:
                vulns_found += 1
            if sev_match:
                severity_correct += 1

            vuln_details.append(
                {
                    "file": vuln["file"],
                    "type": vuln["type"],
                    "severity": vuln.get("severity", ""),
                    "found": found,
                    "file_mentioned": file_match,
                    "type_mentioned": type_match,
                    "severity_correct": sev_match,
                }
            )

        total_vulns = len(vulnerabilities)
        detection_rate = vulns_found / total_vulns if total_vulns > 0 else 0.0
        severity_rate = severity_correct / vulns_found if vulns_found > 0 else 0.0

        # --- False positive penalty ---
        fp_count = _count_false_positives(model_answer, vulnerabilities, safe_patterns)
        fp_penalty = max(0.0, 1.0 - fp_count / 3.0)

        # --- Tier 2: Checklist via LLM judge (if backend available) ---
        checklist_score = 0.0
        checklist_details: List[Dict[str, Any]] = []

        if self._judge_backend and self._judge_model:
            checklist_items = [
                "The report identifies the correct file(s) containing vulnerabilities",
                "The report correctly classifies the type of each vulnerability",
                "The report provides actionable fix recommendations",
                "The report assigns appropriate severity levels",
                "The report is well-structured and professional",
            ]
            scorer = ChecklistScorer(self._judge_backend, self._judge_model)
            checklist_score, checklist_details = scorer.score_checklist(
                model_answer,
                checklist_items,
                context=record.problem,
            )
        else:
            # Without judge, give partial credit based on structural heuristics
            has_recommendations = any(
                kw in model_norm for kw in ["recommend", "fix", "remediat", "mitigat"]
            )
            has_severity = any(
                kw in model_norm for kw in ["critical", "high", "medium", "low"]
            )
            checklist_score = (0.5 if has_recommendations else 0.0) + (
                0.5 if has_severity else 0.0
            )

        # --- Composite score ---
        final_score = (
            detection_rate * 0.6
            + severity_rate * 0.2
            + fp_penalty * 0.1
            + checklist_score * 0.1
        )

        is_correct = detection_rate == 1.0 and final_score >= 0.8

        return is_correct, {
            "match_type": "security_scan",
            "vulns_found": vulns_found,
            "total_vulns": total_vulns,
            "detection_rate": round(detection_rate, 3),
            "severity_correct": severity_correct,
            "severity_rate": round(severity_rate, 3),
            "false_positives": fp_count,
            "fp_penalty": round(fp_penalty, 3),
            "checklist_score": round(checklist_score, 3),
            "final_score": round(final_score, 3),
            "vuln_details": vuln_details,
            "checklist_details": checklist_details,
        }


__all__ = ["SecurityScannerScorer"]
