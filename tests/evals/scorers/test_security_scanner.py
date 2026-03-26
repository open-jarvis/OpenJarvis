"""Tests for the security_scanner scorer."""

from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.scorers.security_scanner import SecurityScannerScorer


def _make_record(vulnerabilities, safe_patterns=None):
    return EvalRecord(
        record_id="test-sec-1",
        problem="Scan this project for vulnerabilities.",
        reference="",
        category="agentic",
        metadata={
            "project_files": {"app.py": "..."},
            "vulnerabilities": vulnerabilities,
            "safe_patterns": safe_patterns or [],
        },
    )


def _vuln(file, vtype, severity, desc=""):
    return {
        "file": file,
        "type": vtype,
        "severity": severity,
        "description": desc,
    }


def test_all_vulns_found():
    vulns = [
        _vuln("app.py", "sql_injection", "critical"),
        _vuln("config.py", "hardcoded_secret", "high"),
    ]
    record = _make_record(vulns)
    scorer = SecurityScannerScorer()

    answer = (
        "## Security Report\n\n"
        "**app.py**: Found SQL injection vulnerability "
        "(CRITICAL severity) in the database query.\n\n"
        "**config.py**: Hardcoded secret — API key "
        "embedded in source code (HIGH severity).\n\n"
        "### Recommendations\n"
        "1. Use parameterized queries\n"
        "2. Move secrets to environment variables"
    )
    is_correct, meta = scorer.score(record, answer)
    assert meta["vulns_found"] == 2
    assert meta["total_vulns"] == 2
    assert meta["detection_rate"] == 1.0
    assert meta["severity_correct"] == 2
    assert is_correct is True


def test_partial_detection():
    vulns = [
        _vuln("app.py", "sql_injection", "critical"),
        _vuln("utils.py", "command_injection", "high"),
    ]
    record = _make_record(vulns)
    scorer = SecurityScannerScorer()

    answer = (
        "Found SQL injection in app.py. Severity: critical. Use parameterized queries."
    )
    is_correct, meta = scorer.score(record, answer)
    assert meta["vulns_found"] == 1
    assert meta["detection_rate"] == 0.5
    assert is_correct is False


def test_empty_answer():
    vulns = [_vuln("app.py", "xss", "high")]
    record = _make_record(vulns)
    scorer = SecurityScannerScorer()
    is_correct, meta = scorer.score(record, "")
    assert is_correct is False
    assert meta["reason"] == "empty_response"


def test_false_positive_penalty():
    vulns = [_vuln("app.py", "sql_injection", "critical")]
    safe = [
        "parameterized query in auth.py",
        "escaped output in templates",
    ]
    record = _make_record(vulns, safe)
    scorer = SecurityScannerScorer()

    answer = (
        "Found SQL injection in app.py (critical).\n"
        "Also found vulnerability: parameterized "
        "query in auth.py is insecure.\n"
        "The escaped output in templates is unsafe "
        "and exploitable.\n"
        "Recommendations: fix all issues."
    )
    is_correct, meta = scorer.score(record, answer)
    assert meta["vulns_found"] == 1
    assert meta["false_positives"] >= 1


def test_vuln_type_aliases():
    vulns = [_vuln("app.py", "xss", "high")]
    record = _make_record(vulns)
    scorer = SecurityScannerScorer()

    answer = "app.py has a cross-site scripting vulnerability. Severity: high."
    is_correct, meta = scorer.score(record, answer)
    assert meta["vulns_found"] == 1
    assert meta["detection_rate"] == 1.0


def test_no_vulnerabilities():
    record = _make_record([])
    scorer = SecurityScannerScorer()
    is_correct, meta = scorer.score(
        record,
        "Everything looks clean.",
    )
    assert is_correct is None
    assert meta["reason"] == "no_vulnerabilities_in_manifest"
