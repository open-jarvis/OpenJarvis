"""File system tools for NORA AI with permission checking."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class FileSystemTool:
    """Safe file system operations with permission checking."""

    # Directories to protect by default
    PROTECTED_PATHS = {
        Path("/"),  # Root
        Path("C:\\"),  # Windows root
        Path("/System"),
        Path("/Library"),
        Path("C:\\Windows"),
        Path("C:\\Program Files"),
    }

    def __init__(self, permission_system=None):
        self.permission_system = permission_system
        self.approved_roots: List[Path] = []

    def add_approved_directory(self, path: Path) -> None:
        """Add a directory that NORA can freely access."""
        self.approved_roots.append(path.resolve())
        logger.info(f"Approved directory: {path}")

    def is_path_safe(self, path: Path) -> bool:
        """Check if a path is safe to access."""
        path = path.resolve()

        # Check against protected paths
        for protected in self.PROTECTED_PATHS:
            try:
                path.relative_to(protected)
                logger.warning(f"Access denied: {path} (protected)")
                return False
            except ValueError:
                pass

        # Check if in approved roots
        for approved in self.approved_roots:
            try:
                path.relative_to(approved)
                return True
            except ValueError:
                pass

        return False

    def read_file(self, path: Path) -> Optional[str]:
        """Read file contents with permission checking."""
        if not self.is_path_safe(path):
            if self.permission_system:
                if not self.permission_system.request_permission(
                    "read_files",
                    {"path": str(path)},
                ):
                    logger.error(f"Permission denied: read {path}")
                    return None
            else:
                logger.error(f"Access denied: {path}")
                return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read file: {e}")
            return None

    def write_file(self, path: Path, content: str) -> bool:
        """Write to file with permission checking."""
        if not self.is_path_safe(path):
            if self.permission_system:
                if not self.permission_system.request_permission(
                    "edit_files",
                    {"path": str(path), "action": "write"},
                ):
                    logger.error(f"Permission denied: write {path}")
                    return False
            else:
                logger.error(f"Access denied: {path}")
                return False

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"File written: {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to write file: {e}")
            return False

    def list_directory(self, path: Path) -> Optional[List[str]]:
        """List directory contents with permission checking."""
        if not self.is_path_safe(path):
            logger.error(f"Access denied: {path}")
            return None

        try:
            return [item.name for item in path.iterdir()]
        except Exception as e:
            logger.error(f"Failed to list directory: {e}")
            return None

    def delete_file(self, path: Path) -> bool:
        """Delete file with permission checking."""
        if not self.is_path_safe(path):
            if self.permission_system:
                if not self.permission_system.request_permission(
                    "delete_files",
                    {"path": str(path), "action": "delete"},
                ):
                    logger.error(f"Permission denied: delete {path}")
                    return False
            else:
                logger.error(f"Access denied: {path}")
                return False

        try:
            path.unlink()
            logger.info(f"File deleted: {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file: {e}")
            return False

    def get_file_info(self, path: Path) -> Optional[Dict[str, Any]]:
        """Get file metadata."""
        if not self.is_path_safe(path):
            logger.error(f"Access denied: {path}")
            return None

        try:
            stat = path.stat()
            return {
                "name": path.name,
                "path": str(path),
                "size_bytes": stat.st_size,
                "is_file": path.is_file(),
                "is_dir": path.is_dir(),
                "modified": stat.st_mtime,
            }
        except Exception as e:
            logger.error(f"Failed to get file info: {e}")
            return None


__all__ = ["FileSystemTool"]
