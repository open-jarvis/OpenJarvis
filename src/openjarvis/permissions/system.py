"""Permission system for NORA AI — Level 1/2/3 access control."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Callable, Any
import logging

logger = logging.getLogger(__name__)


class PermissionLevel(int, Enum):
    """Permission levels for NORA operations."""
    LEVEL_1 = 1  # Safe - automatic
    LEVEL_2 = 2  # Confirmation required
    LEVEL_3 = 3  # High risk - explicit permission required


@dataclass
class Permission:
    """A permission definition."""
    id: str
    name: str
    description: str
    level: PermissionLevel
    category: str  # file_ops, terminal, network, system, etc.
    default_allowed: bool = False
    
    def __hash__(self):
        return hash(self.id)


class PermissionSystem:
    """Manages permissions and approval requests."""

    # Default permissions
    SAFE_PERMISSIONS = {
        "read_files": Permission(
            "read_files", "Read Files",
            "Read approved files and directories",
            PermissionLevel.LEVEL_1, "file_ops", default_allowed=True
        ),
        "inspect_projects": Permission(
            "inspect_projects", "Inspect Projects",
            "Check project structure and status",
            PermissionLevel.LEVEL_1, "file_ops", default_allowed=True
        ),
        "check_status": Permission(
            "check_status", "Check Status",
            "Check device and application status",
            PermissionLevel.LEVEL_1, "system", default_allowed=True
        ),
        "search_memory": Permission(
            "search_memory", "Search Memory",
            "Search stored memories and facts",
            PermissionLevel.LEVEL_1, "memory", default_allowed=True
        ),
    }

    CONFIRMATION_PERMISSIONS = {
        "edit_files": Permission(
            "edit_files", "Edit Files",
            "Create or modify files",
            PermissionLevel.LEVEL_2, "file_ops"
        ),
        "install_software": Permission(
            "install_software", "Install Software",
            "Install applications and dependencies",
            PermissionLevel.LEVEL_2, "system"
        ),
        "update_apps": Permission(
            "update_apps", "Update Applications",
            "Update installed applications",
            PermissionLevel.LEVEL_2, "system"
        ),
        "create_git_commit": Permission(
            "create_git_commit", "Create Git Commit",
            "Create and push git commits",
            PermissionLevel.LEVEL_2, "git"
        ),
        "execute_code": Permission(
            "execute_code", "Execute Code",
            "Execute Python/terminal code",
            PermissionLevel.LEVEL_2, "terminal"
        ),
    }

    HIGH_RISK_PERMISSIONS = {
        "delete_files": Permission(
            "delete_files", "Delete Files",
            "Delete files and directories",
            PermissionLevel.LEVEL_3, "file_ops"
        ),
        "uninstall_software": Permission(
            "uninstall_software", "Uninstall Software",
            "Uninstall applications",
            PermissionLevel.LEVEL_3, "system"
        ),
        "system_config": Permission(
            "system_config", "System Configuration",
            "Modify system settings and configuration",
            PermissionLevel.LEVEL_3, "system"
        ),
        "network_access": Permission(
            "network_access", "Network Access",
            "Access network and internet resources",
            PermissionLevel.LEVEL_3, "network"
        ),
    }

    def __init__(self, approval_callback: Optional[Callable[[str, Dict[str, Any]], bool]] = None):
        self.permissions: Dict[str, Permission] = {}
        self.permissions.update(self.SAFE_PERMISSIONS)
        self.permissions.update(self.CONFIRMATION_PERMISSIONS)
        self.permissions.update(self.HIGH_RISK_PERMISSIONS)
        
        self.granted_permissions: set = set(self.SAFE_PERMISSIONS.keys())
        self.approval_callback = approval_callback

    def request_permission(
        self,
        permission_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Request permission for an action."""
        if permission_id not in self.permissions:
            logger.warning(f"Unknown permission: {permission_id}")
            return False
        
        perm = self.permissions[permission_id]
        
        # Level 1: Always allowed
        if perm.level == PermissionLevel.LEVEL_1:
            return True
        
        # Check if already granted
        if permission_id in self.granted_permissions:
            return True
        
        # Request approval
        logger.info(f"Requesting {perm.level.name}: {perm.name}")
        logger.info(f"  {perm.description}")
        
        if self.approval_callback:
            approved = self.approval_callback(perm.name, context or {})
            if approved:
                self.granted_permissions.add(permission_id)
                logger.info(f"Permission granted: {permission_id}")
            return approved
        
        # No callback - deny by default for safety
        logger.warning(f"Permission denied (no approval callback): {permission_id}")
        return False

    def explain_action(self, permission_id: str) -> str:
        """Explain what an action does before asking for permission."""
        if permission_id not in self.permissions:
            return "Unknown action"
        perm = self.permissions[permission_id]
        return f"{perm.name}: {perm.description}"

    def get_permission_level(self, permission_id: str) -> Optional[PermissionLevel]:
        """Get permission level for an action."""
        if permission_id not in self.permissions:
            return None
        return self.permissions[permission_id].level

    def get_permissions_by_level(
        self,
        level: PermissionLevel,
    ) -> List[Permission]:
        """Get all permissions at a specific level."""
        return [
            p for p in self.permissions.values()
            if p.level == level
        ]

    def grant_permission(self, permission_id: str) -> bool:
        """Manually grant a permission."""
        if permission_id not in self.permissions:
            return False
        self.granted_permissions.add(permission_id)
        return True

    def revoke_permission(self, permission_id: str) -> bool:
        """Revoke a permission."""
        if permission_id not in self.permissions:
            return False
        self.granted_permissions.discard(permission_id)
        return True

    def reset_permissions(self) -> None:
        """Reset to default permissions."""
        self.granted_permissions = set(self.SAFE_PERMISSIONS.keys())


__all__ = ["PermissionLevel", "Permission", "PermissionSystem"]
