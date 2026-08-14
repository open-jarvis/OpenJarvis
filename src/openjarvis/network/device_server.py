"""WebSocket server for real-time device communication."""

from __future__ import annotations

import logging
import asyncio
import json
from typing import Dict, Optional, Set, Callable, Any
from pathlib import Path

try:
    import websockets
    from websockets.server import WebSocketServerProtocol
except ImportError:
    websockets = None
    WebSocketServerProtocol = None

from openjarvis.network.device_protocol import (
    DeviceMessage,
    SecureTransport,
    MessageType,
)

logger = logging.getLogger(__name__)


class DeviceServer:
    """WebSocket server for NORA device communication."""

    def __init__(
        self,
        device_id: str,
        host: str = "0.0.0.0",
        port: int = 8765,
    ):
        """Initialize device communication server.
        
        Parameters
        ----------
        device_id
            This device's ID
        host
            Bind address (0.0.0.0 = all interfaces)
        port
            Port to listen on
        """
        if websockets is None:
            raise ImportError(
                "websockets library required. Install: pip install websockets"
            )
        
        self.device_id = device_id
        self.host = host
        self.port = port
        self.connected_devices: Dict[str, WebSocketServerProtocol] = {}
        self.transports: Dict[str, SecureTransport] = {}  # device_id -> SecureTransport
        self.message_handlers: Dict[MessageType, Callable] = {}
        self.server = None

    def register_handler(
        self,
        message_type: MessageType,
        handler: Callable[[DeviceMessage], Any],
    ) -> None:
        """Register a message handler."""
        self.message_handlers[message_type] = handler

    async def handle_connection(
        self,
        websocket: WebSocketServerProtocol,
        path: str,
    ) -> None:
        """Handle new device connection."""
        device_id = None
        try:
            # First message must be identification
            identification = await asyncio.wait_for(websocket.recv(), timeout=5)
            data = json.loads(identification)
            device_id = data.get("device_id")
            
            if not device_id:
                logger.warning("Connection rejected: no device_id")
                await websocket.close()
                return
            
            self.connected_devices[device_id] = websocket
            logger.info(f"Device connected: {device_id}")
            
            # Listen for messages
            async for message_json in websocket:
                await self._handle_message(device_id, message_json)
        
        except asyncio.TimeoutError:
            logger.warning("Connection timeout: no identification received")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from {device_id}: {e}")
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            logger.error(f"Connection error: {e}")
        finally:
            if device_id in self.connected_devices:
                del self.connected_devices[device_id]
                logger.info(f"Device disconnected: {device_id}")

    async def _handle_message(self, device_id: str, message_json: str) -> None:
        """Handle incoming message from device."""
        try:
            data = json.loads(message_json)
            message = DeviceMessage.from_dict(data)
            
            # Verify message signature if transport exists
            if device_id in self.transports:
                if not self.transports[device_id].verify_message(message):
                    logger.warning(f"Message verification failed from {device_id}")
                    return
            
            # Route to handler
            if message.message_type in self.message_handlers:
                handler = self.message_handlers[message.message_type]
                await handler(message) if asyncio.iscoroutinefunction(handler) else handler(message)
            else:
                logger.warning(f"No handler for message type: {message.message_type}")
        
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    async def send_message(
        self,
        target_device_id: str,
        message: DeviceMessage,
    ) -> bool:
        """Send message to a device."""
        if target_device_id not in self.connected_devices:
            logger.warning(f"Device not connected: {target_device_id}")
            return False
        
        try:
            websocket = self.connected_devices[target_device_id]
            message_json = json.dumps(message.to_dict())
            await websocket.send(message_json)
            return True
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False

    async def broadcast_message(
        self,
        message: DeviceMessage,
        exclude_device_id: Optional[str] = None,
    ) -> int:
        """Broadcast message to all connected devices.
        
        Returns
        -------
        Number of devices message was sent to
        """
        sent_count = 0
        for device_id, websocket in self.connected_devices.items():
            if exclude_device_id and device_id == exclude_device_id:
                continue
            
            try:
                message_json = json.dumps(message.to_dict())
                await websocket.send(message_json)
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to broadcast to {device_id}: {e}")
        
        return sent_count

    async def start(self) -> None:
        """Start the WebSocket server."""
        self.server = await websockets.serve(
            self.handle_connection,
            self.host,
            self.port,
        )
        logger.info(f"Device server started on {self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("Device server stopped")

    def get_connected_devices(self) -> list:
        """Get list of connected device IDs."""
        return list(self.connected_devices.keys())


__all__ = ["DeviceServer"]
