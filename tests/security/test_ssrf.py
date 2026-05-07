"""Tests for SSRF protection module."""

from __future__ import annotations

from unittest.mock import patch

from openjarvis.security.ssrf import _check_ssrf_python, check_ssrf, is_private_ip


class TestIsPrivateIp:
    def test_private_10_network(self):
        assert is_private_ip("10.0.0.1") is True
        assert is_private_ip("10.255.255.255") is True

    def test_private_172_16_network(self):
        assert is_private_ip("172.16.0.1") is True
        assert is_private_ip("172.31.255.255") is True

    def test_private_192_168_network(self):
        assert is_private_ip("192.168.0.1") is True
        assert is_private_ip("192.168.1.100") is True

    def test_loopback(self):
        assert is_private_ip("127.0.0.1") is True
        assert is_private_ip("127.255.255.255") is True

    def test_ipv6_loopback(self):
        assert is_private_ip("::1") is True

    def test_link_local(self):
        assert is_private_ip("169.254.0.1") is True

    def test_public_ips(self):
        assert is_private_ip("8.8.8.8") is False
        assert is_private_ip("1.1.1.1") is False
        assert is_private_ip("93.184.216.34") is False

    def test_invalid_ip(self):
        assert is_private_ip("not-an-ip") is False

    def test_empty_string(self):
        assert is_private_ip("") is False

    def test_ipv4_mapped_ipv6_loopback(self):
        # ::ffff:127.0.0.1 — IPv4-mapped form of loopback must be flagged.
        assert is_private_ip("::ffff:127.0.0.1") is True

    def test_ipv4_mapped_ipv6_rfc1918(self):
        assert is_private_ip("::ffff:10.0.0.1") is True
        assert is_private_ip("::ffff:172.16.0.1") is True
        assert is_private_ip("::ffff:192.168.1.1") is True

    def test_ipv4_mapped_ipv6_link_local(self):
        assert is_private_ip("::ffff:169.254.0.1") is True

    def test_ipv4_mapped_ipv6_public_allowed(self):
        # Public IPv4 wrapped as IPv6 must NOT be flagged as private.
        assert is_private_ip("::ffff:8.8.8.8") is False

    def test_ipv4_compatible_loopback(self):
        # ::127.0.0.1 — deprecated IPv4-compatible form, must still be blocked.
        assert is_private_ip("::127.0.0.1") is True

    def test_unspecified_addresses(self):
        assert is_private_ip("0.0.0.0") is True
        assert is_private_ip("::") is True

    def test_zero_subnet_is_private(self):
        # 0.0.0.0/8 routes to localhost on Linux.
        assert is_private_ip("0.1.2.3") is True

    def test_multicast_and_broadcast_blocked(self):
        assert is_private_ip("239.0.0.1") is True
        assert is_private_ip("255.255.255.255") is True
        assert is_private_ip("ff02::1") is True


class TestCheckSsrf:
    """Tests for SSRF protection.

    The Rust backend performs real DNS resolution, so tests that need to
    mock DNS use ``_check_ssrf_python`` (the pure-Python implementation)
    instead of the Rust-backed ``check_ssrf``.
    """

    def test_blocks_aws_metadata(self):
        result = check_ssrf("http://169.254.169.254/latest/meta-data/")
        assert result is not None
        assert "cloud metadata" in result.lower() or "Blocked host" in result

    def test_blocks_google_metadata(self):
        result = check_ssrf("http://metadata.google.internal/computeMetadata/v1/")
        assert result is not None
        assert "Blocked host" in result

    def test_blocks_alibaba_metadata(self):
        result = check_ssrf("http://100.100.100.200/latest/meta-data/")
        assert result is not None
        assert "Blocked host" in result

    def test_allows_normal_urls(self):
        # Use Python impl so we can mock DNS resolution
        with patch("openjarvis.security.ssrf.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 0)),
            ]
            result = _check_ssrf_python("https://example.com")
        assert result is None

    def test_blocks_localhost_url(self):
        with patch("openjarvis.security.ssrf.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (2, 1, 6, "", ("127.0.0.1", 0)),
            ]
            result = _check_ssrf_python("http://localhost:8080/admin")
        assert result is not None
        assert "private IP" in result

    def test_blocks_private_ip_url(self):
        with patch("openjarvis.security.ssrf.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (2, 1, 6, "", ("192.168.1.1", 0)),
            ]
            result = _check_ssrf_python("http://internal-service.local/api")
        assert result is not None
        assert "private IP" in result

    def test_no_hostname(self):
        # Rust returns "Invalid URL" for malformed URLs (no scheme => parse error)
        result = check_ssrf("not-a-url")
        assert result is not None
        assert "Invalid URL" in result

    def test_dns_failure_allowed(self):
        """DNS resolution failure should not block — request will fail at HTTP time."""
        import socket

        with patch(
            "openjarvis.security.ssrf.socket.getaddrinfo",
            side_effect=socket.gaierror("Name resolution failed"),
        ):
            result = _check_ssrf_python("https://nonexistent.example.com")
        assert result is None

    def test_blocks_dns_rebinding_to_private(self):
        """Even if hostname looks normal, block if it resolves to private IP."""
        with patch("openjarvis.security.ssrf.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (2, 1, 6, "", ("10.0.0.5", 0)),
            ]
            result = _check_ssrf_python("https://evil-rebind.example.com")
        assert result is not None
        assert "private IP" in result

    def test_blocks_ipv4_mapped_loopback_url(self):
        """IPv4-mapped IPv6 form of 127.0.0.1 must be blocked (Rust path)."""
        result = check_ssrf("http://[::ffff:127.0.0.1]:6666")
        assert result is not None
        assert "private IP" in result

    def test_blocks_ipv4_mapped_rfc1918_url(self):
        for url in (
            "http://[::ffff:10.0.0.1]/",
            "http://[::ffff:192.168.1.1]/",
            "http://[::ffff:172.16.0.1]/",
        ):
            result = check_ssrf(url)
            assert result is not None, f"{url} must be blocked"
            assert "private IP" in result

    def test_blocks_ipv4_mapped_metadata_url(self):
        # ::ffff:169.254.169.254 — IPv4-mapped form of cloud metadata IP.
        result = check_ssrf("http://[::ffff:169.254.169.254]/latest/meta-data/")
        assert result is not None

    def test_blocks_ipv6_loopback_literal_url(self):
        result = check_ssrf("http://[::1]:80/")
        assert result is not None

    def test_allows_ipv4_mapped_public_url(self):
        result = check_ssrf("http://[::ffff:8.8.8.8]/")
        assert result is None

    def test_python_impl_blocks_ipv4_mapped_loopback(self):
        """Legacy Python impl must also catch ::ffff:127.0.0.1."""
        result = _check_ssrf_python("http://[::ffff:127.0.0.1]:6666")
        assert result is not None
        assert "private IP" in result

    def test_python_impl_blocks_ipv4_mapped_metadata(self):
        result = _check_ssrf_python(
            "http://[::ffff:169.254.169.254]/latest/meta-data/"
        )
        assert result is not None

    def test_blocks_ipv4_mapped_alibaba_metadata(self):
        # 100.100.100.200 isn't private — relies on BLOCKED_HOSTS lookup
        # against the embedded v4. Verifies the canonical-host fix.
        result = check_ssrf("http://[::ffff:100.100.100.200]/")
        assert result is not None
        assert "Blocked host" in result

    def test_blocks_ipv4_compatible_loopback(self):
        result = check_ssrf("http://[::127.0.0.1]/")
        assert result is not None

    def test_blocks_zero_dot_zero(self):
        result = check_ssrf("http://0.0.0.0/")
        assert result is not None

    def test_url_userinfo_does_not_bypass(self):
        # Userinfo + bracketed IPv6 literal still gets blocked.
        result = check_ssrf("http://user:pass@[::ffff:127.0.0.1]:8080/admin")
        assert result is not None

    def test_canonicalized_hex_ipv6_form_blocked(self):
        # url crate canonicalizes [::ffff:127.0.0.1] to [::ffff:7f00:1]
        # internally; ensure this form blocks too.
        result = check_ssrf("http://[::ffff:7f00:1]/")
        assert result is not None


__all__ = ["TestCheckSsrf", "TestIsPrivateIp"]
