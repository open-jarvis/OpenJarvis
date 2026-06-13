"""Parser for awesome-osint-arsenal README.md → structured JSON.

Usage:
    python parser.py /path/to/README.md /path/to/output/osint_tools.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


def extract_markdown_link(text: str) -> tuple[str, str | None]:
    """Extract display text and URL from markdown link [text](url)."""
    match = re.search(r"\[([^\]]+)\]\(([^)]+)\)", text)
    if match:
        return match.group(1), match.group(2)
    return text.strip(), None


def parse_readme(md_path: Path) -> list[dict[str, Any]]:
    """Parse the OSINT Arsenal README and extract tools into structured records."""
    tools: list[dict[str, Any]] = []
    current_category = ""

    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()

        # Detect category headers: ## N. Category Name
        cat_match = re.match(r"^##\s+\d+\.\s+(.+)", line)
        if cat_match:
            current_category = cat_match.group(1).strip()
            continue

        # Detect table rows with tool names (bold)
        if not line.startswith("|") or "**" not in line:
            continue

        # Skip header separators
        if re.match(r"^\|[-\s|]+$", line.replace(" ", "")):
            continue

        cells = [c.strip() for c in line.split("|")]
        # Remove empty first/last cells from split
        cells = [c for c in cells if c]
        if len(cells) < 3:
            continue

        name_cell = cells[0]
        desc_cell = cells[1]
        link_cell = cells[2]

        # Extract tool name (remove markdown bold)
        name_match = re.match(r"\*\*(.+?)\*\*", name_cell)
        if not name_match:
            continue
        name = name_match.group(1).strip()

        # Extract description
        description = desc_cell.strip()

        # Extract link / install command
        link_text, url = extract_markdown_link(link_cell)
        install_command = None
        if url is None and (link_cell.startswith("`") or "install" in link_cell.lower()):
            install_command = link_cell.strip("` ")

        tools.append({
            "name": name,
            "category": current_category,
            "description": description,
            "url": url,
            "install_command": install_command,
            "tags": _generate_tags(name, description, current_category),
        })

    return tools


def _generate_tags(name: str, description: str, category: str) -> list[str]:
    """Generate searchable tags from tool metadata."""
    tags: set[str] = set()

    # Category-based tags
    cat_lower = category.lower()
    if "social media" in cat_lower or "username" in cat_lower:
        tags.update(["social", "username", "profile", "account"])
    if "email" in cat_lower:
        tags.update(["email", "breach", "verify"])
    if "phone" in cat_lower:
        tags.update(["phone", "mobile", "carrier"])
    if "domain" in cat_lower or "ip" in cat_lower:
        tags.update(["domain", "ip", "dns", "subdomain", "network"])
    if "geolocation" in cat_lower or "maps" in cat_lower:
        tags.update(["geo", "location", "maps", "gps"])
    if "image" in cat_lower or "video" in cat_lower:
        tags.update(["image", "video", "media", "reverse-image"])
    if "facial" in cat_lower:
        tags.update(["face", "recognition", "person"])
    if "dark web" in cat_lower or "onion" in cat_lower:
        tags.update(["darkweb", "tor", "onion", "anonymous"])
    if "breach" in cat_lower or "leak" in cat_lower:
        tags.update(["breach", "leak", "credential", "password"])
    if "vulnerability" in cat_lower or "exploit" in cat_lower:
        tags.update(["vuln", "exploit", "scan", "pentest"])
    if "network" in cat_lower or "wireless" in cat_lower:
        tags.update(["network", "wifi", "wireless", "packet"])
    if "financial" in cat_lower or "corporate" in cat_lower:
        tags.update(["finance", "company", "corporate", "business"])
    if "metadata" in cat_lower or "forensics" in cat_lower:
        tags.update(["metadata", "forensics", "exif", "digital-forensics"])
    if "camera" in cat_lower or "webcam" in cat_lower:
        tags.update(["camera", "webcam", "surveillance", "cctv"])
    if "google dork" in cat_lower:
        tags.update(["dorking", "google-dorks", "search"])
    if "telegram" in cat_lower:
        tags.update(["telegram", "messaging", "bot"])
    if "api" in cat_lower or "developer" in cat_lower:
        tags.update(["api", "developer", "sdk"])
    if "browser" in cat_lower or "extension" in cat_lower:
        tags.update(["browser", "extension", "chrome", "firefox"])

    # Name-based tags
    name_lower = name.lower()
    if any(x in name_lower for x in ["sherlock", "maigret", "osint"]):
        tags.add("osint")
    if any(x in name_lower for x in ["nmap", "masscan", "shodan"]):
        tags.update(["scanner", "port-scan"])
    if any(x in name_lower for x in ["amass", "subfinder", "dns"]):
        tags.update(["dns", "subdomain"])

    return sorted(tags)


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python parser.py <README.md> <output.json>")
        sys.exit(1)

    md_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    if not md_path.exists():
        print(f"Error: {md_path} not found")
        sys.exit(1)

    tools = parse_readme(md_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(tools, f, indent=2, ensure_ascii=False)

    print(f"Parsed {len(tools)} tools → {out_path}")


if __name__ == "__main__":
    main()
