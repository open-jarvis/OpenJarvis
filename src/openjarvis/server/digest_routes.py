"""FastAPI routes for the morning digest."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from openjarvis.agents.digest_store import DigestStore


def create_digest_router(*, db_path: str = "") -> APIRouter:
    """Create a digest API router with the given store path."""
    router = APIRouter(prefix="/api/digest", tags=["digest"])
    store = DigestStore(db_path=db_path) if db_path else DigestStore()

    @router.get("")
    async def get_digest():
        """Return the latest digest artifact."""
        artifact = store.get_today()
        if artifact is None:
            raise HTTPException(status_code=404, detail="No digest for today")
        return {
            "text": artifact.text,
            "sections": artifact.sections,
            "sources_used": artifact.sources_used,
            "generated_at": artifact.generated_at.isoformat(),
            "model_used": artifact.model_used,
            "voice_used": artifact.voice_used,
            "audio_available": (
                artifact.audio_path.exists() if artifact.audio_path.name else False
            ),
        }

    @router.get("/audio")
    async def get_digest_audio():
        """Stream the digest audio file."""
        artifact = store.get_today()
        if artifact is None:
            raise HTTPException(status_code=404, detail="No digest for today")
        if not artifact.audio_path.exists():
            raise HTTPException(status_code=404, detail="Audio not available")
        return FileResponse(
            str(artifact.audio_path),
            media_type="audio/mpeg",
            filename="digest.mp3",
        )

    @router.post("/generate")
    async def generate_digest():
        """Force re-generation of the digest."""
        try:
            from openjarvis.sdk import Jarvis

            with Jarvis() as j:
                result = j.ask("Generate my morning digest", agent="morning_digest")
            return {"status": "ok", "text": result}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/history")
    async def get_digest_history():
        """Return past digests."""
        history = store.history(limit=10)
        return [
            {
                "text": a.text[:200],
                "generated_at": a.generated_at.isoformat(),
                "model_used": a.model_used,
                "voice_used": a.voice_used,
            }
            for a in history
        ]

    return router
