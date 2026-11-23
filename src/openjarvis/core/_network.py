"""Classify configured inference endpoints without resolving or contacting them."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)


def _endpoint_hostname(endpoint: object) -> str | None:
    if (
        not isinstance(endpoint, str)
        or not endpoint
        or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in endpoint)
    ):
        return None
    # Support a bare IPv6 literal as well as normal URL authorities.
    try:
        return str(ipaddress.ip_address(endpoint))
    except ValueError:
        pass
    try:
        parsed = urlsplit(endpoint if "://" in endpoint else "//" + endpoint)
        if parsed.scheme not in ("", "http", "https"):
            return None
        hostname = parsed.hostname
        parsed.port  # Validate malformed/out-of-range ports too.
        authority = parsed.netloc.rsplit("@", 1)[-1]
        if authority.startswith("["):
            suffix = authority[authority.index("]") + 1 :]
            if suffix and (not suffix.startswith(":") or not suffix[1:].isdigit()):
                return None
        if not hostname or hostname.endswith(".."):
            return None
        return hostname.lower().removesuffix(".")
    except ValueError:
        return None


def _address(hostname: str):
    try:
        address = ipaddress.ip_address(hostname)
        return (
            address.ipv4_mapped
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped
            else address
        )
    except ValueError:
        return None


def endpoint_is_loopback(endpoint: object) -> bool:
    """Whether a configured endpoint identifies this machine, without DNS."""
    hostname = _endpoint_hostname(endpoint)
    if hostname is None:
        return False
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    address = _address(hostname)
    return address is not None and (address.is_loopback or address.is_unspecified)


def endpoint_is_local_network(endpoint: object) -> bool:
    """Whether an endpoint is loopback or explicitly a private/local-network host.

    NIM may be self-hosted on a LAN. This classification does not claim the
    endpoint is on this device; diagnostics use endpoint_is_loopback instead.
    Unknown or malformed endpoints conservatively remain remote.
    """
    if endpoint_is_loopback(endpoint):
        return True
    hostname = _endpoint_hostname(endpoint)
    if hostname is None:
        return False
    if hostname.endswith(".local") and hostname != ".local":
        return True
    address = _address(hostname)
    return address is not None and any(
        address.version == network.version and address in network
        for network in _PRIVATE_NETWORKS
    )
