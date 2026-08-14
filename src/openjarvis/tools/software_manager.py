"""Software Manager for NORA AI — application inventory and updates."""

from __future__ import annotations

import logging
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)


class UpdateStatus(str, Enum):
    """Update status for an application."""
    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    UNKNOWN = "unknown"
    ERROR = "error"


@dataclass
class InstalledApp:
    """Information about an installed application."""
    name: str
    version: str
    installed_path: Optional[Path] = None
    latest_version: Optional[str] = None
    update_available: bool = False
    update_method: str = "unknown"  # manual, package_manager, official_updater, app_store
    homepage: str = ""
    last_checked: str = ""

    def needs_update(self) -> bool:
        """Check if update is available."""
        if not self.latest_version or not self.version:
            return False
        return self.latest_version > self.version


class PackageManagerDetector:
    """Detect available package managers."""

    @staticmethod
    def is_command_available(cmd: str) -> bool:
        """Check if a command is available."""
        import shutil
        return shutil.which(cmd) is not None

    @staticmethod
    def get_available_managers() -> Dict[str, str]:
        """Get available package managers for this system."""
        system = platform.system()
        available = {}

        if system == "Windows":
            if PackageManagerDetector.is_command_available("winget"):
                available["winget"] = "Windows Package Manager"
            if PackageManagerDetector.is_command_available("choco"):
                available["chocolatey"] = "Chocolatey"

        elif system == "Darwin":
            if PackageManagerDetector.is_command_available("brew"):
                available["homebrew"] = "Homebrew"
            if PackageManagerDetector.is_command_available("port"):
                available["macports"] = "MacPorts"

        elif system == "Linux":
            if PackageManagerDetector.is_command_available("apt"):
                available["apt"] = "APT (Debian/Ubuntu)"
            elif PackageManagerDetector.is_command_available("yum"):
                available["yum"] = "YUM (RedHat/CentOS)"
            elif PackageManagerDetector.is_command_available("pacman"):
                available["pacman"] = "Pacman (Arch)"
            elif PackageManagerDetector.is_command_available("zypper"):
                available["zypper"] = "Zypper (openSUSE)"

        return available


class SoftwareManager:
    """Manage software inventory and updates."""

    def __init__(self):
        self.system = platform.system()
        self.apps: Dict[str, InstalledApp] = {}
        self.package_managers = PackageManagerDetector.get_available_managers()
        logger.info(
            f"SoftwareManager initialized for {self.system}. "
            f"Available package managers: {list(self.package_managers.values())}"
        )

    def register_app(
        self,
        name: str,
        version: str,
        installed_path: Optional[Path] = None,
        update_method: str = "unknown",
        homepage: str = "",
    ) -> InstalledApp:
        """Register an installed application."""
        app = InstalledApp(
            name=name,
            version=version,
            installed_path=installed_path,
            update_method=update_method,
            homepage=homepage,
        )
        self.apps[name.lower()] = app
        logger.info(f"Registered app: {name} v{version}")
        return app

    def check_updates(self, app_name: str) -> Optional[InstalledApp]:
        """Check if an app has updates available."""
        app_lower = app_name.lower()
        if app_lower not in self.apps:
            logger.warning(f"App not found: {app_name}")
            return None

        app = self.apps[app_lower]

        # For known apps, attempt to detect latest version
        # This is simplified; real implementation would check online
        app.update_available = app.needs_update()

        return app

    def get_update_instructions(self, app_name: str) -> Optional[str]:
        """Get instructions for updating an app."""
        app_lower = app_name.lower()
        if app_lower not in self.apps:
            return None

        app = self.apps[app_lower]

        if app.update_method == "package_manager" and self.package_managers:
            manager = list(self.package_managers.keys())[0]
            if manager == "winget":
                return f"Run: winget upgrade {app.name}"
            elif manager == "homebrew":
                return f"Run: brew upgrade {app.name}"
            elif manager == "apt":
                return f"Run: sudo apt update && sudo apt upgrade {app.name}"

        elif app.update_method == "official_updater":
            return f"Check Settings > About or Help > Check for Updates in {app.name}"

        elif app.homepage:
            return f"Visit {app.homepage} to download the latest version"

        return "Manual update required"

    def install_package(
        self,
        package_name: str,
        manager: Optional[str] = None,
    ) -> bool:
        """Install a package using available package manager."""
        if not manager and not self.package_managers:
            logger.error("No package manager available")
            return False

        if not manager:
            manager = list(self.package_managers.keys())[0]

        try:
            if manager == "winget":
                subprocess.run(
                    ["winget", "install", package_name],
                    check=True,
                )
            elif manager == "homebrew":
                subprocess.run(
                    ["brew", "install", package_name],
                    check=True,
                )
            elif manager == "apt":
                subprocess.run(
                    ["sudo", "apt", "install", package_name],
                    check=True,
                )
            elif manager == "yum":
                subprocess.run(
                    ["sudo", "yum", "install", package_name],
                    check=True,
                )

            logger.info(f"Package installed: {package_name}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install package: {e}")
            return False
        except Exception as e:
            logger.error(f"Installation error: {e}")
            return False

    def get_installed_apps(self) -> List[InstalledApp]:
        """Get all registered installed applications."""
        return list(self.apps.values())

    def get_apps_needing_updates(self) -> List[InstalledApp]:
        """Get applications with available updates."""
        return [app for app in self.apps.values() if app.needs_update()]

    def get_status(self) -> Dict[str, Any]:
        """Get software manager status."""
        apps_needing_update = self.get_apps_needing_updates()
        return {
            "system": self.system,
            "total_apps": len(self.apps),
            "apps_needing_update": len(apps_needing_update),
            "available_package_managers": self.package_managers,
            "apps_with_updates": [
                {
                    "name": app.name,
                    "current": app.version,
                    "latest": app.latest_version,
                    "update_method": app.update_method,
                }
                for app in apps_needing_update
            ],
        }


__all__ = [
    "UpdateStatus",
    "InstalledApp",
    "PackageManagerDetector",
    "SoftwareManager",
]
