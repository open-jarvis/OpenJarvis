"""Generic IMAP email connector for any provider."""

from __future__ import annotations

from datetime import datetime
from typing import Iterator, Optional

from openjarvis.connectors._stubs import Document
from openjarvis.connectors.gmail_imap import GmailIMAPConnector
from openjarvis.connectors.oauth import load_tokens, save_tokens
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
        max_messages: Optional[int] = None,
    ) -> None:
        super().__init__(
            email_address,
            app_password,
            credentials_path or _DEFAULT_CREDENTIALS_PATH,
            imap_host=imap_host,
            max_messages=max_messages,
        )

    def auth_url(self) -> str:
        return ""

    def handle_callback(self, code: str) -> None:
        # code format: "email:password"
        if ":" in code:
            email_addr, password = code.split(":", 1)
            email_addr, password = email_addr.strip(), password.strip()
        else:
            email_addr, password = "", code.strip()
        save_tokens(
            self._credentials_path,
            {
                "email": email_addr,
                "password": password,
                "imap_host": resolve_imap_host(email_addr),
            },
        )

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        if not self._imap_host:
            tokens = load_tokens(self._credentials_path) or {}
            self._imap_host = tokens.get("imap_host", "") or resolve_imap_host(
                tokens.get("email", "")
            )
        for doc in super().sync(since=since, cursor=cursor):
            doc.source = self.connector_id
            doc.doc_id = doc.doc_id.replace("gmail:", f"{self.connector_id}:", 1)
            yield doc
