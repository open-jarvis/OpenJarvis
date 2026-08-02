"""Policy, injection protection, artifacts, and browser action verification."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import mimetypes
import re
import socket
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from openjarvis.browser.cdp import BrowserObservation
from openjarvis.browser.models import BrowserSession
from openjarvis.security.file_policy import is_sensitive_file
from openjarvis.tasks.policy import RiskLevel
from openjarvis.tools.safe_filesystem import SecurePathPolicy


class BrowserPolicyError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class InjectionAssessment:
    clean: bool
    risk_level: RiskLevel
    findings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BrowserArtifact:
    artifact_id: str
    kind: str
    path: str
    sha256: str
    size_bytes: int
    media_type: str


@dataclass(frozen=True, slots=True)
class BrowserActionResult:
    verified: bool
    observation: BrowserObservation
    verification: str
    injection: InjectionAssessment
    artifact: BrowserArtifact | None = None


class BrowserNetworkPolicy:
    """Phase-5 browser network policy: explicit loopback ports only."""

    def __init__(self, allowed_loopback_ports: frozenset[int]) -> None:
        if not allowed_loopback_ports:
            raise ValueError("at least one loopback test port is required")
        self.allowed_loopback_ports = allowed_loopback_ports

    def validate(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise BrowserPolicyError("only HTTP(S) URLs are allowed")
        if parsed.username or parsed.password:
            raise BrowserPolicyError("URL credentials are blocked")
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise BrowserPolicyError("only explicit loopback test pages are allowed")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in self.allowed_loopback_ports:
            raise BrowserPolicyError("loopback port is not allowlisted")
        return url


class PublicBrowserNetworkPolicy:
    """Allow HTTPS research while rejecting local, private, and credential URLs."""

    def __init__(self, *, allowed_ports: frozenset[int] = frozenset({443})) -> None:
        if not allowed_ports:
            raise ValueError("at least one public HTTPS port is required")
        self.allowed_ports = allowed_ports

    def validate(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise BrowserPolicyError("public research requires an HTTPS URL")
        if parsed.username or parsed.password:
            raise BrowserPolicyError("URL credentials are blocked")
        port = parsed.port or 443
        if port not in self.allowed_ports:
            raise BrowserPolicyError("public research port is not allowlisted")
        host = parsed.hostname.rstrip(".")
        if host.casefold() == "localhost" or not host:
            raise BrowserPolicyError("local browser destinations are blocked")
        try:
            addresses = {
                item[4][0].split("%", 1)[0]
                for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            }
        except OSError as exc:
            raise BrowserPolicyError(
                "public browser destination did not resolve"
            ) from exc
        if not addresses or any(
            not ipaddress.ip_address(address).is_global for address in addresses
        ):
            raise BrowserPolicyError("non-public browser destination is blocked")
        return url


class WebInjectionGuard:
    """Treat website content as data and raise risk on injection patterns."""

    _PATTERNS = (
        (
            re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior).*instructions"),
            "override",
        ),
        (re.compile(r"(?i)(disable|bypass).*security"), "security_bypass"),
        (
            re.compile(r"(?i)(send|upload|reveal).*(credential|secret|password)"),
            "secret_request",
        ),
        (
            re.compile(r"(?i)(run|execute).*(powershell|shell|cmd|terminal)"),
            "command_request",
        ),
        (re.compile(r"(?i)always\s+allow|approve\s+this"), "approval_forgery"),
    )

    def scan(self, content: str) -> InjectionAssessment:
        normalised = unicodedata.normalize("NFKC", content)
        candidates = [normalised]
        for token in re.findall(r"[A-Za-z0-9+/]{20,}={0,2}", normalised):
            try:
                decoded = base64.b64decode(token, validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                continue
            candidates.append(unicodedata.normalize("NFKC", decoded))
        findings = {
            name
            for candidate in candidates
            for pattern, name in self._PATTERNS
            if pattern.search(candidate)
        }
        return InjectionAssessment(
            clean=not findings,
            risk_level=(
                RiskLevel.READ_ONLY
                if not findings
                else RiskLevel.DESTRUCTIVE_OR_SENSITIVE
            ),
            findings=tuple(sorted(findings)),
        )


class BrowserArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve(strict=False)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(
        self, *, kind: str, data: bytes, suffix: str, media_type: str
    ) -> BrowserArtifact:
        artifact_id = f"browser_artifact_{uuid.uuid4().hex}"
        path = self.root / f"{artifact_id}{suffix}"
        path.write_bytes(data)
        observed = path.read_bytes()
        if observed != data:
            raise OSError("browser artifact verification failed")
        return BrowserArtifact(
            artifact_id=artifact_id,
            kind=kind,
            path=str(path),
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            media_type=media_type,
        )


class BrowserTransferPolicy:
    _EXECUTABLE_SUFFIXES = frozenset(
        {".bat", ".cmd", ".com", ".exe", ".msi", ".ps1", ".scr"}
    )

    def __init__(
        self,
        *,
        download_root: str | Path,
        upload_policy: SecurePathPolicy,
        max_bytes: int = 10_485_760,
    ) -> None:
        self.download_root = Path(download_root).resolve(strict=False)
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.upload_policy = upload_policy
        self.max_bytes = max_bytes

    def validate_upload(self, path: str | Path) -> dict[str, object]:
        value = self.upload_policy.resolve(
            str(path), must_exist=True, allow_directory=False
        )
        size = value.stat().st_size
        if size > self.max_bytes:
            raise BrowserPolicyError("upload exceeds size limit")
        if is_sensitive_file(value):
            raise BrowserPolicyError("sensitive upload is blocked")
        return {
            "path": value,
            "filename": value.name,
            "size_bytes": size,
            "sha256": hashlib.sha256(value.read_bytes()).hexdigest(),
        }

    def verify_download(self, path: str | Path) -> BrowserArtifact:
        value = Path(path).resolve(strict=True)
        try:
            value.relative_to(self.download_root)
        except ValueError as exc:
            raise BrowserPolicyError("download escaped isolated root") from exc
        if value.suffix.casefold() in self._EXECUTABLE_SUFFIXES:
            raise BrowserPolicyError("executable download is quarantined")
        size = value.stat().st_size
        if size > self.max_bytes:
            raise BrowserPolicyError("download exceeds size limit")
        media_type = mimetypes.guess_type(value.name)[0] or "application/octet-stream"
        data = value.read_bytes()
        return BrowserArtifact(
            artifact_id=f"download_{uuid.uuid4().hex}",
            kind="download",
            path=str(value),
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=size,
            media_type=media_type,
        )


class BrowserActionVerifier:
    @staticmethod
    def navigation(
        observation: BrowserObservation,
        *,
        expected_url: str,
        expected_title: str | None = None,
    ) -> str:
        if observation.url != expected_url:
            raise BrowserPolicyError(
                f"navigation URL mismatch: {observation.url!r} != {expected_url!r}"
            )
        if observation.ready_state not in {"interactive", "complete"}:
            raise BrowserPolicyError("document is not ready")
        if expected_title is not None and observation.title != expected_title:
            raise BrowserPolicyError("navigation title mismatch")
        return "URL, document state, and title were observed"

    @staticmethod
    def click(
        before: BrowserObservation,
        after: BrowserObservation,
        *,
        expected_text: str | None = None,
    ) -> str:
        changed = (before.url, before.title, before.text) != (
            after.url,
            after.title,
            after.text,
        )
        if expected_text is not None and expected_text not in after.text:
            raise BrowserPolicyError("expected post-click text was not observed")
        if not changed:
            raise BrowserPolicyError("click produced no observable state change")
        return "post-click state change was observed"

    @staticmethod
    def input(actual: str | None, expected: str) -> str:
        if actual != expected:
            raise BrowserPolicyError(
                f"input value mismatch: {actual!r} != {expected!r}"
            )
        return "field value exactly matches the proposed input"


class BrowserToolAdapter:
    """High-level actions that always perform policy and verification."""

    def __init__(
        self,
        *,
        session: BrowserSession,
        control,
        network_policy: BrowserNetworkPolicy,
        transfer_policy: BrowserTransferPolicy,
        artifact_store: BrowserArtifactStore,
        injection_guard: WebInjectionGuard | None = None,
    ) -> None:
        self.session = session
        self.control = control
        self.network = network_policy
        self.transfers = transfer_policy
        self.artifacts = artifact_store
        self.injection = injection_guard or WebInjectionGuard()
        self.verifier = BrowserActionVerifier()

    def observe(self) -> tuple[BrowserObservation, InjectionAssessment]:
        observation = self.control.snapshot()
        return observation, self.injection.scan(observation.text)

    def navigate(
        self, url: str, *, expected_title: str | None = None
    ) -> BrowserActionResult:
        target = self.network.validate(url)
        self.session.safe_checkpoint = "before.navigation"
        observation = self.control.navigate(target)
        verification = self.verifier.navigation(
            observation, expected_url=target, expected_title=expected_title
        )
        assessment = self.injection.scan(observation.text)
        self.session.safe_checkpoint = "after.navigation.verified"
        return BrowserActionResult(True, observation, verification, assessment)

    def click(
        self,
        selector: str,
        *,
        expected_text: str | None = None,
        approved_submit: bool = False,
    ) -> BrowserActionResult:
        before, assessment = self.observe()
        if not assessment.clean:
            raise BrowserPolicyError("website injection blocked browser action")
        info = self.control.element_info(selector)
        if not info or not info.get("visible"):
            raise BrowserPolicyError("click target is missing or not visible")
        if info.get("type") == "submit" and not approved_submit:
            raise BrowserPolicyError("form submission requires allow-once")
        self.session.safe_checkpoint = "before.click"
        self.session.effect_known = False
        after = self.control.click(selector)
        verification = self.verifier.click(before, after, expected_text=expected_text)
        self.session.effect_known = True
        self.session.safe_checkpoint = "after.click.verified"
        return BrowserActionResult(True, after, verification, assessment)

    def fill(self, selector: str, text: str) -> BrowserActionResult:
        before, assessment = self.observe()
        if not assessment.clean:
            raise BrowserPolicyError("website injection blocked browser action")
        self.session.safe_checkpoint = "before.input"
        after = self.control.fill(selector, text)
        actual = self.control.value(selector)
        verification = self.verifier.input(actual, text)
        self.session.safe_checkpoint = "after.input.verified"
        return BrowserActionResult(True, after, verification, assessment)

    def screenshot(self) -> BrowserActionResult:
        observation, assessment = self.observe()
        artifact = self.artifacts.put(
            kind="browser_screenshot",
            data=self.control.screenshot(),
            suffix=".png",
            media_type="image/png",
        )
        return BrowserActionResult(
            True,
            observation,
            "page-only screenshot was hashed and stored out of line",
            assessment,
            artifact,
        )

    def prepare_upload(self, selector: str, path: str | Path) -> dict[str, object]:
        _, assessment = self.observe()
        if not assessment.clean:
            raise BrowserPolicyError("website injection blocked upload preparation")
        file_info = self.transfers.validate_upload(path)
        observed_name = self.control.prepare_upload(selector, file_info["path"])
        if observed_name != file_info["filename"]:
            raise BrowserPolicyError("selected upload filename was not observed")
        return {**file_info, "prepared": True, "submitted": False}

    def prepare_downloads(self) -> dict[str, object]:
        self.control.prepare_downloads(self.transfers.download_root)
        return {"download_root": str(self.transfers.download_root), "opened": False}


__all__ = [
    "BrowserActionResult",
    "BrowserActionVerifier",
    "BrowserArtifact",
    "BrowserArtifactStore",
    "BrowserNetworkPolicy",
    "BrowserPolicyError",
    "PublicBrowserNetworkPolicy",
    "BrowserToolAdapter",
    "BrowserTransferPolicy",
    "InjectionAssessment",
    "WebInjectionGuard",
]
