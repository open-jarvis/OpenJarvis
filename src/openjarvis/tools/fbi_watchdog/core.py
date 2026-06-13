"""Simplified FBI Watchdog scan engine for OpenJarvis integration.

Core scanning modules extracted from fbi_watchdog.py without CLI output,
Discord/Telegram alerting, or screenshot capture. Returns pure JSON results.
"""

from __future__ import annotations

import hashlib
import ipaddress
import random
import socket
from datetime import datetime, timezone
from typing import Any

try:
    import dns.resolver
except ImportError:
    dns = None  # type: ignore

import requests

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0",
]

DNS_RECORDS = ["A", "AAAA", "CNAME", "MX", "NS", "TXT"]
DNS_TIMEOUT = 5
REQUEST_TIMEOUT = 15


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_ip(target: str) -> bool:
    try:
        ipaddress.ip_address(target)
        return True
    except ValueError:
        return False


def dns_scan(domain: str) -> dict[str, Any]:
    """Query DNS records for a domain."""
    result: dict[str, Any] = {
        "module": "dns",
        "target": domain,
        "timestamp": _now(),
        "records": {},
        "errors": [],
    }

    if dns is None:
        result["errors"].append("dnspython not installed: pip install dnspython")
        return result

    for record_type in DNS_RECORDS:
        try:
            answers = dns.resolver.resolve(domain, record_type, lifetime=DNS_TIMEOUT)
            records = sorted([r.to_text() for r in answers])
            result["records"][record_type] = records
        except dns.resolver.NXDOMAIN:
            result["errors"].append(f"{record_type}: NXDOMAIN")
        except dns.resolver.Timeout:
            result["errors"].append(f"{record_type}: timeout")
        except dns.resolver.NoAnswer:
            pass  # No answer is normal for some record types
        except Exception as exc:
            result["errors"].append(f"{record_type}: {exc}")

    return result


def http_scan(domain: str) -> dict[str, Any]:
    """Fetch HTTP fingerprint for a domain."""
    result: dict[str, Any] = {
        "module": "http",
        "target": domain,
        "timestamp": _now(),
        "reachable": False,
        "https": False,
        "status_code": None,
        "final_url": None,
        "headers": {},
        "body_hash": None,
        "body_size": None,
        "errors": [],
    }

    headers = {"User-Agent": random.choice(USER_AGENTS)}

    for scheme in ["https", "http"]:
        try:
            resp = requests.get(
                f"{scheme}://{domain}",
                timeout=REQUEST_TIMEOUT,
                headers=headers,
                allow_redirects=True,
                stream=True,
                verify=(scheme == "https"),
            )

            result["reachable"] = True
            result["https"] = scheme == "https"
            result["status_code"] = resp.status_code
            result["final_url"] = resp.url

            # Selected headers
            for key in ["server", "x-powered-by", "x-frame-options",
                        "strict-transport-security", "x-content-type-options",
                        "via", "x-cdn"]:
                val = resp.headers.get(key)
                if val:
                    result["headers"][key] = val

            # Body hash (first 1 MB)
            hasher = hashlib.sha256()
            size = 0
            limit = 1024 * 1024
            for chunk in resp.iter_content(chunk_size=65536):
                size += len(chunk)
                hasher.update(chunk)
                if size >= limit:
                    break
            result["body_hash"] = hasher.hexdigest()
            result["body_size"] = size

            return result

        except requests.exceptions.SSLError:
            result["errors"].append(f"{scheme}: SSL error")
        except requests.exceptions.ConnectionError:
            result["errors"].append(f"{scheme}: connection error")
        except requests.exceptions.Timeout:
            result["errors"].append(f"{scheme}: timeout")
        except requests.exceptions.RequestException as exc:
            result["errors"].append(f"{scheme}: {exc}")

    return result


def whois_scan(domain: str) -> dict[str, Any]:
    """Query WHOIS for domain registration info."""
    result: dict[str, Any] = {
        "module": "whois",
        "target": domain,
        "timestamp": _now(),
        "registrar": None,
        "creation_date": None,
        "expiration_date": None,
        "name_servers": None,
        "privacy_protected": False,
        "seizure_indicators": [],
        "errors": [],
    }

    try:
        import whois  # type: ignore

        w = whois.whois(domain)
        result["registrar"] = str(w.registrar) if w.registrar else None
        result["creation_date"] = str(w.creation_date) if w.creation_date else None
        result["expiration_date"] = str(w.expiration_date) if w.expiration_date else None
        result["name_servers"] = w.name_servers if w.name_servers else None

        # Privacy detection
        privacy_orgs = [
            "withheld for privacy", "privacy service", "whoisguard",
            "domains by proxy", "redacted for privacy", "data protected",
            "privacy protect", "perfect privacy",
        ]
        raw_text = str(w).lower()
        result["privacy_protected"] = any(org in raw_text for org in privacy_orgs)

        # Seizure detection
        seizure_indicators = [
            "department of justice", "u.s. government", "law enforcement",
            "seized", "europol", "interpol", "fbi", "ice homeland security",
            "forfeiture", "usdoj", "justice gov", "usssdomainseizure",
        ]
        result["seizure_indicators"] = [
            ind for ind in seizure_indicators if ind in raw_text
        ]

    except Exception as exc:
        result["errors"].append(str(exc))

    return result


def ip_scan(ip: str) -> dict[str, Any]:
    """Query IP geolocation and reverse DNS."""
    result: dict[str, Any] = {
        "module": "ip",
        "target": ip,
        "timestamp": _now(),
        "reverse_dns": None,
        "geolocation": {},
        "asn": {},
        "errors": [],
    }

    # Reverse DNS
    try:
        result["reverse_dns"] = socket.gethostbyaddr(ip)[0]
    except Exception:
        pass

    # Geo + ASN via ip-api.com (free, no key required)
    try:
        resp = requests.get(
            f"http://ip-api.com/json/{ip}",
            timeout=REQUEST_TIMEOUT,
        )
        data = resp.json()
        if data.get("status") == "success":
            result["geolocation"] = {
                "country": data.get("country"),
                "region": data.get("regionName"),
                "city": data.get("city"),
                "zip": data.get("zip"),
                "lat": data.get("lat"),
                "lon": data.get("lon"),
                "isp": data.get("isp"),
                "org": data.get("org"),
            }
            result["asn"] = {
                "asn": data.get("as"),
            }
        else:
            result["errors"].append(f"ip-api: {data.get('message', 'unknown')}")
    except Exception as exc:
        result["errors"].append(f"ip-api: {exc}")

    return result


def run_scan(target: str, modules: list[str]) -> dict[str, Any]:
    """Run selected scan modules against a target.

    Args:
        target: Domain, IP, or hostname to scan.
        modules: List of modules to run. Options: dns, http, whois, ip.

    Returns:
        Dict with results per module and summary.
    """
    results: dict[str, Any] = {
        "target": target,
        "timestamp": _now(),
        "modules": modules,
        "results": {},
        "summary": {
            "reachable": False,
            "privacy_protected": False,
            "seizure_detected": False,
            "errors": 0,
        },
    }

    is_ip_target = _is_ip(target)

    for module in modules:
        if module == "dns" and not is_ip_target:
            results["results"]["dns"] = dns_scan(target)
        elif module == "http" and not is_ip_target:
            results["results"]["http"] = http_scan(target)
        elif module == "whois" and not is_ip_target:
            results["results"]["whois"] = whois_scan(target)
        elif module == "ip":
            ip_target = target if is_ip_target else None
            if ip_target is None:
                # Resolve domain to IP
                try:
                    ip_target = socket.gethostbyname(target)
                except Exception as exc:
                    results["results"]["ip"] = {
                        "module": "ip",
                        "target": target,
                        "timestamp": _now(),
                        "errors": [f"resolve failed: {exc}"],
                    }
                    continue
            results["results"]["ip"] = ip_scan(ip_target)
        else:
            results["results"][module] = {
                "module": module,
                "target": target,
                "timestamp": _now(),
                "errors": ["module skipped for target type"],
            }

    # Build summary
    for mod_result in results["results"].values():
        if mod_result.get("reachable"):
            results["summary"]["reachable"] = True
        if mod_result.get("privacy_protected"):
            results["summary"]["privacy_protected"] = True
        if mod_result.get("seizure_indicators"):
            if len(mod_result["seizure_indicators"]) > 0:
                results["summary"]["seizure_detected"] = True
        results["summary"]["errors"] += len(mod_result.get("errors", []))

    return results
