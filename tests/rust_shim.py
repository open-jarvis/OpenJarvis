"""Test-only shim for the ``openjarvis_rust`` module.

This module provides a lightweight Python implementation of the subset of
Rust extension APIs used by unit tests, so local test runs can proceed when
the compiled extension is unavailable.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import ipaddress
import json
import math
import os
import re
import socket
import subprocess
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Optional
from urllib.parse import urlparse

PatternDef = tuple[str, re.Pattern[str], str, str]

_SENSITIVE_PATTERNS = (
    ".env",
    ".env.*",
    "*.env",
    ".secret",
    "*.secrets",
    "credentials.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "id_rsa",
    "id_ed25519",
    ".htpasswd",
    ".pgpass",
    ".netrc",
)

_BLOCKED_HOSTS = frozenset(
    {
        "169.254.169.254",
        "metadata.google.internal",
        "metadata.google.com",
        "100.100.100.200",
    }
)

_BLOCKED_CIDR = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _embedded_ipv4(addr: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    mapped = addr.ipv4_mapped
    if mapped is not None:
        return mapped
    packed = addr.packed
    if (
        packed[:12] == b"\x00" * 12
        and addr != ipaddress.IPv6Address("::")
        and addr != ipaddress.IPv6Address("::1")
    ):
        return ipaddress.IPv4Address(packed[12:])
    return None


def _is_private_ip(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(addr)
        if embedded is not None:
            addr = embedded
    return any(addr in net for net in _BLOCKED_CIDR)


class _BaseMemory:
    def __init__(self, *, hex_ids: bool) -> None:
        self._hex_ids = hex_ids
        self._docs: list[dict[str, Any]] = []
        self._index: dict[str, int] = {}

    def _new_id(self) -> str:
        return uuid.uuid4().hex if self._hex_ids else str(uuid.uuid4())

    def store(self, content: str, source: str = "", metadata: str | None = None) -> str:
        doc_id = self._new_id()
        meta: dict[str, Any]
        if metadata:
            try:
                meta = json.loads(metadata)
            except json.JSONDecodeError:
                meta = {}
        else:
            meta = {}
        self._index[doc_id] = len(self._docs)
        self._docs.append(
            {
                "id": doc_id,
                "content": content,
                "source": source,
                "metadata": meta,
                "deleted": False,
                "tokens": _tokenize(content),
            }
        )
        return doc_id

    def retrieve(self, query: str, top_k: int = 5) -> str:
        q_tokens = set(_tokenize(query))
        if not q_tokens:
            return "[]"
        scored: list[tuple[float, dict[str, Any]]] = []
        for doc in self._docs:
            if doc["deleted"]:
                continue
            d_tokens = set(doc["tokens"])
            overlap = len(q_tokens & d_tokens)
            if overlap == 0:
                continue
            score = overlap / max(1, len(q_tokens))
            scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        payload = [
            {
                "content": doc["content"],
                "score": float(score),
                "source": doc["source"],
                "metadata": doc["metadata"],
            }
            for score, doc in scored[: max(0, int(top_k))]
        ]
        return json.dumps(payload)

    def delete(self, doc_id: str) -> bool:
        idx = self._index.get(doc_id)
        if idx is None:
            return False
        if self._docs[idx]["deleted"]:
            return False
        self._docs[idx]["deleted"] = True
        return True

    def clear(self) -> None:
        self._docs.clear()
        self._index.clear()

    def count(self) -> int:
        return sum(1 for d in self._docs if not d["deleted"])


class SQLiteMemory(_BaseMemory):
    def __init__(self, db_path: str) -> None:
        super().__init__(hex_ids=False)
        self._db_path = db_path


class BM25Memory(_BaseMemory):
    def __init__(self) -> None:
        super().__init__(hex_ids=True)


class LoopGuard:
    def __init__(
        self,
        max_identical: int = 50,
        max_ping_pong: int = 4,
        poll_budget: int = 100,
    ):
        self._seen: set[str] = set()
        self._recent: deque[str] = deque(maxlen=max_ping_pong * 2)
        self._poll_count = 0
        self._poll_budget = poll_budget

    def check(self, tool_name: str, arguments: str) -> Optional[str]:
        h = hashlib.sha256(f"{tool_name}|{arguments}".encode("utf-8")).hexdigest()
        if h in self._seen:
            return f"Loop detected: identical call to '{tool_name}' with same arguments"
        self._seen.add(h)

        self._recent.append(tool_name)
        if len(self._recent) >= 4:
            c = list(self._recent)
            n = len(c)
            if (
                c[n - 1] == c[n - 3]
                and c[n - 2] == c[n - 4]
                and c[n - 1] != c[n - 2]
            ):
                return f"Ping-pong loop detected between '{c[n - 1]}' and '{c[n - 2]}'"

        self._poll_count += 1
        if self._poll_count > self._poll_budget:
            return (
                f"Poll budget exceeded: {self._poll_count} calls made "
                f"(budget: {self._poll_budget})"
            )
        return None

    def reset(self) -> None:
        self._seen.clear()
        self._recent.clear()
        self._poll_count = 0


def _scan_with_patterns(
    text: str,
    patterns: list[PatternDef],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for name, regex, threat, description in patterns:
        for m in regex.finditer(text):
            findings.append(
                {
                    "pattern_name": name,
                    "matched_text": m.group(0),
                    "threat_level": threat,
                    "start": m.start(),
                    "end": m.end(),
                    "description": description,
                }
            )
    return findings


def _redact_with_patterns(text: str, patterns: list[PatternDef]) -> str:
    out = text
    for name, regex, _threat, _desc in patterns:
        out = regex.sub(f"[REDACTED:{name}]", out)
    return out


class SecretScanner:
    _patterns = [
        (
            "openai_key",
            re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
            "critical",
            "OpenAI API key",
        ),
        (
            "anthropic_key",
            re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
            "critical",
            "Anthropic API key",
        ),
        (
            "aws_access_key",
            re.compile(r"AKIA[0-9A-Z]{16}"),
            "critical",
            "AWS access key",
        ),
        (
            "github_token",
            re.compile(r"(?:ghp|gho|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}"),
            "critical",
            "GitHub token",
        ),
        (
            "password_assignment",
            re.compile(
                r"""(?:password|passwd|pwd)\s*[=:]\s*['"]([^'"]{4,})['"]""",
                re.IGNORECASE,
            ),
            "high",
            "Password assignment",
        ),
        (
            "db_connection_string",
            re.compile(
                r"(?:postgres|mysql|mongodb|redis)://[^\s]{10,}",
                re.IGNORECASE,
            ),
            "high",
            "Database connection string",
        ),
        (
            "private_key",
            re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----"),
            "critical",
            "Private key",
        ),
        (
            "slack_token",
            re.compile(r"xox[bpors]-[A-Za-z0-9\-]{8,}", re.IGNORECASE),
            "high",
            "Slack token",
        ),
        (
            "stripe_key",
            re.compile(r"(?:sk|pk)_(?:test|live)_[A-Za-z0-9]{20,}", re.IGNORECASE),
            "critical",
            "Stripe key",
        ),
        (
            "generic_api_key",
            re.compile(
                r"""(?:api_key|secret_key|auth_token)\s*[=:]\s*['"]([^'"]{8,})['"]""",
                re.IGNORECASE,
            ),
            "high",
            "Generic API key/secret",
        ),
    ]

    def scan(self, text: str) -> str:
        return json.dumps({"findings": _scan_with_patterns(text, self._patterns)})

    def redact(self, text: str) -> str:
        return _redact_with_patterns(text, self._patterns)


class PIIScanner:
    _patterns = [
        (
            "email",
            re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
            "medium",
            "Email address",
        ),
        (
            "us_ssn",
            re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
            "critical",
            "US Social Security Number",
        ),
        (
            "credit_card_visa",
            re.compile(r"\b4\d{3}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
            "critical",
            "Visa credit card",
        ),
        (
            "credit_card_mastercard",
            re.compile(r"\b5[1-5]\d{2}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
            "critical",
            "Mastercard credit card",
        ),
        (
            "credit_card_amex",
            re.compile(r"\b3[47]\d{2}[\s-]?\d{6}[\s-]?\d{5}\b"),
            "critical",
            "Amex credit card",
        ),
        (
            "us_phone",
            re.compile(r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
            "medium",
            "US phone number",
        ),
    ]

    def scan(self, text: str) -> str:
        return json.dumps({"findings": _scan_with_patterns(text, self._patterns)})

    def redact(self, text: str) -> str:
        return _redact_with_patterns(text, self._patterns)


class InjectionScanner:
    _patterns = [
        (
            "prompt_override",
            re.compile(
                r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+"
                r"(instructions?|prompts?|rules?)"
            ),
            "high",
            "Attempt to override system instructions",
        ),
        (
            "identity_override",
            re.compile(r"(?i)you\s+are\s+now\s+(?:a\s+)?(?:different|new|my)"),
            "high",
            "Attempt to change AI identity",
        ),
        (
            "code_injection",
            re.compile(r"(?i)(?:execute|run|eval)\s*\(\s*['\"]"),
            "high",
            "Code execution attempt in prompt",
        ),
        (
            "shell_injection",
            re.compile(
                r"(?:;|\||&&)\s*(?:rm|curl|wget|nc|ncat|bash|sh|python|perl)\s"
            ),
            "high",
            "Shell command injection",
        ),
        (
            "exfiltration",
            re.compile(
                r"(?i)(?:send|post|upload|exfiltrate|transmit)\s+"
                r"(?:(?:to|data|all|everything)\s+)*(?:to\s+)?"
                r"(?:https?://|my\s+server)"
            ),
            "high",
            "Data exfiltration attempt",
        ),
        (
            "jailbreak",
            re.compile(
                r"(?i)(?:DAN|do\s+anything\s+now)\s+"
                r"(?:mode|prompt|jailbreak)"
            ),
            "high",
            "Jailbreak attempt",
        ),
        (
            "restriction_bypass",
            re.compile(
                r"(?i)pretend\s+(?:you\s+)?(?:have\s+)?no\s+"
                r"(?:restrictions?|limitations?|rules?|filters?)"
            ),
            "medium",
            "Restriction bypass attempt",
        ),
        (
            "delimiter_injection",
            re.compile(r"```(?:system|assistant)\b|<\|(?:im_start|im_end|system|assistant)\|>"),
            "high",
            "Delimiter injection",
        ),
    ]

    def scan(self, text: str) -> str:
        findings = _scan_with_patterns(text, self._patterns)
        threat = "low"
        if findings:
            if any(f["threat_level"] == "high" for f in findings):
                threat = "high"
            elif any(f["threat_level"] == "medium" for f in findings):
                threat = "medium"
        return json.dumps(
            {
                "is_clean": len(findings) == 0,
                "findings": findings,
                "threat_level": threat,
            }
        )


@dataclass
class _Grant:
    capability: str
    pattern: str = "*"


class CapabilityPolicy:
    def __init__(self, default_deny: bool = False):
        self._default_deny = default_deny
        self._grants: dict[str, list[_Grant]] = {}
        self._denies: dict[str, list[str]] = {}

    def grant(self, agent_id: str, capability: str, pattern: str = "*") -> None:
        self._grants.setdefault(agent_id, []).append(_Grant(capability, pattern))

    def deny(self, agent_id: str, capability: str) -> None:
        self._denies.setdefault(agent_id, []).append(capability)

    def check(self, agent_id: str, capability: str, resource: str = "") -> bool:
        denies = self._denies.get(agent_id, [])
        if any(fnmatch.fnmatch(capability, d) for d in denies):
            return False
        grants = self._grants.get(agent_id, [])
        for g in grants:
            if fnmatch.fnmatch(capability, g.capability):
                if (
                    g.pattern == "*"
                    or not resource
                    or fnmatch.fnmatch(resource, g.pattern)
                ):
                    return True
        return not self._default_deny


class RateLimiter:
    def __init__(self, requests_per_minute: int = 60, burst_size: int = 10):
        self._rpm = max(1, int(requests_per_minute))
        self._burst = max(1, int(burst_size))
        self._rate = self._rpm / 60.0
        self._state: dict[str, tuple[float, float]] = {}

    def check(self, key: str) -> tuple[bool, float]:
        tokens, last = self._state.get(key, (float(self._burst), time.monotonic()))
        now = time.monotonic()
        tokens = min(float(self._burst), tokens + (now - last) * self._rate)
        if tokens >= 1.0:
            tokens -= 1.0
            self._state[key] = (tokens, now)
            return True, 0.0
        wait = (1.0 - tokens) / self._rate
        self._state[key] = (tokens, now)
        return False, max(0.0, wait)

    def reset(self, key: Optional[str] = None) -> None:
        if key is None:
            self._state.clear()
        else:
            self._state.pop(key, None)


_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}
_UNARYOPS = {ast.UAdd: lambda x: +x, ast.USub: lambda x: -x}
_FUNCS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "log": math.log,
    "ln": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "ceil": math.ceil,
    "floor": math.floor,
    "pi": math.pi,
    "e": math.e,
}


def _eval_math(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_math(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")
    if isinstance(node, ast.BinOp):
        op = type(node.op)
        if op not in _BINOPS:
            raise ValueError(f"Unsupported operator: {op.__name__}")
        return float(_BINOPS[op](_eval_math(node.left), _eval_math(node.right)))
    if isinstance(node, ast.UnaryOp):
        op = type(node.op)
        if op not in _UNARYOPS:
            raise ValueError(f"Unsupported unary operator: {op.__name__}")
        return float(_UNARYOPS[op](_eval_math(node.operand)))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls are allowed")
        fn = node.func.id
        if fn not in _FUNCS:
            raise ValueError(f"Unknown function: {fn}")
        return float(_FUNCS[fn](*[_eval_math(a) for a in node.args]))
    if isinstance(node, ast.Name):
        if node.id in ("pi", "e"):
            return float(_FUNCS[node.id])
        raise ValueError(f"unknown variable: {node.id}")
    raise ValueError(f"Unsupported expression type: {type(node).__name__}")


class CalculatorTool:
    def execute(self, expression: str) -> str:
        expr = (expression or "").replace("^", "**")
        try:
            tree = ast.parse(expr, mode="eval")
            result = _eval_math(tree.body)
            return str(float(result))
        except ZeroDivisionError:
            return "inf"


class FileReadTool:
    def execute(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8", errors="replace")


class FileWriteTool:
    def execute(self, path: str, content: str) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return "ok"


class ThinkTool:
    def execute(self, thought: str) -> str:
        return thought


class ShellExecTool:
    def execute(self, command: str, working_dir: str | None = None) -> str:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=working_dir,
            capture_output=True,
            text=True,
        )
        return (
            f"Exit code: {proc.returncode}\n"
            f"--- stdout ---\n{proc.stdout}\n"
            f"--- stderr ---\n{proc.stderr}"
        )


class HttpRequestTool:
    def execute(self, url: str, method: str = "GET", body: str | None = None) -> str:
        import httpx
        response = httpx.request(
            method,
            url,
            content=body,
            follow_redirects=True,
            timeout=30.0,
        )
        response.raise_for_status()
        return response.text


def _run_git(args: list[str], cwd: str | None = None) -> str:
    result = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git exited {result.returncode}")
    return result.stdout


class GitStatusTool:
    def execute(self, cwd: str | None = None) -> str:
        return _run_git(["status", "--short"], cwd=cwd)


class GitDiffTool:
    def execute(self, cwd: str | None = None) -> str:
        return _run_git(["diff"], cwd=cwd)


class GitLogTool:
    def execute(self, cwd: str | None = None, count: int | None = None) -> str:
        n = int(count or 10)
        return _run_git(["log", "--oneline", f"-{n}"], cwd=cwd)


class OptimizationStore:
    def __init__(self, path: str = ":memory:") -> None:
        self.path = path

    def close(self) -> None:
        pass


def is_sensitive_file(path: str) -> bool:
    p = str(path)
    name = os.path.basename(p)
    for pattern in _SENSITIVE_PATTERNS:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(p, pattern):
            return True
    return False


def check_ssrf(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "Invalid URL"

    host = parsed.hostname
    if host in _BLOCKED_HOSTS:
        return f"Blocked host: {host} (cloud metadata endpoint)"

    try:
        addr = ipaddress.ip_address(host)
        if isinstance(addr, ipaddress.IPv6Address):
            embedded = _embedded_ipv4(addr)
            if embedded is not None and str(embedded) in _BLOCKED_HOSTS:
                return f"Blocked host: {embedded} (cloud metadata endpoint)"
        if _is_private_ip(host):
            return f"URL resolves to private IP: {host}"
        return None
    except ValueError:
        pass

    try:
        resolved = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return None

    for _family, _stype, _proto, _canon, sockaddr in resolved:
        ip = sockaddr[0]
        if _is_private_ip(ip):
            return f"URL resolves to private IP: {ip}"
        try:
            parsed_ip = ipaddress.ip_address(ip)
            if isinstance(parsed_ip, ipaddress.IPv6Address):
                embedded = _embedded_ipv4(parsed_ip)
                if embedded is not None and str(embedded) in _BLOCKED_HOSTS:
                    return f"Blocked host: {embedded} (cloud metadata endpoint)"
        except ValueError:
            continue
    return None


def create_openjarvis_rust_module() -> ModuleType:
    module = ModuleType("openjarvis_rust")
    module.SQLiteMemory = SQLiteMemory
    module.BM25Memory = BM25Memory
    module.LoopGuard = LoopGuard
    module.SecretScanner = SecretScanner
    module.PIIScanner = PIIScanner
    module.InjectionScanner = InjectionScanner
    module.CapabilityPolicy = CapabilityPolicy
    module.RateLimiter = RateLimiter
    module.CalculatorTool = CalculatorTool
    module.FileReadTool = FileReadTool
    module.FileWriteTool = FileWriteTool
    module.ThinkTool = ThinkTool
    module.ShellExecTool = ShellExecTool
    module.HttpRequestTool = HttpRequestTool
    module.GitStatusTool = GitStatusTool
    module.GitDiffTool = GitDiffTool
    module.GitLogTool = GitLogTool
    module.OptimizationStore = OptimizationStore
    module.is_sensitive_file = is_sensitive_file
    module.check_ssrf = check_ssrf
    return module

