"""Webhook endpoints for receiving messages from external platforms."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Request, Response
from starlette.responses import PlainTextResponse

logger = logging.getLogger(__name__)


def _log_task_exception(task: asyncio.Task) -> None:
    """Log exceptions from background message handling tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Background message handling failed: %s",
            exc,
            exc_info=exc,
        )


def _validate_twilio_signature(
    auth_token: str,
    url: str,
    params: dict,
    signature: str,
) -> bool:
    """Validate Twilio webhook signature using the SDK."""
    try:
        from twilio.request_validator import RequestValidator

        validator = RequestValidator(auth_token)
        return validator.validate(url, params, signature)
    except ImportError:
        logger.warning("twilio SDK not installed — skipping signature validation")
        return True


def create_webhook_router(
    bridge: Any,
    twilio_auth_token: str = "",
    bluebubbles_password: str = "",
    whatsapp_verify_token: str = "",
    whatsapp_app_secret: str = "",
    sendblue_channel: Any = None,
) -> APIRouter:
    """Create a FastAPI router with webhook endpoints.

    Args:
        bridge: ChannelBridge instance for routing messages.
        twilio_auth_token: Twilio auth token for signatures.
        bluebubbles_password: BlueBubbles server password.
        whatsapp_verify_token: WhatsApp verification token.
        whatsapp_app_secret: WhatsApp app secret for HMAC.
        sendblue_channel: SendBlueChannel instance for reply-back.
    """
    router = APIRouter(prefix="/webhooks", tags=["webhooks"])

    # ----------------------------------------------------------
    # Twilio SMS
    # ----------------------------------------------------------

    @router.post("/twilio")
    async def twilio_incoming(request: Request) -> Response:
        form = await request.form()
        params = dict(form)
        signature = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)

        if twilio_auth_token and not _validate_twilio_signature(
            twilio_auth_token, url, params, signature
        ):
            return Response("Invalid signature", status_code=403)

        from_number = params.get("From", "")
        body = params.get("Body", "")

        # Dispatch to background — return TwiML immediately
        task = asyncio.create_task(
            asyncio.to_thread(
                bridge.handle_incoming,
                from_number,
                body,
                "twilio",
                max_length=1600,
            )
        )
        task.add_done_callback(_log_task_exception)

        return Response(
            content="<Response></Response>",
            media_type="application/xml",
        )

    # ----------------------------------------------------------
    # BlueBubbles (iMessage)
    # ----------------------------------------------------------

    @router.post("/bluebubbles")
    async def bluebubbles_incoming(
        request: Request,
    ) -> Response:
        auth = request.headers.get("Authorization", "")
        if bluebubbles_password and auth != bluebubbles_password:
            return Response("Invalid password", status_code=403)

        payload = await request.json()
        msg_type = payload.get("type", "")
        if msg_type != "new-message":
            return Response("OK", status_code=200)

        data = payload.get("data", {})
        handle = data.get("handle", {})
        sender = handle.get("address", "")
        text = data.get("text", "")

        task = asyncio.create_task(
            asyncio.to_thread(
                bridge.handle_incoming,
                sender,
                text,
                "bluebubbles",
            )
        )
        task.add_done_callback(_log_task_exception)

        return Response("OK", status_code=200)

    # ----------------------------------------------------------
    # WhatsApp Cloud API
    # ----------------------------------------------------------

    @router.get("/whatsapp")
    async def whatsapp_verify(request: Request) -> Response:
        mode = request.query_params.get("hub.mode", "")
        token = request.query_params.get("hub.verify_token", "")
        challenge = request.query_params.get("hub.challenge", "")

        if mode == "subscribe" and token == whatsapp_verify_token:
            return PlainTextResponse(challenge)
        return Response("Forbidden", status_code=403)

    @router.post("/whatsapp")
    async def whatsapp_incoming(
        request: Request,
    ) -> Response:
        body_bytes = await request.body()

        # Verify signature
        if whatsapp_app_secret:
            signature = request.headers.get("X-Hub-Signature-256", "")
            expected = (
                "sha256="
                + hmac.new(
                    whatsapp_app_secret.encode(),
                    body_bytes,
                    hashlib.sha256,
                ).hexdigest()
            )
            if not hmac.compare_digest(signature, expected):
                return Response("Invalid signature", status_code=403)

        payload = json.loads(body_bytes)
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for message in value.get("messages", []):
                    if message.get("type") != "text":
                        continue
                    sender = message.get("from", "")
                    text = message.get("text", {}).get("body", "")

                    task = asyncio.create_task(
                        asyncio.to_thread(
                            bridge.handle_incoming,
                            sender,
                            text,
                            "whatsapp",
                        )
                    )
                    task.add_done_callback(_log_task_exception)

        return Response("OK", status_code=200)

    # ----------------------------------------------------------
    # SendBlue (iMessage / SMS)
    # ----------------------------------------------------------

    @router.post("/sendblue")
    async def sendblue_incoming(request: Request) -> Response:
        payload = await request.json()

        # Get the SendBlue channel — may be passed at init or set later
        sb = sendblue_channel or getattr(
            request.app.state, "sendblue_channel", None
        )

        # Verify webhook secret if configured
        if sb and sb.webhook_secret:
            header_secret = request.headers.get("x-sendblue-secret", "")
            if header_secret != sb.webhook_secret:
                return Response("Invalid secret", status_code=403)

        # Ignore outbound status callbacks
        if payload.get("is_outbound", False):
            return Response("OK", status_code=200)

        from_number = payload.get("from_number", "")
        content = payload.get("content", "")

        if not from_number or not content:
            return Response("OK", status_code=200)

        # Capture sb for the closure
        reply_channel = sb
        # Also check for a dynamically-created bridge on app.state
        active_bridge = bridge or getattr(
            request.app.state, "channel_bridge", None
        )

        if not active_bridge:
            logger.warning("No channel bridge — cannot process SendBlue msg")
            return Response("OK", status_code=200)

        def _handle_and_reply() -> None:
            response = active_bridge.handle_incoming(
                from_number, content, "sendblue"
            )
            # Send the agent's response back via SendBlue
            if response and reply_channel:
                reply_channel.send(from_number, response)

        task = asyncio.create_task(asyncio.to_thread(_handle_and_reply))
        task.add_done_callback(_log_task_exception)

        return Response("OK", status_code=200)

    return router
