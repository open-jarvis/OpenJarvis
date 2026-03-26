"""Tests for GET /v1/security/scan."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.app import create_app  # noqa: E402
from openjarvis.security.environment import EnvFinding, EnvReport, Severity  # noqa: E402


def _make_engine():
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    return engine


@pytest.fixture
def client():
    app = create_app(_make_engine(), "test-model")
    return TestClient(app)


def _mock_report(*findings):
    return EnvReport(findings=list(findings))


def _clean_report():
    return _mock_report(
        EnvFinding("disk_encryption", Severity.INFO, "FileVault is enabled", "Good."),
        EnvFinding("mdm_profiles", Severity.INFO, "No MDM profiles", "Good."),
        EnvFinding("cloud_sync", Severity.INFO, "No cloud sync", "Good."),
        EnvFinding("open_ports", Severity.INFO, "No unexpected ports", "Good."),
        EnvFinding("screen_recording", Severity.INFO, "No apps", "Good."),
        EnvFinding("remote_access", Severity.INFO, "No remote tools", "Good."),
        EnvFinding("dns", Severity.INFO, "Private DNS", "Good."),
    )


class TestSecurityScanRoute:
    def test_returns_200(self, client) -> None:
        with patch("openjarvis.security.environment.run_all_checks", return_value=_clean_report()):
            resp = client.get("/v1/security/scan")
        assert resp.status_code == 200

    def test_response_shape(self, client) -> None:
        with patch("openjarvis.security.environment.run_all_checks", return_value=_clean_report()):
            data = client.get("/v1/security/scan").json()
        assert "has_critical" in data
        assert "has_warnings" in data
        assert "findings" in data
        assert isinstance(data["findings"], list)

    def test_findings_have_required_fields(self, client) -> None:
        with patch("openjarvis.security.environment.run_all_checks", return_value=_clean_report()):
            data = client.get("/v1/security/scan").json()
        for f in data["findings"]:
            assert "check" in f
            assert "severity" in f
            assert "title" in f
            assert "detail" in f
            assert "remediation" in f

    def test_severity_values_are_strings(self, client) -> None:
        with patch("openjarvis.security.environment.run_all_checks", return_value=_clean_report()):
            data = client.get("/v1/security/scan").json()
        for f in data["findings"]:
            assert f["severity"] in ("info", "warn", "critical")

    def test_has_critical_true_when_critical_finding(self, client) -> None:
        report = _mock_report(
            EnvFinding("disk_encryption", Severity.CRITICAL, "FileVault off", "Unencrypted."),
        )
        with patch("openjarvis.security.environment.run_all_checks", return_value=report):
            data = client.get("/v1/security/scan").json()
        assert data["has_critical"] is True
        assert data["has_warnings"] is False

    def test_has_warnings_true_when_warn_finding(self, client) -> None:
        report = _mock_report(
            EnvFinding("cloud_sync", Severity.WARN, "iCloud running", "Sync active."),
        )
        with patch("openjarvis.security.environment.run_all_checks", return_value=report):
            data = client.get("/v1/security/scan").json()
        assert data["has_warnings"] is True
        assert data["has_critical"] is False

    def test_all_clear_report(self, client) -> None:
        with patch("openjarvis.security.environment.run_all_checks", return_value=_clean_report()):
            data = client.get("/v1/security/scan").json()
        assert data["has_critical"] is False
        assert data["has_warnings"] is False
        assert len(data["findings"]) == 7
