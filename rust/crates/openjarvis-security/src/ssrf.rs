//! SSRF protection — block requests to private IPs and cloud metadata endpoints.

use once_cell::sync::Lazy;
use std::collections::HashSet;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, ToSocketAddrs};

static BLOCKED_HOSTS: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    HashSet::from([
        "169.254.169.254",
        "metadata.google.internal",
        "metadata.google.com",
        "100.100.100.200",
    ])
});

/// Normalize an IPv6 address to its embedded IPv4 if it is an IPv4-mapped
/// (`::ffff:a.b.c.d`) or IPv4-compatible (`::a.b.c.d`, deprecated) form.
/// Returns `None` for `::` and `::1` (these are checked as IPv6 directly).
fn embedded_ipv4(v6: &Ipv6Addr) -> Option<Ipv4Addr> {
    if let Some(v4) = v6.to_ipv4_mapped() {
        return Some(v4);
    }
    // IPv4-compatible (::a.b.c.d) — RFC 4291 deprecated but still parseable.
    // Excludes `::` and `::1` which must be classified as IPv6.
    let segments = v6.segments();
    if segments[0] == 0
        && segments[1] == 0
        && segments[2] == 0
        && segments[3] == 0
        && segments[4] == 0
        && segments[5] == 0
        && !v6.is_unspecified()
        && !v6.is_loopback()
    {
        let octets: [u8; 4] = [
            (segments[6] >> 8) as u8,
            (segments[6] & 0xff) as u8,
            (segments[7] >> 8) as u8,
            (segments[7] & 0xff) as u8,
        ];
        return Some(Ipv4Addr::from(octets));
    }
    None
}

/// Check if an IP address is private/reserved.
pub fn is_private_ip(ip: &IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => {
            v4.is_loopback()
                || v4.is_private()
                || v4.is_link_local()
                || is_in_cidr_v4(v4, Ipv4Addr::new(169, 254, 0, 0), 16)
                || *v4 == Ipv4Addr::UNSPECIFIED
                || v4.is_broadcast()
                || v4.is_multicast()
                // 0.0.0.0/8 — current network, routes to localhost on Linux
                || v4.octets()[0] == 0
        }
        IpAddr::V6(v6) => {
            // IPv4-mapped (`::ffff:a.b.c.d`) and IPv4-compatible (`::a.b.c.d`)
            // addresses must be classified by their embedded IPv4. Without
            // this, the IPv6 checks below never match RFC1918 / loopback /
            // link-local ranges and the address is treated as public.
            if let Some(v4) = embedded_ipv4(v6) {
                return is_private_ip(&IpAddr::V4(v4));
            }
            v6.is_loopback()
                || v6.is_unspecified()
                || v6.is_multicast()
                || is_ula_v6(v6)
                || is_link_local_v6(v6)
        }
    }
}

fn is_in_cidr_v4(addr: &Ipv4Addr, network: Ipv4Addr, prefix_len: u32) -> bool {
    let mask = if prefix_len == 0 {
        0u32
    } else {
        !0u32 << (32 - prefix_len)
    };
    (u32::from(*addr) & mask) == (u32::from(network) & mask)
}

fn is_ula_v6(addr: &Ipv6Addr) -> bool {
    let segments = addr.segments();
    (segments[0] & 0xfe00) == 0xfc00
}

fn is_link_local_v6(addr: &Ipv6Addr) -> bool {
    let segments = addr.segments();
    (segments[0] & 0xffc0) == 0xfe80
}

/// Check a URL for SSRF vulnerabilities.
/// Returns an error message or None if safe.
pub fn check_ssrf(url_str: &str) -> Option<String> {
    let parsed = match url::Url::parse(url_str) {
        Ok(u) => u,
        Err(_) => return Some("Invalid URL".into()),
    };

    // Use the typed `Host` enum rather than `host_str()`. `host_str()` returns
    // IPv6 addresses with brackets and in canonicalized hex form (e.g.
    // `[::ffff:7f00:1]`), which neither `IpAddr::from_str` nor a string-based
    // `BLOCKED_HOSTS` lookup can match against.
    let host = match parsed.host() {
        Some(h) => h,
        None => return Some("No hostname in URL".into()),
    };

    let literal_ip: Option<IpAddr> = match &host {
        url::Host::Ipv4(v4) => Some(IpAddr::V4(*v4)),
        url::Host::Ipv6(v6) => Some(
            // Normalize IPv4-mapped / IPv4-compatible IPv6 to embedded IPv4
            // so the `BLOCKED_HOSTS` and private-range checks below catch
            // them. This is the core SSRF fix.
            embedded_ipv4(v6)
                .map(IpAddr::V4)
                .unwrap_or(IpAddr::V6(*v6)),
        ),
        url::Host::Domain(_) => None,
    };

    // Build the canonical host string for `BLOCKED_HOSTS` lookup. For IPv4
    // (including normalized IPv4-mapped forms) this is the dotted-decimal
    // representation; for IPv6 it is the un-bracketed canonical form.
    let canonical_host: String = match (&literal_ip, &host) {
        (Some(IpAddr::V4(v4)), _) => v4.to_string(),
        (Some(IpAddr::V6(v6)), _) => v6.to_string(),
        (None, url::Host::Domain(d)) => d.to_string(),
        _ => unreachable!(),
    };

    if BLOCKED_HOSTS.contains(canonical_host.as_str()) {
        return Some(format!(
            "Blocked host: {} (cloud metadata endpoint)",
            canonical_host
        ));
    }

    if let Some(ip) = literal_ip {
        if is_private_ip(&ip) {
            return Some(format!("URL resolves to private IP: {}", ip));
        }
        return None;
    }

    // Domain hostname — fall through to DNS resolution.
    let port = parsed.port().unwrap_or(match parsed.scheme() {
        "https" => 443,
        _ => 80,
    });

    let addr_str = format!("{}:{}", canonical_host, port);
    if let Ok(addrs) = addr_str.to_socket_addrs() {
        for addr in addrs {
            if is_private_ip(&addr.ip()) {
                return Some(format!("URL resolves to private IP: {}", addr.ip()));
            }
        }
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_private_ip_detection() {
        assert!(is_private_ip(&IpAddr::V4(Ipv4Addr::new(10, 0, 0, 1))));
        assert!(is_private_ip(&IpAddr::V4(Ipv4Addr::new(192, 168, 1, 1))));
        assert!(is_private_ip(&IpAddr::V4(Ipv4Addr::new(172, 16, 0, 1))));
        assert!(is_private_ip(&IpAddr::V4(Ipv4Addr::LOCALHOST)));
    }

    #[test]
    fn test_public_ip_allowed() {
        assert!(!is_private_ip(&IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8))));
        assert!(!is_private_ip(&IpAddr::V4(Ipv4Addr::new(1, 1, 1, 1))));
    }

    #[test]
    fn test_blocked_metadata_host() {
        let result = check_ssrf("http://169.254.169.254/latest/meta-data/");
        assert!(result.is_some());
        assert!(result.unwrap().contains("Blocked host"));
    }

    #[test]
    fn test_invalid_url() {
        let result = check_ssrf("not-a-url");
        assert!(result.is_some());
    }

    #[test]
    fn test_ipv4_mapped_ipv6_loopback_is_private() {
        // ::ffff:127.0.0.1
        let mapped: Ipv6Addr = "::ffff:127.0.0.1".parse().unwrap();
        assert!(is_private_ip(&IpAddr::V6(mapped)));
    }

    #[test]
    fn test_ipv4_mapped_ipv6_rfc1918_is_private() {
        for s in ["::ffff:10.0.0.1", "::ffff:172.16.0.1", "::ffff:192.168.1.1"] {
            let v6: Ipv6Addr = s.parse().unwrap();
            assert!(is_private_ip(&IpAddr::V6(v6)), "{} should be private", s);
        }
    }

    #[test]
    fn test_ipv4_mapped_ipv6_link_local_is_private() {
        let v6: Ipv6Addr = "::ffff:169.254.0.1".parse().unwrap();
        assert!(is_private_ip(&IpAddr::V6(v6)));
    }

    #[test]
    fn test_ipv4_mapped_public_ipv6_allowed() {
        // ::ffff:8.8.8.8 — public IPv4 wrapped as IPv6 must NOT be flagged.
        let v6: Ipv6Addr = "::ffff:8.8.8.8".parse().unwrap();
        assert!(!is_private_ip(&IpAddr::V6(v6)));
    }

    #[test]
    fn test_ipv6_unspecified_is_private() {
        assert!(is_private_ip(&IpAddr::V6(Ipv6Addr::UNSPECIFIED)));
    }

    #[test]
    fn test_check_ssrf_blocks_ipv4_mapped_loopback_url() {
        let result = check_ssrf("http://[::ffff:127.0.0.1]:6666");
        assert!(result.is_some(), "::ffff:127.0.0.1 must be blocked");
        assert!(result.unwrap().contains("private IP"));
    }

    #[test]
    fn test_check_ssrf_blocks_ipv4_mapped_rfc1918_url() {
        for url in [
            "http://[::ffff:10.0.0.1]/",
            "http://[::ffff:192.168.1.1]/",
            "http://[::ffff:172.16.0.1]/",
        ] {
            let result = check_ssrf(url);
            assert!(result.is_some(), "{} must be blocked", url);
        }
    }

    #[test]
    fn test_check_ssrf_blocks_ipv4_mapped_metadata_url() {
        // ::ffff:169.254.169.254 — IPv4-mapped form of AWS/GCP metadata IP.
        let result = check_ssrf("http://[::ffff:169.254.169.254]/latest/meta-data/");
        assert!(result.is_some());
    }

    #[test]
    fn test_check_ssrf_blocks_ipv6_loopback_literal() {
        // Bracketed IPv6 literal must be checked even though `host:port`
        // string parsing of the unbracketed form is ambiguous.
        let result = check_ssrf("http://[::1]:80/");
        assert!(result.is_some());
    }

    #[test]
    fn test_check_ssrf_allows_ipv4_mapped_public() {
        let result = check_ssrf("http://[::ffff:8.8.8.8]/");
        assert!(result.is_none(), "public IP wrapped as IPv6 must be allowed");
    }

    #[test]
    fn test_check_ssrf_blocks_ipv4_mapped_alibaba_metadata() {
        // ::ffff:100.100.100.200 — Alibaba metadata; not in any private CIDR,
        // so must be caught by `BLOCKED_HOSTS` lookup on the normalized IPv4.
        let result = check_ssrf("http://[::ffff:100.100.100.200]/");
        assert!(result.is_some(), "Alibaba metadata via mapped form must be blocked");
        assert!(result.unwrap().contains("Blocked host"));
    }

    #[test]
    fn test_check_ssrf_blocks_ipv4_compatible_loopback() {
        // ::127.0.0.1 — deprecated IPv4-compatible form; defense-in-depth.
        let result = check_ssrf("http://[::127.0.0.1]/");
        assert!(result.is_some(), "::127.0.0.1 must be blocked");
    }

    #[test]
    fn test_check_ssrf_blocks_zero_dot_zero() {
        // 0.0.0.0 — connects to localhost on Linux.
        let result = check_ssrf("http://0.0.0.0/");
        assert!(result.is_some());
    }

    #[test]
    fn test_is_private_ip_unspecified_v4_v6() {
        assert!(is_private_ip(&IpAddr::V4(Ipv4Addr::UNSPECIFIED)));
        assert!(is_private_ip(&IpAddr::V6(Ipv6Addr::UNSPECIFIED)));
    }

    #[test]
    fn test_is_private_ip_blocks_multicast_and_broadcast() {
        assert!(is_private_ip(&IpAddr::V4(Ipv4Addr::new(239, 0, 0, 1))));
        assert!(is_private_ip(&IpAddr::V4(Ipv4Addr::BROADCAST)));
    }

    #[test]
    fn test_embedded_ipv4_compatibility() {
        // IPv4-compatible: ::a.b.c.d
        let v6: Ipv6Addr = "::127.0.0.1".parse().unwrap();
        assert_eq!(embedded_ipv4(&v6), Some(Ipv4Addr::new(127, 0, 0, 1)));
        // ::1 must NOT be treated as IPv4-compatible
        assert_eq!(embedded_ipv4(&Ipv6Addr::LOCALHOST), None);
        // :: must NOT be treated as IPv4-compatible
        assert_eq!(embedded_ipv4(&Ipv6Addr::UNSPECIFIED), None);
        // Mapped form
        let v6: Ipv6Addr = "::ffff:127.0.0.1".parse().unwrap();
        assert_eq!(embedded_ipv4(&v6), Some(Ipv4Addr::new(127, 0, 0, 1)));
    }
}
