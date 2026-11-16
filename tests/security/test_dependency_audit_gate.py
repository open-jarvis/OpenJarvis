"""Dependency gates must reject new findings and incomplete audit evidence."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts/security/audit_dependencies.py"
_SPEC = importlib.util.spec_from_file_location("dependency_audit_gate", _PATH)
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)
TODAY = dt.date(2026, 11, 16)


def exception(**overrides):
    return {
        "lockfile": "uv.lock",
        "package": "example",
        "version": "1.2.3",
        "advisories": ["GHSA-1234-5678-abcd"],
        "reason": "Upstream has no compatible patch; the vulnerable API is not used.",
        "upstream": "https://example.org/security/advisory",
        "expires": "2026-12-01",
        **overrides,
    }


def policy_file(tmp_path, entries):
    path = tmp_path / "exceptions.json"
    path.write_text(json.dumps({"schema": 1, "exceptions": entries}))
    return path


def test_clean_complete_query_passes():
    packages = [{"name": "example", "version": "1.2.3"}]
    assert gate.python_findings(packages, lambda _: {"results": [{}]}) == []


def test_queries_every_version_across_batch_boundary():
    packages = [{"name": "example", "version": f"1.2.{i}"} for i in range(101)]
    batches = []

    def query(queries):
        batches.append(queries)
        result = {"results": [{} for _ in queries]}
        if len(queries) == 1:
            result["results"][0] = {"vulns": [{"id": "GHSA-new-1234-abcd"}]}
        return result

    findings = gate.python_findings(packages, query)
    assert [len(b) for b in batches] == [100, 1]
    assert findings == [
        {"name": "example", "version": "1.2.100", "advisory": "GHSA-new-1234-abcd"}
    ]


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"results": []},
        {"results": [{}, {}]},
        {"results": [None]},
        {"results": [{"error": "upstream failure"}]},
        {"results": [{"vulns": None}]},
        {"results": [{"vulns": [None]}]},
        {"results": [{"vulns": [{}]}]},
        {"error": "offline", "results": [{}]},
        {"results": [{"warnings": ["skipped"]}]},
        {"results": [{"next_page_token": "another-page"}]},
    ],
)
def test_incomplete_or_malformed_query_fails_closed(response):
    with pytest.raises(gate.AuditError):
        gate.python_findings(
            [{"name": "example", "version": "1.2.3"}], lambda _: response
        )


def test_network_failure_cannot_be_clean_result(monkeypatch):
    import urllib.error

    def offline(*args, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(gate.urllib.request, "urlopen", offline)
    monkeypatch.setattr(gate.time, "sleep", lambda _: None)
    with pytest.raises(gate.AuditError, match="incomplete audit"):
        gate.request_osv([])


def test_known_exception_does_not_allow_new_advisory_or_version():
    entries = [exception()]
    accepted = {
        "name": "example",
        "version": "1.2.3",
        "advisory": "GHSA-1234-5678-abcd",
    }
    new_id = {**accepted, "advisory": "GHSA-new-1234-abcd"}
    new_version = {**accepted, "version": "1.2.4"}
    results = gate.apply_exceptions([accepted, new_id, new_version], entries)
    assert [r["excepted"] for r in results] == [True, False, False]


def test_removed_advisory_requires_exception_cleanup():
    with pytest.raises(gate.AuditError, match="no longer appear"):
        gate.apply_exceptions([], [exception()])


@pytest.mark.parametrize(
    "change",
    [
        {"expires": "2026-11-16"},
        {"expires": "2026-01-01"},
        {"expires": "2030-01-01"},
        {"expires": "tomorrow"},
        {"version": "*"},
        {"version": ">=1.0"},
        {"advisories": ["*"]},
        {"advisories": []},
        {"reason": "ignore"},
        {"upstream": "http://example.org"},
        {"lockfile": "elsewhere.lock"},
    ],
)
def test_invalid_or_expired_exception_is_rejected(tmp_path, change):
    with pytest.raises(gate.AuditError):
        gate.read_policy(policy_file(tmp_path, [exception(**change)]), TODAY)


def test_duplicate_exceptions_fail(tmp_path):
    entry = exception()
    with pytest.raises(gate.AuditError, match="Duplicate"):
        gate.read_policy(policy_file(tmp_path, [entry, entry]), TODAY)


def test_exact_bounded_exception_is_valid(tmp_path):
    assert gate.read_policy(policy_file(tmp_path, [exception()]), TODAY) == [
        exception()
    ]


def test_new_package_source_cannot_silently_escape_python_audit(tmp_path):
    path = tmp_path / "uv.lock"
    path.write_text(
        '[[package]]\nname="example"\nversion="1.2.3"\nsource={git="https://example.org/repo"}\n'
    )
    with pytest.raises(gate.AuditError, match="Unreviewed"):
        gate.lock_packages(path, "uv.lock")


def test_missing_package_source_is_an_audit_error(tmp_path):
    path = tmp_path / "uv.lock"
    path.write_text('[[package]]\nname="example"\nversion="1.2.3"\n')
    with pytest.raises(gate.AuditError, match="Unreviewed"):
        gate.lock_packages(path, "uv.lock")


def test_only_own_editable_project_is_excluded(tmp_path):
    path = tmp_path / "uv.lock"
    path.write_text(
        '[[package]]\nname="openjarvis"\nsource={editable="."}\n'
        '[[package]]\nname="example"\nversion="1.2.3"\nsource={registry="https://pypi.org/simple"}\n'
    )
    assert gate.lock_packages(path, "uv.lock") == [
        {"name": "example", "version": "1.2.3"}
    ]
    path.write_text('[[package]]\nname="other"\nsource={editable="."}\n')
    with pytest.raises(gate.AuditError):
        gate.lock_packages(path, "uv.lock")


def test_empty_lock_cannot_pass(tmp_path):
    path = tmp_path / "uv.lock"
    path.write_text("package=[]")
    with pytest.raises(gate.AuditError, match="no packages"):
        gate.lock_packages(path, "uv.lock")


def test_own_native_project_is_covered_by_the_separate_rust_audit(tmp_path):
    path = tmp_path / "uv.lock"
    path.write_text(
        '[[package]]\nname="openjarvis-rust"\n'
        'source={directory="rust/crates/openjarvis-python"}\n'
        '[[package]]\nname="example"\nversion="1.2.3"\n'
        'source={registry="https://pypi.org/simple"}\n'
    )
    assert gate.lock_packages(path, "uv.lock") == [
        {"name": "example", "version": "1.2.3"}
    ]
    path.write_text(
        path.read_text().replace("rust/crates/openjarvis-python", "elsewhere")
    )
    with pytest.raises(gate.AuditError, match="Unreviewed"):
        gate.lock_packages(path, "uv.lock")


def test_changed_package_version_requires_exception_cleanup():
    with pytest.raises(gate.AuditError, match="stale"):
        gate.scoped_exceptions(
            [exception()], [{"name": "example", "version": "1.2.4"}], "uv.lock"
        )


def test_rust_config_denies_yanked_unsound_and_unknown_sources():
    text = gate.cargo_config([])
    config = gate.tomllib.loads(text)
    assert config["advisories"]["yanked"] == "deny"
    assert config["advisories"]["unsound"] == "all"
    assert config["sources"] == {"unknown-registry": "deny", "unknown-git": "deny"}


def test_exception_is_limited_to_its_lockfile():
    entry = exception(lockfile="frontend/src-tauri/Cargo.lock")
    assert (
        gate.scoped_exceptions(
            [entry], [{"name": "example", "version": "1.2.3"}], "rust/Cargo.lock"
        )
        == []
    )


def test_cargo_exception_is_rendered_only_after_validation(tmp_path):
    entry = exception(
        lockfile="frontend/src-tauri/Cargo.lock", advisories=["RUSTSEC-2024-0429"]
    )
    policy = gate.read_policy(policy_file(tmp_path, [entry]), TODAY)
    config = gate.tomllib.loads(gate.cargo_config(policy))
    assert config["advisories"]["ignore"][0]["id"] == "RUSTSEC-2024-0429"
    assert "2026-12-01" in config["advisories"]["ignore"][0]["reason"]


def test_cli_records_audit_failure_and_returns_nonzero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("uv.lock").write_text(
        '[[package]]\nname="example"\nversion="1.2.3"\nsource={registry="https://pypi.org/simple"}\n'
    )
    policy = policy_file(tmp_path, [])
    monkeypatch.setattr(
        gate,
        "python_findings",
        lambda _: (_ for _ in ()).throw(gate.AuditError("offline")),
    )
    assert (
        gate.main(
            [
                "python",
                "--lockfile",
                "uv.lock",
                "--policy",
                str(policy),
                "--output",
                "report.json",
            ]
        )
        == 2
    )
    assert json.loads(Path("report.json").read_text()) == {"error": "offline"}


def test_cli_new_advisory_is_a_failing_check(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("uv.lock").write_text(
        '[[package]]\nname="example"\nversion="1.2.3"\n'
        'source={registry="https://pypi.org/simple"}\n'
    )
    policy = policy_file(tmp_path, [])
    finding = {"name": "example", "version": "1.2.3", "advisory": "GHSA-new-1234-abcd"}
    monkeypatch.setattr(gate, "python_findings", lambda _: [finding])
    result = gate.main(
        [
            "python",
            "--lockfile",
            "uv.lock",
            "--policy",
            str(policy),
            "--output",
            "report.json",
        ]
    )
    assert result == 1
    report = json.loads(Path("report.json").read_text())
    assert report["findings"][0]["excepted"] is False
