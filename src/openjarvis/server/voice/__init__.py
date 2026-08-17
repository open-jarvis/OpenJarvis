"""Voice: one Pipecat/WebRTC pipeline, Gemini Live STT, local VieNeu TTS.

``app.py`` needs four names from here. Everything else is internal.

Note the two routers are separate on purpose. ``availability_router`` mounts
unconditionally so the UI can always ask why voice is off; ``voice_router``
mounts only when the Gemini gate opens. Do not merge them — see
``tests/server/test_voice_availability_router.py::test_availability_router_is_mounted_by_create_app_when_gate_is_closed``.

``voice_router`` is ``None`` when the optional ``pipecat-ai`` extra is absent.
Only the WebRTC pipeline needs it; the gate and the session service are pure
Python, so an install without the extra still imports this package, still
serves ``/api/voice/availability``, and reports ``voice_runtime_missing``
instead of taking the whole API server down at import time.
"""

from openjarvis.server.voice.gate import gemini_live_poc_available
from openjarvis.server.voice.gate import router as availability_router
from openjarvis.server.voice.session import VoiceSessionService

try:
    from openjarvis.server.voice.routes import router as voice_router
except ImportError:  # pipecat-ai[google,silero,webrtc] not installed
    voice_router = None

__all__ = [
    "VoiceSessionService",
    "availability_router",
    "gemini_live_poc_available",
    "voice_router",
]
