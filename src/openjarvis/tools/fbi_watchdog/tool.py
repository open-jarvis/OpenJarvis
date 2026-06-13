"""FBI Watchdog Tool for OpenJarvis Agents.

Wraps the simplified FBI_Watchdog scan engine so agents can perform
DNS, HTTP, WHOIS, and IP reconnaissance on demand.
"""

from __future__ import annotations

from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec
from openjarvis.tools.fbi_watchdog.core import run_scan


@ToolRegistry.register("fbi_watchdog")
class FbiWatchdogTool(BaseTool):
    """On-demand OSINT reconnaissance via DNS, HTTP, WHOIS, and IP lookups."""

    tool_id = "fbi_watchdog"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="fbi_watchdog",
            description=(
                "Perform OSINT reconnaissance on a domain or IP address. "
                "Runs DNS record queries, HTTP fingerprinting, WHOIS lookups, "
                "and IP geolocation / reverse-DNS. "
                "Use this when the user asks to 'check a domain', 'scan a website', "
                "'investigate a target', or 'recon a site'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": (
                            "The domain, hostname, or IP address to investigate. "
                            "Examples: 'landhausbavaria.de', '1.1.1.1'"
                        ),
                    },
                    "modules": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["dns", "http", "whois", "ip"]},
                        "description": (
                            "Which recon modules to run. Default is all. "
                            "dns: A, MX, TXT, NS, CNAME records. "
                            "http: status, headers, body hash. "
                            "whois: registrar, creation/expiration dates, privacy status. "
                            "ip: geolocation, ASN, reverse DNS."
                        ),
                        "default": ["dns", "http", "whois", "ip"],
                    },
                },
                "required": ["target"],
            },
            category="osint",
            cost_estimate=0.0,
            latency_estimate=8.0,
            timeout_seconds=45.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        target = params.get("target", "").strip()
        modules = params.get("modules", ["dns", "http", "whois", "ip"])

        if not target:
            return ToolResult(
                tool_name="fbi_watchdog",
                content="Error: target parameter is required.",
                success=False,
            )

        try:
            results = run_scan(target, modules)
        except Exception as exc:
            return ToolResult(
                tool_name="fbi_watchdog",
                content=f"Scan failed: {exc}",
                success=False,
            )

        # Format human-readable output
        lines = [f"OSINT Recon Report: {target}", ""]

        for mod, mod_result in results["results"].items():
            lines.append(f"--- {mod.upper()} ---")
            if mod_result.get("errors"):
                lines.append(f"Errors: {', '.join(mod_result['errors'])}")

            if mod == "dns" and mod_result.get("records"):
                for record_type, records in mod_result["records"].items():
                    lines.append(f"  {record_type}: {', '.join(records)}")

            elif mod == "http":
                lines.append(f"  Reachable: {mod_result.get('reachable')}")
                lines.append(f"  HTTPS: {mod_result.get('https')}")
                lines.append(f"  Status: {mod_result.get('status_code')}")
                lines.append(f"  Final URL: {mod_result.get('final_url')}")
                if mod_result.get("headers"):
                    for key, val in mod_result["headers"].items():
                        lines.append(f"  {key}: {val}")
                lines.append(f"  Body SHA256: {mod_result.get('body_hash')}")

            elif mod == "whois":
                lines.append(f"  Registrar: {mod_result.get('registrar')}")
                lines.append(f"  Created: {mod_result.get('creation_date')}")
                lines.append(f"  Expires: {mod_result.get('expiration_date')}")
                lines.append(f"  Privacy Protected: {mod_result.get('privacy_protected')}")
                if mod_result.get("seizure_indicators"):
                    lines.append(f"  Seizure Indicators: {', '.join(mod_result['seizure_indicators'])}")

            elif mod == "ip":
                lines.append(f"  Reverse DNS: {mod_result.get('reverse_dns')}")
                geo = mod_result.get("geolocation", {})
                if geo.get("country"):
                    lines.append(f"  Country: {geo.get('country')}")
                if geo.get("city"):
                    lines.append(f"  City: {geo.get('city')}")
                if geo.get("isp"):
                    lines.append(f"  ISP: {geo.get('isp')}")
                asn = mod_result.get("asn", {})
                if asn.get("asn"):
                    lines.append(f"  ASN: {asn.get('asn')}")

            lines.append("")

        # Summary
        summary = results["summary"]
        lines.append("--- SUMMARY ---")
        lines.append(f"Reachable: {summary['reachable']}")
        lines.append(f"Privacy Protected: {summary['privacy_protected']}")
        lines.append(f"Seizure Detected: {summary['seizure_detected']}")
        lines.append(f"Errors: {summary['errors']}")

        content = "\n".join(lines)
        return ToolResult(
            tool_name="fbi_watchdog",
            content=content,
            success=True,
            metadata={
                "target": target,
                "modules": modules,
                "summary": summary,
                "raw_results": results,
            },
        )


__all__ = ["FbiWatchdogTool"]
