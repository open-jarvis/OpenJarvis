"""SSRF: disguised-IPv4 forms are normalized and unresolvable hosts fail closed.

Regression tests for the ``_check_ssrf_python`` fallback used when the compiled
Rust backend is unavailable.
"""

from __future__ import annotations

import pytest

from openjarvis.security.ssrf import _check_ssrf_python


class TestSSRFDisguisedForms:
    @pytest.mark.parametrize(
        "url",
        [
            "http://2130706433/",  # decimal 127.0.0.1
            "http://0x7f000001/",  # hex 127.0.0.1
            "http://0x7f.0x0.0x0.0x1/",  # dotted hex
            "http://127.1/",  # short-dotted loopback
        ],
    )
    def test_disguised_loopback_blocked(self, url):
        assert _check_ssrf_python(url) is not None

    def test_plain_loopback_still_blocked(self):
        assert _check_ssrf_python("http://127.0.0.1/") is not None

    def test_metadata_endpoint_blocked(self):
        assert _check_ssrf_python("http://169.254.169.254/") is not None

    def test_unresolvable_host_fails_closed(self):
        result = _check_ssrf_python("http://this-host-does-not-exist-zzz.invalid/")
        assert result is not None  # blocked, not silently allowed

    def test_fail_open_override(self, monkeypatch):
        monkeypatch.setenv("OPENJARVIS_SSRF_FAIL_OPEN", "1")
        assert _check_ssrf_python("http://another-nonexistent-zzz.invalid/") is None
