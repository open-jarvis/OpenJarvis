"""Secure device communication protocol for NORA cross-device system."""

from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from typing import Dict, Any, Optional
from enum import Enum
import hashlib
import hmac
from datetime import datetime, timedelta
import secrets

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """Types of messages between devices."""
    # Device management
    PAIRING_REQUEST = "pairing_request"
    PAIRING_RESPONSE = "pairing_response"
    PAIRING_CONFIRM = "pairing_confirm"
    DEVICE_HEARTBEAT = "device_heartbeat"
    DEVICE_DISCONNECT = "device_disconnect"
    
    # Commands
    COMMAND_REQUEST = "command_request"
    COMMAND_RESPONSE = "command_response"
    COMMAND_ERROR = "command_error"
    
    # File transfer
    FILE_TRANSFER_START = "file_transfer_start"
    FILE_TRANSFER_DATA = "file_transfer_data"
    FILE_TRANSFER_COMPLETE = "file_transfer_complete"
    FILE_TRANSFER_CANCEL = "file_transfer_cancel"


@dataclass
class DeviceMessage:
    """Secure message between devices."""
    message_type: MessageType
    source_device_id: str
    target_device_id: str
    payload: Dict[str, Any]
    message_id: str = ""
    timestamp: str = ""
    signature: str = ""  # HMAC-SHA256
    
    def __post_init__(self):
        if not self.message_id:
            self.message_id = secrets.token_hex(16)
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "message_type": self.message_type.value,
            "source_device_id": self.source_device_id,
            "target_device_id": self.target_device_id,
            "payload": self.payload,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DeviceMessage:
        """Create from dictionary."""
        return cls(
            message_type=MessageType(data["message_type"]),
            source_device_id=data["source_device_id"],
            target_device_id=data["target_device_id"],
            payload=data["payload"],
            message_id=data.get("message_id", ""),
            timestamp=data.get("timestamp", ""),
            signature=data.get("signature", ""),
        )


class SecureTransport:
    """Secure message transport with authentication and integrity."""

    def __init__(self, device_id: str, shared_key: str):
        """Initialize transport.
        
        Parameters
        ----------
        device_id
            This device's ID
        shared_key
            Shared secret key for HMAC (from pairing)
        """
        self.device_id = device_id
        self.shared_key = shared_key
        self.message_cache: Dict[str, DeviceMessage] = {}
        self.max_age_seconds = 300  # 5 minutes

    def sign_message(self, message: DeviceMessage) -> str:
        """Sign a message with HMAC-SHA256."""
        # Create signature payload (excludes signature itself)
        sig_payload = f"{message.message_type.value}{message.source_device_id}{message.target_device_id}{message.timestamp}{json.dumps(message.payload, sort_keys=True)}"
        
        signature = hmac.new(
            self.shared_key.encode(),
            sig_payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        
        return signature

    def prepare_message(
        self,
        message_type: MessageType,
        target_device_id: str,
        payload: Dict[str, Any],
    ) -> DeviceMessage:
        """Prepare a signed message."""
        message = DeviceMessage(
            message_type=message_type,
            source_device_id=self.device_id,
            target_device_id=target_device_id,
            payload=payload,
        )
        message.signature = self.sign_message(message)
        return message

    def verify_message(self, message: DeviceMessage) -> bool:
        """Verify message signature and timestamp."""
        # Check timestamp (prevent replay attacks)
        msg_time = datetime.fromisoformat(message.timestamp)
        age = datetime.utcnow() - msg_time
        if age > timedelta(seconds=self.max_age_seconds):
            logger.warning(f"Message too old: {age.total_seconds()}s")
            return False
        
        # Check if already seen (replay attack prevention)
        if message.message_id in self.message_cache:
            logger.warning(f"Duplicate message ID: {message.message_id}")
            return False
        
        # Verify signature
        expected_signature = self.sign_message(message)
        if not hmac.compare_digest(message.signature, expected_signature):
            logger.error(f"Invalid signature for message {message.message_id}")
            return False
        
        # Cache message
        self.message_cache[message.message_id] = message
        return True


class DevicePairingProtocol:
    """Secure device pairing workflow."""

    @staticmethod
    def generate_pairing_token() -> str:
        """Generate a short pairing token for user verification."""
        return secrets.token_hex(4).upper()  # 8 character hex string

    @staticmethod
    def generate_shared_key() -> str:
        """Generate a shared encryption key for communication."""
        return secrets.token_hex(32)  # 64 character hex string (256-bit)

    @staticmethod
    def create_pairing_request(
        initiator_device_id: str,
        initiator_name: str,
    ) -> Dict[str, Any]:
        """Create a pairing request."""
        return {
            "initiator_device_id": initiator_device_id,
            "initiator_name": initiator_name,
            "pairing_token": DevicePairingProtocol.generate_pairing_token(),
            "timestamp": datetime.utcnow().isoformat(),
        }

    @staticmethod
    def create_pairing_response(
        initiator_device_id: str,
        responder_device_id: str,
        responder_name: str,
        pairing_token: str,
    ) -> Dict[str, Any]:
        """Create a pairing response."""
        return {
            "initiator_device_id": initiator_device_id,
            "responder_device_id": responder_device_id,
            "responder_name": responder_name,
            "pairing_token": pairing_token,
            "shared_key": DevicePairingProtocol.generate_shared_key(),
            "timestamp": datetime.utcnow().isoformat(),
        }


class LocalNetworkDiscovery:
    """Discover devices on local network (mDNS/Bonjour)."""

    @staticmethod
    def broadcast_presence(
        device_id: str,
        device_name: str,
        port: int,
    ) -> Dict[str, Any]:
        """Create mDNS broadcast message."""
        return {
            "service_type": "_nora-ai._tcp",
            "device_id": device_id,
            "device_name": device_name,
            "port": port,
            "version": "1.0",
            "timestamp": datetime.utcnow().isoformat(),
        }

    @staticmethod
    def parse_discovery_response(response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse a discovery response."""
        required_fields = {"device_id", "device_name", "port", "service_type"}
        if not required_fields.issubset(response.keys()):
            return None
        
        if response.get("service_type") != "_nora-ai._tcp":
            return None
        
        return response


__all__ = [
    "MessageType",
    "DeviceMessage",
    "SecureTransport",
    "DevicePairingProtocol",
    "LocalNetworkDiscovery",
]
