"""Device types and capabilities for NORA's cross-device system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
from uuid import UUID


class DeviceType(str, Enum):
    """Types of devices in NORA network."""
    PC = "pc"
    LAPTOP = "laptop"
    PHONE = "phone"
    TABLET = "tablet"
    WATCH = "watch"
    HEADLESS = "headless"  # Server/Raspberry Pi


class DeviceOS(str, Enum):
    """Operating systems."""
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    ANDROID = "android"
    IOS = "ios"
    UNKNOWN = "unknown"


class ConnectionStatus(str, Enum):
    """Device connection status."""
    ONLINE = "online"
    OFFLINE = "offline"
    SLEEPING = "sleeping"
    UNREACHABLE = "unreachable"


@dataclass(slots=True)
class Capability:
    """A device capability with permission status."""
    name: str  # e.g., "terminal", "file_access", "camera"
    enabled: bool = True
    description: str = ""
    requires_confirmation: bool = False


@dataclass
class DeviceInfo:
    """Complete device information."""
    device_id: str  # UUID
    name: str
    device_type: DeviceType
    os: DeviceOS
    os_version: str = ""
    
    # Network info
    local_ip: Optional[str] = None
    remote_ip: Optional[str] = None
    port: int = 8000
    
    # Hardware
    cpu_cores: int = 0
    ram_gb: float = 0.0
    storage_gb: float = 0.0
    gpu_name: Optional[str] = None
    gpu_vram_gb: Optional[float] = None
    
    # Status
    status: ConnectionStatus = ConnectionStatus.OFFLINE
    last_seen: str = ""  # ISO 8601 timestamp
    is_primary: bool = False
    
    # Capabilities
    capabilities: Dict[str, Capability] = field(default_factory=dict)
    
    # Connection
    auth_token: str = ""  # For secure pairing
    trusted: bool = False  # User has approved this device
    
    def __hash__(self):
        return hash(self.device_id)


@dataclass
class DeviceCommand:
    """A command to execute on a device."""
    command_id: str  # UUID
    source_device_id: str
    target_device_id: str
    action: str  # e.g., "launch_app", "file_transfer", "execute_code"
    payload: Dict[str, Any] = field(default_factory=dict)
    requires_permission: bool = False
    created_at: str = ""  # ISO 8601
    status: str = "pending"  # pending, executing, completed, failed
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class FileTransfer:
    """File transfer between devices."""
    transfer_id: str  # UUID
    source_device_id: str
    target_device_id: str
    file_path: str
    file_name: str
    file_size_bytes: int
    transfer_status: str = "pending"  # pending, in_progress, completed, failed
    progress_percent: int = 0
    checksum: Optional[str] = None  # SHA256 for verification
    created_at: str = ""


__all__ = [
    "DeviceType",
    "DeviceOS",
    "ConnectionStatus",
    "Capability",
    "DeviceInfo",
    "DeviceCommand",
    "FileTransfer",
]
