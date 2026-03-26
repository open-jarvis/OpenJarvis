from __future__ import annotations

import sys
from pathlib import Path

SYSTEMD_TEMPLATE = """\
[Unit]
Description=OpenJarvis Gateway Daemon
After=network.target

[Service]
Type=simple
ExecStart={python} -m openjarvis.daemon.gateway
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""

LAUNCHD_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openjarvis.gateway</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string>
        <string>openjarvis.daemon.gateway</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""


def generate_systemd_service(output: Path | None = None) -> str:
    content = SYSTEMD_TEMPLATE.format(python=sys.executable)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)
    return content


def generate_launchd_plist(output: Path | None = None) -> str:
    content = LAUNCHD_TEMPLATE.format(python=sys.executable)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)
    return content
