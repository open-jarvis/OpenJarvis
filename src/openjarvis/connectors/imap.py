"""Generic IMAP email connector for any provider."""

from __future__ import annotations

import imaplib
import ipaddress
import socket
import ssl
from datetime import datetime
from typing import Iterator, Optional

from openjarvis.connectors._stubs import Document
from openjarvis.connectors.gmail_imap import (
    _IMAP_TIMEOUT_SECONDS,
    _SECURITY_STARTTLS,
    _SECURITY_TLS,
    GmailIMAPConnector,
)
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry

_DEFAULT_CREDENTIALS_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "imap.json")

_PROVIDER_HOSTS = {
    "gmail.com": "imap.gmail.com",
    "googlemail.com": "imap.gmail.com",
    "outlook.com": "outlook.office365.com",
    "hotmail.com": "outlook.office365.com",
    "live.com": "outlook.office365.com",
    "icloud.com": "imap.mail.me.com",
    "me.com": "imap.mail.me.com",
    "yahoo.com": "imap.mail.yahoo.com",
    "fastmail.com": "imap.fastmail.com",
    "aol.com": "imap.aol.com",
    "zoho.com": "imap.zoho.com",
    "gmx.com": "imap.gmx.com",
}

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata.google.com",
    }
)


def _normalize_hostname(host: str) -> str:
    """Normalize and validate a host without accepting URL-like input."""
    normalized = host.strip().rstrip(".")
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    if not normalized or any(char.isspace() for char in normalized):
        raise ValueError("A valid IMAP hostname is required")
    if any(char in normalized for char in ("/", "\\", "@")) or "://" in normalized:
        raise ValueError("IMAP host must be a hostname or IP address, not a URL")

    try:
        return str(ipaddress.ip_address(normalized))
    except ValueError:
        pass

    try:
        ascii_host = normalized.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("A valid IMAP hostname is required") from exc
    labels = ascii_host.split(".")
    if len(ascii_host) > 253 or any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not all(char.isalnum() or char == "-" for char in label)
        for label in labels
    ):
        raise ValueError("A valid IMAP hostname is required")
    return ascii_host


def _is_public_address(address: str) -> bool:
    """Return whether an address is globally routable unicast."""
    parsed = ipaddress.ip_address(address)
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    # ``is_global`` alone is insufficient: Python classifies multicast ranges
    # as global even though they are not valid remote unicast endpoints.
    return parsed.is_global and not any(
        (
            parsed.is_multicast,
            parsed.is_reserved,
            parsed.is_unspecified,
            parsed.is_loopback,
            parsed.is_link_local,
            parsed.is_private,
        )
    )


def validate_imap_endpoint(host: str, port: int) -> tuple[str, tuple[str, ...]]:
    """Resolve a public IMAP endpoint and return addresses safe to pin.

    All resolved addresses must be globally routable. Returning the resolved
    addresses lets the socket layer pin one of the checked IPs, closing the
    DNS-rebinding gap between policy validation and connection establishment.
    """
    normalized = _normalize_hostname(host)
    lowered = normalized.lower()
    if (
        lowered in _BLOCKED_HOSTNAMES
        or lowered.endswith(".localhost")
        or lowered.endswith(".local")
        or lowered.endswith(".internal")
    ):
        raise ValueError("Private or local IMAP hosts are not allowed")

    try:
        resolved = socket.getaddrinfo(
            normalized,
            port,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError(f"Unable to resolve IMAP host '{normalized}'") from exc

    addresses: list[str] = []
    for _, _, _, _, sockaddr in resolved:
        address = sockaddr[0]
        if not _is_public_address(address):
            raise ValueError("Private or non-public IMAP addresses are not allowed")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise ValueError(f"Unable to resolve IMAP host '{normalized}'")
    return normalized, tuple(addresses)


def _create_pinned_socket(address: str, port: int, timeout: float | None):
    """Create a socket to an already policy-checked IP literal."""
    if timeout is not None and not timeout:
        raise ValueError("Non-blocking sockets are not supported")
    if timeout is None:
        return socket.create_connection((address, port))
    return socket.create_connection((address, port), timeout)


class _PinnedIMAP4(imaplib.IMAP4):
    """Plain IMAP transport pinned to a previously validated address."""

    def __init__(
        self,
        host: str,
        port: int,
        pinned_address: str,
        *,
        timeout: float | None = None,
    ) -> None:
        self._pinned_address = pinned_address
        super().__init__(host, port, timeout)

    def _create_socket(self, timeout):
        return _create_pinned_socket(self._pinned_address, self.port, timeout)


class _PinnedIMAP4SSL(imaplib.IMAP4_SSL):
    """Implicit-TLS IMAP transport with DNS-pinned TCP and hostname TLS."""

    def __init__(
        self,
        host: str,
        port: int,
        pinned_address: str,
        *,
        ssl_context: ssl.SSLContext,
        timeout: float | None = None,
    ) -> None:
        self._pinned_address = pinned_address
        super().__init__(host, port, ssl_context=ssl_context, timeout=timeout)

    def _create_socket(self, timeout):
        sock = _create_pinned_socket(self._pinned_address, self.port, timeout)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


def resolve_imap_host(email_address: str) -> str:
    """Resolve the IMAP host for an email address from its domain."""
    domain = email_address.rsplit("@", 1)[-1].lower() if "@" in email_address else ""
    if not domain:
        return ""
    return _PROVIDER_HOSTS.get(domain, f"imap.{domain}")


@ConnectorRegistry.register("imap")
class IMAPConnector(GmailIMAPConnector):
    """Generic IMAP connector for any email provider."""

    connector_id = "imap"
    display_name = "Email (IMAP)"
    _default_imap_host = ""

    def __init__(
        self,
        email_address: str = "",
        app_password: str = "",
        credentials_path: str = "",
        *,
        imap_host: str = "",
        imap_port: int | None = None,
        imap_security: str = "",
        max_messages: Optional[int] = None,
    ) -> None:
        super().__init__(
            email_address,
            app_password,
            credentials_path or _DEFAULT_CREDENTIALS_PATH,
            imap_host=imap_host,
            imap_port=imap_port,
            imap_security=imap_security,
            max_messages=max_messages,
        )

    def auth_url(self) -> str:
        return ""

    def _host_for_email(self, email_address: str) -> str:
        return resolve_imap_host(email_address)

    def _make_imap_client(self, host: str, port: int, security: str) -> imaplib.IMAP4:
        """Connect only to a DNS-pinned, globally routable endpoint."""
        normalized_host, addresses = validate_imap_endpoint(host, port)
        tls_context = ssl.create_default_context()
        last_error: Exception | None = None
        for address in addresses:
            try:
                if security == _SECURITY_TLS:
                    return _PinnedIMAP4SSL(
                        normalized_host,
                        port,
                        address,
                        ssl_context=tls_context,
                        timeout=_IMAP_TIMEOUT_SECONDS,
                    )

                if security != _SECURITY_STARTTLS:
                    raise ValueError("IMAP security must be 'tls' or 'starttls'")
                imap = _PinnedIMAP4(
                    normalized_host,
                    port,
                    address,
                    timeout=_IMAP_TIMEOUT_SECONDS,
                )
                try:
                    status, _ = imap.starttls(ssl_context=tls_context)
                    if status != "OK":
                        raise imaplib.IMAP4.error("IMAP server rejected STARTTLS")
                    return imap
                except Exception:
                    self._close_imap(imap)
                    raise
            except (imaplib.IMAP4.error, OSError) as exc:
                last_error = exc

        if last_error is not None:
            raise last_error
        raise OSError(f"Unable to connect to IMAP host '{normalized_host}'")

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        for doc in super().sync(since=since, cursor=cursor):
            doc.source = self.connector_id
            doc.doc_id = doc.doc_id.replace("gmail:", f"{self.connector_id}:", 1)
            # A generic mailbox must not link every result to Gmail.
            doc.url = ""
            yield doc

    def mcp_tools(self) -> list:
        """Do not expose Gmail-branded live tools for non-Gmail mailboxes."""
        return []
