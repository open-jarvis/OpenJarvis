"""Audit locked Python dependencies and render a strict Rust advisory policy."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import json
import re
import ssl
import sys
import time
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python 3.10 compatibility for local checks.
    import tomli as tomllib

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
LOCKFILES = {"uv.lock", "rust/Cargo.lock", "frontend/src-tauri/Cargo.lock"}


class AuditError(ValueError):
    """An audit cannot establish a complete, valid result."""


def read_policy(path: Path, today: dt.date | None = None) -> list[dict]:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or type(data.get("schema")) is not int
        or data["schema"] != 1
    ):
        raise AuditError("Invalid exception policy schema")
    entries = data.get("exceptions")
    if not isinstance(entries, list):
        raise AuditError("Exception policy must contain an exceptions list")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise AuditError("Exception must be an object")
        if set(entry) - {
            "lockfile",
            "package",
            "version",
            "advisories",
            "reason",
            "upstream",
            "expires",
            "only_parents",
        }:
            raise AuditError("Unrecognized exception policy field")
        scope, name, version = (
            entry.get(k) for k in ("lockfile", "package", "version")
        )
        ids = entry.get("advisories")
        if scope not in LOCKFILES or not isinstance(name, str) or not name.strip():
            raise AuditError("Exception must identify a supported lockfile and package")
        if not isinstance(version, str) or not re.fullmatch(
            r"[0-9][A-Za-z0-9.+_-]*", version
        ):
            raise AuditError("Exception versions must be exact")
        parents = entry.get("only_parents")
        if parents is not None and (
            scope != "uv.lock"
            or not isinstance(parents, dict)
            or not parents
            or not all(
                isinstance(k, str)
                and k
                and isinstance(v, str)
                and re.fullmatch(r"[0-9][A-Za-z0-9.+_-]*", v)
                for k, v in parents.items()
            )
        ):
            raise AuditError(
                "Exception parent conditions must use exact Python versions"
            )
        if (
            not isinstance(ids, list)
            or not ids
            or not all(
                isinstance(i, str)
                and re.fullmatch(r"(?:GHSA|CVE|PYSEC|RUSTSEC)-[A-Za-z0-9-]+", i)
                for i in ids
            )
        ):
            raise AuditError("Exception must identify exact advisory IDs")
        if (
            not isinstance(entry.get("reason"), str)
            or len(entry["reason"].strip()) < 30
        ):
            raise AuditError("Exception needs a substantive reason")
        if not isinstance(entry.get("upstream"), str) or not entry[
            "upstream"
        ].startswith("https://"):
            raise AuditError("Exception needs an HTTPS upstream reference")
        try:
            expires = dt.date.fromisoformat(entry["expires"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AuditError("Exception needs an ISO expiry date") from exc
        if expires <= today or expires > today + dt.timedelta(days=90):
            raise AuditError(f"Exception expired or exceeds 90 days: {name} {version}")
        for advisory in ids:
            key = (scope, name, version, advisory)
            if key in seen:
                raise AuditError("Duplicate advisory exception")
            seen.add(key)
    return entries


def lock_packages(path: Path, scope: str) -> list[dict]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    packages = data.get("package")
    if not isinstance(packages, list) or not packages:
        raise AuditError("Lockfile contains no packages")
    result = {}
    for package in packages:
        if not isinstance(package, dict) or not isinstance(package.get("name"), str):
            raise AuditError("Malformed locked package")
        source = package.get("source")
        if scope == "uv.lock":
            own_projects = {
                "openjarvis": {"editable": "."},
                "openjarvis-rust": {"directory": "rust/crates/openjarvis-python"},
            }
            name = package["name"].lower()
            if name in own_projects and own_projects[name] == source:
                continue
            if source != {"registry": "https://pypi.org/simple"}:
                raise AuditError(f"Unreviewed Python package source: {package['name']}")
        else:
            if source is None:  # In-tree workspace/path dependencies are code-reviewed.
                continue
            if source != "registry+https://github.com/rust-lang/crates.io-index":
                raise AuditError(f"Unreviewed Rust package source: {package['name']}")
        version = package.get("version")
        if not isinstance(version, str) or not version:
            raise AuditError("Locked registry package has no version")
        result[(package["name"], version)] = {
            "name": package["name"],
            "version": version,
        }
    if not result:
        raise AuditError("Lockfile contains no auditable registry packages")
    return list(result.values())


def scoped_exceptions(
    policy: list[dict], packages: list[dict], scope: str
) -> list[dict]:
    versions = {(p["name"], p["version"]) for p in packages}
    entries = [e for e in policy if e["lockfile"] == scope]
    for entry in entries:
        if (entry["package"], entry["version"]) not in versions:
            raise AuditError(
                f"Remove stale exception: {entry['package']} {entry['version']}"
            )
    return entries


def request_osv(queries: list[dict]) -> dict:
    for attempt in range(3):
        connection = None
        try:
            # Explicit verified TLS on Python 3.11+, not the pre-3.4.3 behavior
            # covered by this compatibility audit rule. The host is fixed.
            # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected  # noqa: E501
            connection = http.client.HTTPSConnection(
                "api.osv.dev", timeout=30, context=ssl.create_default_context()
            )
            connection.request(
                "POST",
                "/v1/querybatch",
                body=json.dumps({"queries": queries}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            if response.status != 200:
                raise http.client.HTTPException(f"OSV returned HTTP {response.status}")
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise AuditError("OSV response exceeds the audit size limit")
            return json.loads(body)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            if attempt == 2:
                raise AuditError(
                    "OSV audit request failed; refusing an incomplete audit"
                ) from exc
            time.sleep(attempt + 1)
        finally:
            if connection is not None:
                connection.close()
    raise AssertionError("unreachable")


def validate_parent_conditions(entries: list[dict], lockfile: Path) -> None:
    guarded = [e for e in entries if "only_parents" in e]
    if not guarded:
        return
    packages = tomllib.loads(lockfile.read_text(encoding="utf-8"))["package"]
    for entry in guarded:
        actual = {
            (package["name"], package.get("version"))
            for package in packages
            if any(
                d.get("name") == entry["package"]
                for d in package.get("dependencies", [])
            )
        }
        if actual != set(entry["only_parents"].items()):
            raise AuditError(f"Exception parent conditions changed: {entry['package']}")


def python_findings(packages: list[dict], query=request_osv) -> list[dict]:
    findings = []
    for offset in range(0, len(packages), 100):
        batch = packages[offset : offset + 100]
        queries = [
            {
                "package": {"name": p["name"], "ecosystem": "PyPI"},
                "version": p["version"],
            }
            for p in batch
        ]
        response = query(queries)
        if not isinstance(response, dict) or "error" in response:
            raise AuditError("OSV returned an audit error")
        results = response.get("results")
        if not isinstance(results, list) or len(results) != len(batch):
            raise AuditError("OSV returned an incomplete batch")
        for package, result in zip(batch, results):
            if not isinstance(result, dict) or "error" in result:
                raise AuditError("OSV returned an invalid package result")
            if set(result) - {"vulns", "next_page_token"}:
                raise AuditError("OSV returned an unrecognized package result")
            if result.get("next_page_token"):
                raise AuditError("OSV returned a partial advisory page")
            vulns = result.get("vulns", [])
            if not isinstance(vulns, list):
                raise AuditError("OSV returned malformed advisories")
            for vuln in vulns:
                if (
                    not isinstance(vuln, dict)
                    or not isinstance(vuln.get("id"), str)
                    or not vuln["id"]
                ):
                    raise AuditError("OSV returned an advisory without an ID")
                findings.append({**package, "advisory": vuln["id"]})
    return findings


def apply_exceptions(findings: list[dict], entries: list[dict]) -> list[dict]:
    allowed = {
        (e["package"], e["version"], advisory): e
        for e in entries
        for advisory in e["advisories"]
    }
    used = set()
    result = []
    for finding in findings:
        key = (finding["name"], finding["version"], finding["advisory"])
        entry = allowed.get(key)
        if entry:
            used.add(key)
        result.append({**finding, "excepted": bool(entry), "exception": entry})
    if set(allowed) - used:
        raise AuditError("Remove exception IDs that no longer appear in the audit")
    return result


def cargo_config(entries: list[dict]) -> str:
    ignores = []
    for entry in entries:
        for advisory in entry["advisories"]:
            if not advisory.startswith("RUSTSEC-"):
                raise AuditError("Rust exceptions must use RustSec IDs")
            ignores.append(
                "{ id = "
                + json.dumps(advisory)
                + ", reason = "
                + json.dumps(entry["reason"] + " Expires " + entry["expires"])
                + " }"
            )
    return (
        '[advisories]\ndb-urls = ["https://github.com/RustSec/advisory-db"]\n'
        'maximum-db-staleness = "P1D"\nyanked = "deny"\nunsound = "all"\n'
        'unmaintained = "all"\nunused-ignored-advisory = "deny"\n'
        "ignore = [" + ",\n".join(ignores) + "]\n\n"
        '[sources]\nunknown-registry = "deny"\nunknown-git = "deny"\n'
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["python", "cargo-config"])
    parser.add_argument("--lockfile", required=True, choices=sorted(LOCKFILES))
    parser.add_argument("--policy", default=".github/security/advisory-exceptions.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    try:
        if (args.mode == "python") != (args.lockfile == "uv.lock"):
            raise AuditError("Scanner does not match the lockfile")
        policy = read_policy(Path(args.policy))
        packages = lock_packages(Path(args.lockfile), args.lockfile)
        entries = scoped_exceptions(policy, packages, args.lockfile)
        validate_parent_conditions(entries, Path(args.lockfile))
        if args.mode == "cargo-config":
            output.write_text(cargo_config(entries), encoding="utf-8")
            return 0
        findings = apply_exceptions(python_findings(packages), entries)
        rejected = [f for f in findings if not f["excepted"]]
        report = {
            "lockfile": args.lockfile,
            "sha256": hashlib.sha256(Path(args.lockfile).read_bytes()).hexdigest(),
            "audited_packages": len(packages),
            "findings": findings,
        }
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(
            f"Audited {len(packages)} locked versions; "
            f"{len(rejected)} unaccepted advisories"
        )
        for finding in rejected:
            print(f"{finding['name']}=={finding['version']}: {finding['advisory']}")
        return 1 if rejected else 0
    except (AuditError, OSError, ValueError, TypeError) as exc:
        output.write_text(json.dumps({"error": str(exc)}) + "\n", encoding="utf-8")
        print(f"Security audit failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
