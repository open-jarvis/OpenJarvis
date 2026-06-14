import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from src.openjarvis.server.osint_store import OsintStore

class TestOsintAlerts:
    def setup_method(self):
        self.store = OsintStore()

    def test_diff_scan_no_previous(self):
        self.store.save_scan("u1", "x.com", ["dns"], {"ip": "1.2.3.4"}, {"errors": 0})
        diff = self.store.diff_scan("u1", "x.com")
        assert diff is None

    def test_diff_scan_detects_changes(self):
        self.store.save_scan("u1", "x.com", ["dns"], {"ip": "1.2.3.4", "mx": ["mx1"]}, {"errors": 0})
        self.store.save_scan("u1", "x.com", ["dns"], {"ip": "5.6.7.8", "mx": ["mx1", "mx2"]}, {"errors": 0})
        diff = self.store.diff_scan("u1", "x.com")
        assert diff is not None
        assert "changed" in diff
        assert diff["changed"]["ip"]["from"] == "1.2.3.4"
        assert diff["changed"]["ip"]["to"] == "5.6.7.8"
        assert "added" in diff
        assert "mx" in diff["added"]

    def test_diff_scan_no_changes(self):
        self.store.save_scan("u1", "x.com", ["dns"], {"ip": "1.2.3.4"}, {"errors": 0})
        self.store.save_scan("u1", "x.com", ["dns"], {"ip": "1.2.3.4"}, {"errors": 0})
        diff = self.store.diff_scan("u1", "x.com")
        assert diff is None

    def test_list_alerts(self):
        self.store.save_scan("u1", "x.com", ["dns"], {"ip": "1.2.3.4"}, {"errors": 0})
        self.store.save_scan("u1", "x.com", ["dns"], {"ip": "5.6.7.8"}, {"errors": 0})
        diff = self.store.diff_scan("u1", "x.com")
        for entry in self.store._user_history("u1"):
            if entry.type == "scan" and entry.results.get("ip") == "5.6.7.8":
                entry.metadata["diff"] = diff
                break
        alerts = self.store.list_alerts("u1")
        assert len(alerts) == 1
        assert alerts[0]["target"] == "x.com"
        assert "diff" in alerts[0]["metadata"]

    def test_tick_creates_diff_on_change(self):
        job = self.store.create_schedule("u1", "example.com", ["dns"], 30)
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        job.next_run = past
        call_count = 0
        def fake_run_scan(target, modules):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"target": target, "modules": modules, "results": {"ip": "1.2.3.4"}, "summary": {"errors": 0}}
            else:
                return {"target": target, "modules": modules, "results": {"ip": "5.6.7.8"}, "summary": {"errors": 0}}

        with patch("openjarvis.tools.fbi_watchdog.core.run_scan", fake_run_scan):
            # First tick
            executed1 = self.store._tick()
            assert len(executed1) == 1
            assert executed1[0]["success"] is True
            assert executed1[0]["changed"] is False

            # Set next_run to past so second tick triggers immediately
            job.next_run = past

            # Second tick with different result
            executed2 = self.store._tick()
            assert len(executed2) == 1
            assert executed2[0]["success"] is True
            assert executed2[0]["changed"] is True

        # Verify alerts
        alerts = self.store.list_alerts("u1")
        assert len(alerts) == 1
        assert alerts[0]["target"] == "example.com"
        assert "diff" in alerts[0]["metadata"]
