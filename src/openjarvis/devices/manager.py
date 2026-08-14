"""Device Manager for NORA's cross-device coordination."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from uuid import uuid4

from openjarvis.devices.types import (
    DeviceInfo,
    DeviceCommand,
    FileTransfer,
    ConnectionStatus,
    DeviceType,
    DeviceOS,
    Capability,
)
from openjarvis.core.paths import get_config_dir

logger = logging.getLogger(__name__)


class DeviceManager:
    """Manages connected devices and cross-device coordination."""

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or get_config_dir()
        self.devices: Dict[str, DeviceInfo] = {}
        self.this_device_id: Optional[str] = None
        self.commands: Dict[str, DeviceCommand] = {}
        self.transfers: Dict[str, FileTransfer] = {}
        
        self._load_devices()

    def _load_devices(self) -> None:
        """Load device registry from disk."""
        import json
        devices_path = self.config_dir / "devices.json"
        if devices_path.exists():
            try:
                with open(devices_path, "r") as f:
                    data = json.load(f)
                    self.this_device_id = data.get("this_device_id")
                    for device_data in data.get("devices", []):
                        device = self._device_from_dict(device_data)
                        self.devices[device.device_id] = device
                logger.info(f"Loaded {len(self.devices)} devices")
            except Exception as e:
                logger.warning(f"Failed to load devices: {e}")

    def _save_devices(self) -> None:
        """Save device registry to disk."""
        import json
        devices_path = self.config_dir / "devices.json"
        try:
            data = {
                "this_device_id": self.this_device_id,
                "devices": [
                    self._device_to_dict(d) for d in self.devices.values()
                ],
            }
            with open(devices_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save devices: {e}")

    def _device_from_dict(self, data: Dict[str, Any]) -> DeviceInfo:
        """Convert dict to DeviceInfo."""
        capabilities = {
            name: Capability(
                name=cap.get("name"),
                enabled=cap.get("enabled", True),
                description=cap.get("description", ""),
                requires_confirmation=cap.get("requires_confirmation", False),
            )
            for name, cap in data.get("capabilities", {}).items()
        }
        return DeviceInfo(
            device_id=data["device_id"],
            name=data.get("name", ""),
            device_type=DeviceType(data.get("device_type", "pc")),
            os=DeviceOS(data.get("os", "unknown")),
            os_version=data.get("os_version", ""),
            local_ip=data.get("local_ip"),
            remote_ip=data.get("remote_ip"),
            port=data.get("port", 8000),
            cpu_cores=data.get("cpu_cores", 0),
            ram_gb=data.get("ram_gb", 0.0),
            storage_gb=data.get("storage_gb", 0.0),
            gpu_name=data.get("gpu_name"),
            gpu_vram_gb=data.get("gpu_vram_gb"),
            status=ConnectionStatus(data.get("status", "offline")),
            last_seen=data.get("last_seen", ""),
            is_primary=data.get("is_primary", False),
            capabilities=capabilities,
            auth_token=data.get("auth_token", ""),
            trusted=data.get("trusted", False),
        )

    def _device_to_dict(self, device: DeviceInfo) -> Dict[str, Any]:
        """Convert DeviceInfo to dict."""
        return {
            "device_id": device.device_id,
            "name": device.name,
            "device_type": device.device_type.value,
            "os": device.os.value,
            "os_version": device.os_version,
            "local_ip": device.local_ip,
            "remote_ip": device.remote_ip,
            "port": device.port,
            "cpu_cores": device.cpu_cores,
            "ram_gb": device.ram_gb,
            "storage_gb": device.storage_gb,
            "gpu_name": device.gpu_name,
            "gpu_vram_gb": device.gpu_vram_gb,
            "status": device.status.value,
            "last_seen": device.last_seen,
            "is_primary": device.is_primary,
            "capabilities": {
                name: {
                    "name": cap.name,
                    "enabled": cap.enabled,
                    "description": cap.description,
                    "requires_confirmation": cap.requires_confirmation,
                }
                for name, cap in device.capabilities.items()
            },
            "auth_token": device.auth_token,
            "trusted": device.trusted,
        }

    def register_this_device(
        self,
        name: str,
        device_type: DeviceType,
        os: DeviceOS,
        os_version: str = "",
        cpu_cores: int = 0,
        ram_gb: float = 0.0,
        storage_gb: float = 0.0,
        gpu_name: Optional[str] = None,
        gpu_vram_gb: Optional[float] = None,
    ) -> DeviceInfo:
        """Register this device."""
        device_id = str(uuid4())
        self.this_device_id = device_id
        
        device = DeviceInfo(
            device_id=device_id,
            name=name,
            device_type=device_type,
            os=os,
            os_version=os_version,
            cpu_cores=cpu_cores,
            ram_gb=ram_gb,
            storage_gb=storage_gb,
            gpu_name=gpu_name,
            gpu_vram_gb=gpu_vram_gb,
            status=ConnectionStatus.ONLINE,
            is_primary=True,
            trusted=True,
        )
        
        # Add default capabilities based on device type
        if device_type in [DeviceType.PC, DeviceType.LAPTOP]:
            device.capabilities = {
                "terminal": Capability("terminal", True, "Terminal access"),
                "file_access": Capability("file_access", True, "File system access"),
                "blender": Capability("blender", True, "Blender automation"),
                "applications": Capability("applications", True, "Launch applications"),
            }
        elif device_type == DeviceType.PHONE:
            device.capabilities = {
                "camera": Capability("camera", False, "Camera access"),
                "microphone": Capability("microphone", False, "Microphone access"),
                "files": Capability("files", True, "File access"),
                "notifications": Capability("notifications", True, "Send notifications"),
            }
        
        self.devices[device_id] = device
        self._save_devices()
        logger.info(f"Registered this device: {name} ({device_id})")
        return device

    def pair_device(
        self,
        name: str,
        device_type: DeviceType,
        os: DeviceOS,
        local_ip: Optional[str] = None,
        remote_ip: Optional[str] = None,
    ) -> DeviceInfo:
        """Pair a new device (requires user approval)."""
        device_id = str(uuid4())
        auth_token = str(uuid4())  # Random token for secure communication
        
        device = DeviceInfo(
            device_id=device_id,
            name=name,
            device_type=device_type,
            os=os,
            local_ip=local_ip,
            remote_ip=remote_ip,
            status=ConnectionStatus.OFFLINE,
            auth_token=auth_token,
            trusted=False,  # Requires approval
        )
        
        self.devices[device_id] = device
        self._save_devices()
        logger.info(f"Paired device: {name} (awaiting approval)")
        return device

    def approve_device(self, device_id: str) -> bool:
        """Approve a paired device."""
        if device_id not in self.devices:
            return False
        self.devices[device_id].trusted = True
        self._save_devices()
        logger.info(f"Device approved: {self.devices[device_id].name}")
        return True

    def remove_device(self, device_id: str) -> bool:
        """Remove a device from the network."""
        if device_id not in self.devices:
            return False
        name = self.devices[device_id].name
        del self.devices[device_id]
        self._save_devices()
        logger.info(f"Device removed: {name}")
        return True

    def update_device_status(
        self,
        device_id: str,
        status: ConnectionStatus,
    ) -> bool:
        """Update device connection status."""
        if device_id not in self.devices:
            return False
        self.devices[device_id].status = status
        self.devices[device_id].last_seen = datetime.utcnow().isoformat()
        self._save_devices()
        return True

    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        """Get device by ID."""
        return self.devices.get(device_id)

    def get_devices_by_type(self, device_type: DeviceType) -> List[DeviceInfo]:
        """Get all devices of a specific type."""
        return [
            d for d in self.devices.values()
            if d.device_type == device_type and d.trusted
        ]

    def get_online_devices(self) -> List[DeviceInfo]:
        """Get all online, trusted devices."""
        return [
            d for d in self.devices.values()
            if d.status == ConnectionStatus.ONLINE and d.trusted
        ]

    def send_command(
        self,
        target_device_id: str,
        action: str,
        payload: Dict[str, Any],
        requires_permission: bool = False,
    ) -> DeviceCommand:
        """Send a command to a device."""
        source_device_id = self.this_device_id or "unknown"
        command = DeviceCommand(
            command_id=str(uuid4()),
            source_device_id=source_device_id,
            target_device_id=target_device_id,
            action=action,
            payload=payload,
            requires_permission=requires_permission,
            created_at=datetime.utcnow().isoformat(),
            status="pending",
        )
        self.commands[command.command_id] = command
        logger.info(
            f"Command sent: {action} to {target_device_id}"
        )
        return command

    def get_status(self) -> Dict[str, Any]:
        """Get device manager status."""
        online = len(self.get_online_devices())
        total = len([d for d in self.devices.values() if d.trusted])
        return {
            "this_device_id": self.this_device_id,
            "online_devices": online,
            "total_devices": total,
            "devices": {
                d.device_id: {
                    "name": d.name,
                    "type": d.device_type.value,
                    "status": d.status.value,
                }
                for d in self.devices.values()
            },
        }

    def __repr__(self) -> str:
        online = len(self.get_online_devices())
        total = len([d for d in self.devices.values() if d.trusted])
        return f"DeviceManager({online}/{total} online)"


__all__ = ["DeviceManager"]
