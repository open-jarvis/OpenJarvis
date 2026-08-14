"""Terminal tool for NORA AI with permission and safety checks."""

from __future__ import annotations

import logging
import subprocess
import platform
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class TerminalTool:
    """Safe terminal execution with permission and safety checks."""

    # Commands that require explicit confirmation
    DANGEROUS_COMMANDS = {
        "rm",
        "del",
        "rmdir",
        "format",
        "destroy",
        "mkfs",
        "dd",
        "chmod",  # Can break system
        "chown",
        "sudo",
        "sudo apt remove",
        "sudo yum remove",
        "uninstall",
    }

    def __init__(self, permission_system=None):
        self.permission_system = permission_system
        self.system = platform.system()

    def is_command_safe(self, command: str) -> bool:
        """Check if a command is safe to execute."""
        command_lower = command.lower().strip()
        for dangerous in self.DANGEROUS_COMMANDS:
            if dangerous in command_lower:
                return False
        return True

    def execute(
        self,
        command: str,
        timeout: int = 30,
        cwd: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Execute a terminal command with safety checks."""
        # Safety check
        if not self.is_command_safe(command):
            if self.permission_system:
                if not self.permission_system.request_permission(
                    "execute_code",
                    {"command": command, "type": "terminal"},
                ):
                    logger.error(f"Permission denied: {command}")
                    return None
            else:
                logger.error(f"Dangerous command blocked: {command}")
                return None

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )

            return {
                "command": command,
                "return_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success": result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            logger.error(f"Command timeout: {command}")
            return {
                "command": command,
                "success": False,
                "error": "Command timeout",
            }
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return {
                "command": command,
                "success": False,
                "error": str(e),
            }

    def get_current_directory(self) -> Optional[str]:
        """Get current working directory."""
        result = self.execute("pwd" if self.system != "Windows" else "cd")
        if result and result["success"]:
            return result["stdout"].strip()
        return None

    def list_directory(self, path: str = ".") -> Optional[list]:
        """List directory contents."""
        cmd = f"ls -la {path}" if self.system != "Windows" else f"dir {path}"
        result = self.execute(cmd)
        if result and result["success"]:
            return result["stdout"].split("\n")
        return None


__all__ = ["TerminalTool"]
