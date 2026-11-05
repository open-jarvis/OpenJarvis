"""Team requests, orchestrator, publisher connections and approved publishing.

Registered on the managed-agents router (``/v1/managed-agents``). Operator
facing errors are Arabic. Credentials are accepted only on creation and never
returned.
"""

from __future__ import annotations

import json
import mimetypes
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_PREVIEW_SUFFIXES = _IMAGE_SUFFIXES | {".html", ".json"}
_MAX_UPLOAD = 20_000_000
_MAX_PHOTOS = 10


class LeadRequest(BaseModel):
    agent_id: Optional[str] = None


class FollowUpRequest(BaseModel):
    content: str
    files: List[str] = []


class RunLimitRequest(BaseModel):
    max_runs: int


class ChannelRequest(BaseModel):
    channel_id: str


def _http(exc: Exception, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


async def _save_image(upload: UploadFile, folder: Path, stem: str) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in _IMAGE_SUFFIXES:
        raise HTTPException(400, "ارفع صور PNG أو JPEG أو WebP فقط.")
    data = await upload.read(_MAX_UPLOAD + 1)
    if len(data) > _MAX_UPLOAD:
        raise HTTPException(400, "حجم الصورة أكبر من 20 ميجابايت.")
    if not (
        data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"\xff\xd8\xff")
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    ):
        raise HTTPException(400, "الملف المرفوع ليس صورة صالحة.")
    path = folder / f"{stem}{'.jpg' if suffix == '.jpeg' else suffix}"
    path.write_bytes(data)
    path.chmod(0o600)
    return f"originals/{path.name}"


def register_campaign_routes(router: Any, manager: Any) -> None:
    from openjarvis.agents.campaigns import HandoffRejected
    from openjarvis.marketing import publisher

    store = manager.campaigns  # Also creates the lead column.

    def campaign_or_404(campaign_id: str) -> Dict[str, Any]:
        campaign = store.get_campaign(campaign_id)
        if campaign is None:
            raise HTTPException(404, "الطلب غير موجود.")
        return campaign

    def view(campaign: Dict[str, Any], *, detail: bool = False) -> Dict[str, Any]:
        handoffs = store.list_handoffs(campaign["id"])
        open_count = sum(
            h["status"] in {"pending", "running", "waiting_paused"} for h in handoffs
        )
        attention = [h for h in handoffs if h["status"] in {"blocked", "failed"}]
        value = dict(campaign)
        if campaign["status"] == "active" and attention and not open_count:
            value["display_status"] = "needs_attention"
        elif campaign["status"] == "active" and not open_count:
            value["display_status"] = "waiting_for_you"
        else:
            value["display_status"] = campaign["status"]
        value["open_handoffs"] = open_count
        value["attention_count"] = len(attention)
        if detail:
            names = {
                a["id"]: a["name"] for a in manager.list_agents(include_archived=True)
            }
            for handoff in handoffs:
                handoff["source_name"] = (
                    names.get(handoff["source_agent_id"], "")
                    if handoff["source_agent_id"]
                    else "أنت"
                )
                handoff["target_name"] = names.get(handoff["target_agent_id"], "")
                handoff["result"] = None
                if handoff["result_message_id"]:
                    message = next(
                        (
                            m
                            for m in manager.list_messages(
                                handoff["target_agent_id"], limit=200
                            )
                            if m["id"] == handoff["result_message_id"]
                        ),
                        None,
                    )
                    handoff["result"] = (message or {}).get("content")
            value["handoffs"] = handoffs
            value["files"] = store.list_files(campaign)
            value["publications"] = publisher.list_publications(manager, campaign["id"])
        return value

    # ── Orchestrator ─────────────────────────────────────────────

    @router.put("/teams/{team_id}/lead")
    async def set_team_lead(team_id: str, req: LeadRequest):
        try:
            store.set_team_lead(team_id, req.agent_id)
        except KeyError as exc:
            raise _http(exc, 404) from exc
        except HandoffRejected as exc:
            raise _http(exc) from exc
        return manager.get_team(team_id)

    # ── Requests to the team ─────────────────────────────────────

    @router.get("/teams/{team_id}/campaigns")
    async def list_campaigns(team_id: str):
        if manager.get_team(team_id) is None:
            raise HTTPException(404, "الفريق غير موجود.")
        return {"campaigns": [view(c) for c in store.list_campaigns(team_id)]}

    @router.post("/teams/{team_id}/campaigns", status_code=201)
    async def create_campaign(
        team_id: str,
        title: str = Form(...),
        brief: str = Form(...),
        contact: str = Form(""),
        allow_bria: bool = Form(False),
        max_runs: int = Form(16),
        photos: List[UploadFile] = File(default=[]),
        logo: Optional[UploadFile] = File(default=None),
    ):
        if manager.get_team(team_id) is None:
            raise HTTPException(404, "الفريق غير موجود.")
        if len(photos) > _MAX_PHOTOS:
            raise HTTPException(400, f"ارفع حتى {_MAX_PHOTOS} صور.")
        contact = contact.strip()
        if len(contact) > 160:
            raise HTTPException(400, "بيانات التواصل حتى 160 حرفًا.")
        try:
            campaign = store.create_campaign(
                team_id,
                title=title,
                brief=brief,
                options={"contact": contact, "allow_bria": bool(allow_bria)},
                max_runs=max_runs,
            )
        except KeyError as exc:
            raise _http(exc, 404) from exc
        except HandoffRejected as exc:
            raise _http(exc) from exc
        folder = store.campaign_dir(team_id, campaign["id"]) / "originals"
        files = []
        try:
            for index, photo in enumerate(photos, start=1):
                files.append(await _save_image(photo, folder, f"product-{index}"))
            options = dict(campaign["options"])
            if logo is not None and logo.filename:
                options["logo"] = await _save_image(logo, folder, "logo")
                files.append(options["logo"])
            with manager._db_lock:
                manager._conn.execute(
                    "UPDATE agent_campaigns SET options_json = ? WHERE id = ?",
                    (json.dumps(options, ensure_ascii=False), campaign["id"]),
                )
                manager._conn.commit()
            store.add_request(campaign["id"], content=brief, files=files)
        except HTTPException:
            store.set_campaign_status(campaign["id"], "failed", "تعذّر حفظ المرفقات.")
            raise
        except HandoffRejected as exc:
            store.set_campaign_status(campaign["id"], "failed", str(exc))
            raise _http(exc) from exc
        return view(store.get_campaign(campaign["id"]), detail=True)

    @router.get("/campaigns/{campaign_id}")
    async def get_campaign(campaign_id: str):
        return view(campaign_or_404(campaign_id), detail=True)

    @router.post("/campaigns/{campaign_id}/messages", status_code=201)
    async def follow_up(campaign_id: str, req: FollowUpRequest):
        campaign_or_404(campaign_id)
        try:
            store.add_request(
                campaign_id,
                content=req.content,
                files=req.files,
                title="رسالة متابعة منك",
            )
        except HandoffRejected as exc:
            raise _http(exc) from exc
        return view(store.get_campaign(campaign_id), detail=True)

    @router.post("/campaigns/{campaign_id}/cancel")
    async def cancel_campaign(campaign_id: str):
        campaign_or_404(campaign_id)
        store.set_campaign_status(campaign_id, "cancelled", "أوقفت الطلب.")
        return view(store.get_campaign(campaign_id), detail=True)

    @router.put("/campaigns/{campaign_id}/max-runs")
    async def set_max_runs(campaign_id: str, req: RunLimitRequest):
        campaign_or_404(campaign_id)
        try:
            store.set_max_runs(campaign_id, req.max_runs)
        except HandoffRejected as exc:
            raise _http(exc) from exc
        return view(store.get_campaign(campaign_id), detail=True)

    @router.post("/handoffs/{handoff_id}/retry")
    async def retry_handoff(handoff_id: str):
        try:
            handoff = store.retry_handoff(handoff_id)
        except KeyError as exc:
            raise _http(exc, 404) from exc
        except HandoffRejected as exc:
            raise _http(exc) from exc
        return view(store.get_campaign(handoff["campaign_id"]), detail=True)

    @router.get("/campaigns/{campaign_id}/file")
    async def campaign_file(campaign_id: str, path: str):
        """Preview one file of this request; nothing outside its folder."""
        campaign = campaign_or_404(campaign_id)
        try:
            file = store.resolve_campaign_file(campaign, path)
        except HandoffRejected as exc:
            raise _http(exc, 404) from exc
        if file.suffix.lower() not in _PREVIEW_SUFFIXES:
            raise HTTPException(404, "نوع الملف غير متاح للمعاينة.")
        media = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        headers = {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            # Drafts are self-contained; never let them run with this origin.
            "Content-Security-Policy": "sandbox; default-src 'none'; img-src data:;"
            " style-src 'unsafe-inline'",
        }
        return FileResponse(file, media_type=media, headers=headers)

    # ── Publications (approved Buffer posts) ─────────────────────

    @router.post("/publications/{action_id}/retry")
    async def retry_publication(action_id: str):
        try:
            return publisher.retry(manager, action_id)
        except publisher.PublishError as exc:
            raise _http(exc, 409) from exc

    @router.post("/publications/{action_id}/refresh")
    async def refresh_publication(action_id: str):
        from openjarvis.marketing.buffer import BufferError

        try:
            return publisher.refresh_status(manager, action_id)
        except (publisher.PublishError, BufferError) as exc:
            raise _http(exc, 409) from exc

    # ── Publisher connections (Buffer, R2) ───────────────────────

    @router.post("/teams/{team_id}/connections/{connection_id}/verify")
    async def verify_connection(team_id: str, connection_id: str):
        from openjarvis.marketing.buffer import BufferClient, BufferError
        from openjarvis.marketing.r2 import R2Client, R2Error

        connection = manager.get_team_connection(team_id, connection_id)
        if connection is None:
            raise HTTPException(404, "الاتصال غير موجود.")
        token = manager._team_connection_token(connection_id)
        extra: Dict[str, Any] = {}
        try:
            if connection["kind"] == "buffer":
                account = BufferClient(token).verify()
                orgs = account.get("organizations") or []
                org = connection["settings"].get("organization_id")
                if not org and len(orgs) == 1:
                    org = orgs[0]["id"]
                if org and org not in {o["id"] for o in orgs}:
                    raise BufferError("المؤسسة المحددة غير موجودة في حساب Buffer هذا.")
                extra = {"organizations": orgs, "channels": []}
                if org:
                    extra["channels"] = [
                        {
                            k: c.get(k)
                            for k in (
                                "id",
                                "name",
                                "displayName",
                                "service",
                                "timezone",
                                "isQueuePaused",
                            )
                        }
                        for c in BufferClient(token).channels(org)
                    ]
                manager.update_team_connection_settings(
                    team_id,
                    connection_id,
                    organization_id=org,
                    verified_at=time.time(),
                    last_error=None,
                )
            elif connection["kind"] == "r2":
                settings = connection["settings"]
                R2Client(
                    account_id=settings["account_id"],
                    bucket=settings["bucket"],
                    access_key_id=settings["access_key_id"],
                    secret_access_key=token,
                    public_base_url=settings["public_base_url"],
                ).verify()
                manager.update_team_connection_settings(
                    team_id, connection_id, verified_at=time.time(), last_error=None
                )
            else:
                raise HTTPException(400, "التحقق متاح لاتصالات Buffer وR2 فقط.")
        except (BufferError, R2Error) as exc:
            manager.update_team_connection_settings(
                team_id, connection_id, verified_at=None, last_error=str(exc)
            )
            raise _http(exc, 409) from exc
        result = manager.get_team_connection(team_id, connection_id)
        result.update(extra)
        return result

    @router.put("/teams/{team_id}/connections/{connection_id}/channel")
    async def choose_channel(team_id: str, connection_id: str, req: ChannelRequest):
        from openjarvis.marketing.buffer import BufferClient, BufferError

        connection = manager.get_team_connection(team_id, connection_id)
        if connection is None or connection["kind"] != "buffer":
            raise HTTPException(404, "اتصال Buffer غير موجود.")
        org = connection["settings"].get("organization_id")
        if not org or connection["status"] != "verified":
            raise HTTPException(409, "تحقق من اتصال Buffer أولًا.")
        try:
            channels = BufferClient(
                manager._team_connection_token(connection_id)
            ).channels(org)
        except BufferError as exc:
            raise _http(exc, 409) from exc
        channel = next((c for c in channels if c.get("id") == req.channel_id), None)
        if channel is None:
            raise HTTPException(400, "القناة غير موجودة في مؤسسة Buffer هذه.")
        return manager.update_team_connection_settings(
            team_id,
            connection_id,
            channel_id=channel["id"],
            channel_name=channel.get("displayName") or channel.get("name"),
            channel_service=channel.get("service"),
            channel_timezone=channel.get("timezone"),
        )


def approve_marketing_action(request: Request, action: Any) -> Dict[str, Any]:
    """Called by the approval route for marketing actions only."""
    from openjarvis.marketing import publisher

    manager = getattr(request.app.state, "agent_manager", None)
    if manager is None:
        raise HTTPException(503, "مدير الوكلاء غير متاح؛ أعد تشغيل الخادم.")
    try:
        return publisher.approve(manager, action.id)
    except publisher.PublishError as exc:
        raise HTTPException(409, str(exc)) from exc


def deny_marketing_action(request: Request, action: Any) -> None:
    from openjarvis.marketing import publisher

    manager = getattr(request.app.state, "agent_manager", None)
    if manager is not None:
        publisher.deny(manager, action.id)


__all__ = [
    "approve_marketing_action",
    "deny_marketing_action",
    "register_campaign_routes",
]
