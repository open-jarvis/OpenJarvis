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

/// Check if an IP address is private/reserved.
pub fn is_private_ip(ip: &IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => {
            v4.is_loopback()
                || v4.is_private()
                || v4.is_link_local()
                || is_in_cidr_v4(v4, Ipv4Addr::new(169, 254, 0, 0), 16)
                || *v4 == Ipv4Addr::UNSPECIFIED
        }
        IpAddr::V6(v6) => {
            // IPv4-mapped IPv6 (::ffff:a.b.c.d) addresses must be classified
            // by the embedded IPv4 address — otherwise the IPv6 checks below
            // never match loopback / RFC1918 / link-local ranges and the
            // address is treated as public, allowing SSRF bypass.
            if let Some(v4) = v6.to_ipv4_mapped() {
                return is_private_ip(&IpAddr::V4(v4));
            }
            v6.is_loopback()
                || v6.is_unspecified()
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

    let hostname = match parsed.host_str() {
        Some(h) => h,
        None => return Some("No hostname in URL".into()),
    };

    if BLOCKED_HOSTS.contains(hostname) {
        return Some(format!(
            "Blocked host: {} (cloud metadata endpoint)",
            hostname
        ));
    }

    // If the hostname is itself an IP literal, classify it directly.
    // This is required for IPv6 literals (including IPv4-mapped forms like
    // `::ffff:127.0.0.1`) because `to_socket_addrs()` does not accept the
    // unbracketed `host:port` string we would otherwise build below — without
    // this branch a literal IPv6 address never reaches `is_private_ip`.
    if let Ok(ip) = hostname.parse::<IpAddr>() {
        // Normalize IPv4-mapped IPv6 to its embedded IPv4 so the metadata
        // host check below catches e.g. `::ffff:169.254.169.254`.
        let normalized = match ip {
            IpAddr::V6(v6) => v6.to_ipv4_mapped().map(IpAddr::V4).unwrap_or(ip),
            v4 => v4,
        };
        if let IpAddr::V4(v4) = normalized {
            let v4_str = v4.to_string();
            if BLOCKED_HOSTS.contains(v4_str.as_str()) {
                return Some(format!(
                    "Blocked host: {} (cloud metadata endpoint)",
                    v4_str
                ));
            }
        }
        if is_private_ip(&ip) {
            return Some(format!("URL resolves to private IP: {}", ip));
        }
        return None;
    }

    let port = parsed.port().unwrap_or(match parsed.scheme() {
        "https" => 443,
        _ => 80,
    });

    let addr_str = format!("{}:{}", hostname, port);
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
}
