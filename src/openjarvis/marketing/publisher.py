"""Human-approved Buffer scheduling for a team's final creative.

Flow: an agent submits an exact final PNG + caption + Cairo time for review →
an immutable copy is stored under ``approved/<sha256>.png`` and a high-tier
approval is queued → the operator sees the image, caption, channel and time and
approves → only then the server uploads that exact file to the company's R2
bucket and creates one scheduled Buffer post with the company's own key.

Each publication is a persisted state machine so a crash, timeout or retry can
never schedule twice: an uncertain create is reconciled by looking the post up
in Buffer before any new create. Operator-facing text is Arabic.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import shutil
import time
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from openjarvis.marketing.render import png_size, sha256, sidecar

logger = logging.getLogger(__name__)

ACTION_TYPE = "marketing_buffer_schedule"
CAIRO = ZoneInfo("Africa/Cairo")
MIN_LEAD_SECONDS = 10 * 60
MAX_CREATE_ATTEMPTS = 3
STATE_LABELS = {
    "awaiting_approval": "بانتظار موافقتك",
    "approved": "تمت الموافقة؛ جارٍ التجهيز",
    "uploading": "جارٍ رفع الصورة",
    "uploaded": "رُفعت الصورة؛ جارٍ الجدولة",
    "creating": "جارٍ إنشاء المنشور في Buffer",
    "uncertain": "نتيجة غير مؤكدة؛ جارٍ التحقق في Buffer قبل أي إعادة",
    "scheduled": "مجدول في Buffer",
    "failed": "فشلت الجدولة",
    "denied": "رُفض؛ يلزم تعديل وموافقة جديدة",
}

_CREATE = """
CREATE TABLE IF NOT EXISTS marketing_publications (
    action_id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    image_path TEXT NOT NULL,
    image_sha256 TEXT NOT NULL,
    caption TEXT NOT NULL,
    caption_sha256 TEXT NOT NULL,
    scheduled_local TEXT NOT NULL,
    due_at_utc TEXT NOT NULL,
    state TEXT NOT NULL,
    state_reason TEXT NOT NULL DEFAULT '',
    buffer_connection_id TEXT,
    r2_connection_id TEXT,
    channel_id TEXT,
    channel_name TEXT,
    object_key TEXT,
    image_url TEXT,
    buffer_post_id TEXT,
    buffer_status TEXT,
    buffer_due_at TEXT,
    create_attempts INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    quality_review TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""


class PublishError(ValueError):
    """Arabic message safe to show the operator."""


def _ensure(manager: Any) -> None:
    if getattr(manager, "_publications_ready", False):
        return
    with manager._db_lock:
        manager._conn.executescript(_CREATE)
        manager._conn.commit()
    manager._publications_ready = True


def _row(manager: Any, action_id: str) -> Optional[Dict[str, Any]]:
    _ensure(manager)
    with manager._db_lock:
        row = manager._conn.execute(
            "SELECT * FROM marketing_publications WHERE action_id = ?", (action_id,)
        ).fetchone()
    return dict(row) if row else None


def _set(manager: Any, action_id: str, **fields: Any) -> None:
    keys = list(fields)
    with manager._db_lock:
        manager._conn.execute(
            f"UPDATE marketing_publications SET "
            f"{''.join(f'{k} = ?, ' for k in keys)}updated_at = ? WHERE action_id = ?",
            (*[fields[k] for k in keys], time.time(), action_id),
        )
        manager._conn.commit()


def list_publications(manager: Any, campaign_id: str) -> List[Dict[str, Any]]:
    _ensure(manager)
    with manager._db_lock:
        rows = manager._conn.execute(
            "SELECT * FROM marketing_publications WHERE campaign_id = ? "
            "ORDER BY created_at DESC",
            (campaign_id,),
        ).fetchall()
    result = []
    for row in rows:
        value = dict(row)
        value["state_label"] = STATE_LABELS.get(value["state"], value["state"])
        result.append(value)
    return result


def parse_cairo_time(value: str) -> dt.datetime:
    """Accept 'YYYY-MM-DD HH:MM' (Cairo) or ISO 8601 with an offset."""
    text = (value or "").strip()
    try:
        when = dt.datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        raise PublishError(
            "صيغة الموعد غير صحيحة؛ استخدم YYYY-MM-DD HH:MM بتوقيت القاهرة."
        ) from None
    if when.tzinfo is None:
        when = when.replace(tzinfo=CAIRO)
    return when.astimezone(CAIRO)


def _store():
    from openjarvis.tools.proactive_tools import get_store

    return get_store()


# ── Submission (agent) ──────────────────────────────────────────────


def submit_for_approval(
    manager: Any,
    *,
    agent_id: str,
    campaign: Dict[str, Any],
    final_png: str,
    caption: str,
    scheduled_at: str,
    quality_review: str,
) -> Dict[str, Any]:
    _ensure(manager)
    store = manager.campaigns
    path = store.resolve_campaign_file(campaign, final_png)
    root = store.campaign_dir(campaign["team_id"], campaign["id"]).resolve()
    if path.parent.name != "final" or path.suffix.lower() != ".png":
        raise PublishError("أرسل صورة PNG نهائية من مجلد final الخاص بالطلب.")
    if png_size(path) != (1080, 1080):
        raise PublishError("الصورة النهائية يجب أن تكون 1080×1080.")
    meta = sidecar(path)
    digest = sha256(path)
    if not meta or meta.get("png_sha256") != digest:
        raise PublishError(
            "هذه الصورة لم تُنتَج بأداة التصميم المعتمدة أو عُدّلت بعد تصديرها؛ "
            "أعد تصديرها بـ marketing_creative."
        )
    caption = (caption or "").strip()
    if not caption or len(caption) > 3000:
        raise PublishError("نص المنشور مطلوب (حتى 3000 حرف).")
    if not (quality_review or "").strip():
        raise PublishError("نتيجة مراجعة الجودة مطلوبة قبل طلب الموافقة.")
    when = parse_cairo_time(scheduled_at)
    seconds = (when - dt.datetime.now(CAIRO)).total_seconds()
    if seconds < MIN_LEAD_SECONDS:
        raise PublishError("الموعد يجب أن يكون بعد 10 دقائق على الأقل من الآن.")
    if seconds > 60 * 86400:
        raise PublishError("الموعد يجب أن يكون خلال 60 يومًا.")
    due_utc = when.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    caption_sha = hashlib.sha256(caption.encode()).hexdigest()

    # Immutable approved copy: later edits to final/ never change what is approved.
    approved = root / "approved" / f"{digest}.png"
    if not approved.exists():
        approved.parent.mkdir(exist_ok=True, mode=0o700)
        shutil.copyfile(path, approved)
        approved.chmod(0o600)
    approved_rel = str(approved.relative_to(root))

    with manager._db_lock:
        existing = manager._conn.execute(
            "SELECT action_id FROM marketing_publications WHERE campaign_id = ? "
            "AND image_sha256 = ? AND caption_sha256 = ? AND due_at_utc = ? "
            "AND state = 'awaiting_approval'",
            (campaign["id"], digest, caption_sha, due_utc),
        ).fetchone()
    if existing:
        return {"action_id": existing["action_id"], "status": "pending_approval"}

    reconstructed = bool(meta.get("needs_reconstruction_review"))
    buffer_conn = manager.team_connection_of_kind(campaign["team_id"], "buffer")
    payload = {
        "team_id": campaign["team_id"],
        "campaign_id": campaign["id"],
        "image": approved_rel,
        "image_sha256": digest,
        "caption": caption,
        "caption_sha256": caption_sha,
        "scheduled_local": when.isoformat(),
        "timezone": "Africa/Cairo",
        "due_at_utc": due_utc,
        "quality_review": quality_review.strip()[:6000],
        "needs_reconstruction_review": reconstructed,
        "channel_id": (buffer_conn or {}).get("settings", {}).get("channel_id"),
        "channel_name": (buffer_conn or {}).get("settings", {}).get("channel_name"),
        "submitted_by": agent_id,
    }
    team = manager.get_team(campaign["team_id"]) or {}
    action = _store().queue_action(
        action_type=ACTION_TYPE,
        description=(
            f"جدولة منشور في Buffer — {team.get('name', '')} / {campaign['title']} — "
            f"{when.strftime('%Y-%m-%d %H:%M')} بتوقيت القاهرة"
        ),
        payload=payload,
        permission_key=f"{ACTION_TYPE}:{digest[:16]}:{caption_sha[:16]}",
        tier="high",
        ttl_hours=max(1, int(seconds // 3600)),
    )
    now = time.time()
    with manager._db_lock:
        manager._conn.execute(
            "INSERT INTO marketing_publications (action_id, team_id, campaign_id, "
            "image_path, image_sha256, caption, caption_sha256, scheduled_local, "
            "due_at_utc, state, channel_id, channel_name, needs_review, "
            "quality_review, created_at, updated_at) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, 'awaiting_approval', ?, ?, ?, ?, ?, ?)",
            (
                action.id,
                campaign["team_id"],
                campaign["id"],
                approved_rel,
                digest,
                caption,
                caption_sha,
                when.isoformat(),
                due_utc,
                payload["channel_id"],
                payload["channel_name"],
                int(reconstructed),
                payload["quality_review"],
                now,
                now,
            ),
        )
        manager._conn.commit()
    store.set_campaign_status(
        campaign["id"], "awaiting_approval", "المسودة جاهزة وتنتظر موافقتك."
    )
    return {
        "action_id": action.id,
        "status": "pending_approval",
        "scheduled": False,
        "needs_reconstruction_review": reconstructed,
    }


# ── Approval (operator) ─────────────────────────────────────────────


def _publisher_connections(manager: Any, team_id: str) -> tuple[dict, dict]:
    buffer_conn = manager.team_connection_of_kind(team_id, "buffer")
    r2_conn = manager.team_connection_of_kind(team_id, "r2")
    if not buffer_conn or buffer_conn["status"] != "verified":
        raise PublishError(
            "اتصال Buffer الخاص بالفريق غير موجود أو لم يُتحقق منه بعد. "
            "أضفه وتحقّق منه من «اتصالات الفريق»؛ لن نستخدم أي حساب عام."
        )
    if not buffer_conn["settings"].get("channel_id"):
        raise PublishError("اختر قناة Buffer للفريق قبل الموافقة.")
    if not r2_conn or r2_conn["status"] != "verified":
        raise PublishError(
            "اتصال Cloudflare R2 للفريق غير موجود أو لم يُتحقق منه؛ Buffer يحتاج "
            "رابطًا عامًا للصورة."
        )
    return buffer_conn, r2_conn


def approve(manager: Any, action_id: str) -> Dict[str, Any]:
    """Validate the exact approved version, then queue it for dispatch."""
    from openjarvis.tools.approval_store import STATUS_APPROVED, STATUS_PENDING

    store = _store()
    store.expire_stale()
    action = store.get_action(action_id)
    pub = _row(manager, action_id)
    if action is None or pub is None or action.action_type != ACTION_TYPE:
        raise PublishError("طلب الموافقة غير موجود.")
    if action.status != STATUS_PENDING or pub["state"] != "awaiting_approval":
        raise PublishError("لا يمكن الموافقة على هذا الطلب في حالته الحالية.")
    payload = action.payload
    for key, column in (
        ("image_sha256", "image_sha256"),
        ("caption_sha256", "caption_sha256"),
        ("due_at_utc", "due_at_utc"),
        ("image", "image_path"),
    ):
        if payload.get(key) != pub[column]:
            raise PublishError("بيانات الموافقة لا تطابق المسودة المسجلة.")
    if hashlib.sha256(pub["caption"].encode()).hexdigest() != pub["caption_sha256"]:
        raise PublishError("نص المنشور تغيّر بعد إرساله للموافقة.")
    campaign = manager.campaigns.get_campaign(pub["campaign_id"])
    if campaign is None:
        raise PublishError("الطلب المرتبط غير موجود.")
    image = manager.campaigns.resolve_campaign_file(campaign, pub["image_path"])
    if sha256(image) != pub["image_sha256"]:
        raise PublishError(
            "الصورة تغيّرت بعد إرسالها للموافقة؛ يلزم مراجعة وموافقة جديدة."
        )
    due = dt.datetime.fromisoformat(pub["due_at_utc"].replace("Z", "+00:00"))
    if (due - dt.datetime.now(dt.UTC)).total_seconds() < 120:
        raise PublishError("موعد النشر قريب جدًا أو مضى؛ اطلب موعدًا جديدًا.")
    buffer_conn, r2_conn = _publisher_connections(manager, pub["team_id"])
    store.update_status(action_id, STATUS_APPROVED)
    _set(
        manager,
        action_id,
        state="approved",
        state_reason="",
        buffer_connection_id=buffer_conn["id"],
        r2_connection_id=r2_conn["id"],
        channel_id=buffer_conn["settings"]["channel_id"],
        channel_name=buffer_conn["settings"].get("channel_name"),
    )
    return {"status": "approved", "state": "approved"}


def deny(manager: Any, action_id: str) -> None:
    pub = _row(manager, action_id)
    if pub and pub["state"] == "awaiting_approval":
        _set(manager, action_id, state="denied", state_reason="رفض المستخدم المسودة.")
        manager.campaigns.set_campaign_status(
            pub["campaign_id"],
            "changes_requested",
            "رفضت المسودة؛ أرسل ملاحظاتك للفريق لإعداد نسخة جديدة.",
        )


# ── Dispatch (server loop) ──────────────────────────────────────────


def _clients(manager: Any, pub: Dict[str, Any], *, transport: Any = None):
    from openjarvis.marketing.buffer import BufferClient
    from openjarvis.marketing.r2 import R2Client

    buffer_conn = manager.get_team_connection(
        pub["team_id"], pub["buffer_connection_id"]
    )
    r2_conn = manager.get_team_connection(pub["team_id"], pub["r2_connection_id"])
    if not buffer_conn or not r2_conn:
        raise PublishError(
            "حُذف اتصال Buffer أو R2 الخاص بالفريق بعد الموافقة؛ أوقفنا الجدولة."
        )
    r2_settings = r2_conn["settings"]
    return (
        BufferClient(
            manager._team_connection_token(buffer_conn["id"]), transport=transport
        ),
        buffer_conn,
        R2Client(
            account_id=r2_settings["account_id"],
            bucket=r2_settings["bucket"],
            access_key_id=r2_settings["access_key_id"],
            secret_access_key=manager._team_connection_token(r2_conn["id"]),
            public_base_url=r2_settings["public_base_url"],
            transport=transport,
        ),
    )


def recover_interrupted(manager: Any) -> None:
    """A create interrupted by a restart may have succeeded: reconcile first."""
    _ensure(manager)
    with manager._db_lock:
        manager._conn.execute(
            "UPDATE marketing_publications SET state = 'uncertain', state_reason = ? "
            "WHERE state = 'creating'",
            ("انقطع الخادم أثناء إنشاء المنشور؛ سنتحقق في Buffer قبل أي إعادة.",),
        )
        manager._conn.execute(
            "UPDATE marketing_publications SET state = 'approved' "
            "WHERE state = 'uploading'"
        )
        manager._conn.commit()


def process_due(manager: Any, *, transport: Any = None) -> int:
    """Advance approved publications one step each. Returns steps taken."""
    _ensure(manager)
    with manager._db_lock:
        rows = manager._conn.execute(
            "SELECT action_id FROM marketing_publications WHERE state IN "
            "('approved', 'uploaded', 'uncertain') ORDER BY updated_at LIMIT 10"
        ).fetchall()
    steps = 0
    for row in rows:
        try:
            _advance(manager, row["action_id"], transport=transport)
        except PublishError as exc:
            _fail(manager, row["action_id"], str(exc))
        except Exception:
            logger.exception("Publication %s failed", row["action_id"])
            _fail(manager, row["action_id"], "خطأ غير متوقع أثناء الجدولة.")
        steps += 1
    return steps


def _fail(manager: Any, action_id: str, reason: str) -> None:
    pub = _row(manager, action_id)
    _set(manager, action_id, state="failed", state_reason=reason)
    if pub:
        manager.campaigns.set_campaign_status(
            pub["campaign_id"], "publish_failed", f"فشلت الجدولة في Buffer: {reason}"
        )


def _advance(manager: Any, action_id: str, *, transport: Any = None) -> None:
    from openjarvis.marketing.buffer import BufferError
    from openjarvis.marketing.r2 import R2Error

    pub = _row(manager, action_id)
    if pub is None:
        return
    buffer, buffer_conn, r2 = _clients(manager, pub, transport=transport)
    org = buffer_conn["settings"].get("organization_id")
    if pub["state"] == "approved":
        campaign = manager.campaigns.get_campaign(pub["campaign_id"])
        image = manager.campaigns.resolve_campaign_file(campaign, pub["image_path"])
        if sha256(image) != pub["image_sha256"]:
            raise PublishError("الصورة المعتمدة تغيّرت قبل رفعها؛ أوقفنا الجدولة.")
        key = pub["object_key"] or r2.new_key()
        _set(manager, action_id, state="uploading", object_key=key)
        try:
            url = r2.put_png(key, image.read_bytes())
        except R2Error as exc:
            raise PublishError(str(exc)) from None
        _set(manager, action_id, state="uploaded", image_url=url, state_reason="")
        return
    if pub["state"] == "uncertain":
        found = None
        if org:
            due = dt.datetime.fromisoformat(pub["due_at_utc"].replace("Z", "+00:00"))
            fmt = "%Y-%m-%dT%H:%M:%SZ"
            try:
                found = buffer.find_post(
                    organization_id=org,
                    channel_id=pub["channel_id"],
                    text=pub["caption"],
                    due_at_start=(due - dt.timedelta(minutes=2)).strftime(fmt),
                    due_at_end=(due + dt.timedelta(minutes=2)).strftime(fmt),
                )
            except BufferError as exc:
                _set(manager, action_id, state_reason=f"تعذّر التحقق بعد: {exc}")
                return  # Stay uncertain; check again on the next pass.
        if found:
            _scheduled(manager, action_id, found)
            return
        if not org:
            raise PublishError(
                "النتيجة غير مؤكدة ولا يمكن التحقق دون معرّف مؤسسة Buffer؛ "
                "راجع Buffer يدويًا قبل أي إعادة."
            )
        if pub["create_attempts"] >= MAX_CREATE_ATTEMPTS:
            raise PublishError(
                "نتيجة غير مؤكدة بعد عدة محاولات؛ راجع Buffer يدويًا قبل أي إعادة."
            )
        _set(
            manager,
            action_id,
            state="uploaded",
            state_reason="لم نجد المنشور؛ سنعيد الإنشاء.",
        )
        return
    if pub["state"] == "uploaded":
        due = dt.datetime.fromisoformat(pub["due_at_utc"].replace("Z", "+00:00"))
        if (due - dt.datetime.now(dt.UTC)).total_seconds() < 60:
            raise PublishError("مضى موعد النشر قبل إتمام الجدولة.")
        # Persist intent before the request: a crash now is reconciled, not repeated.
        _set(
            manager,
            action_id,
            state="creating",
            create_attempts=pub["create_attempts"] + 1,
        )
        try:
            post = buffer.create_scheduled_post(
                channel_id=pub["channel_id"],
                text=pub["caption"],
                due_at=pub["due_at_utc"],
                image_url=pub["image_url"],
            )
        except BufferError as exc:
            if exc.uncertain:
                _set(manager, action_id, state="uncertain", state_reason=str(exc))
                return
            raise PublishError(str(exc)) from None
        _scheduled(manager, action_id, post)


def _scheduled(manager: Any, action_id: str, post: Dict[str, Any]) -> None:
    from openjarvis.tools.approval_store import STATUS_EXECUTED

    pub = _row(manager, action_id)
    _set(
        manager,
        action_id,
        state="scheduled",
        state_reason="",
        buffer_post_id=post.get("id"),
        buffer_status=str(post.get("status") or ""),
        buffer_due_at=post.get("dueAt"),
    )
    _store().update_status(action_id, STATUS_EXECUTED)
    if pub:
        local = dt.datetime.fromisoformat(pub["scheduled_local"])
        manager.campaigns.set_campaign_status(
            pub["campaign_id"],
            "scheduled",
            f"مجدول في Buffer ({post.get('id')}) — "
            f"{local.strftime('%Y-%m-%d %H:%M')} بتوقيت القاهرة.",
        )


def refresh_status(manager: Any, action_id: str, *, transport: Any = None) -> Dict:
    """Read the post's actual state back from Buffer."""
    pub = _row(manager, action_id)
    if not pub or not pub["buffer_post_id"]:
        raise PublishError("لا يوجد منشور مجدول لهذا الطلب بعد.")
    buffer, _, _ = _clients(manager, pub, transport=transport)
    post = buffer.get_post(pub["buffer_post_id"])
    if not post:
        raise PublishError("لم يعد Buffer يجد هذا المنشور.")
    _set(
        manager,
        action_id,
        buffer_status=str(post.get("status") or ""),
        buffer_due_at=post.get("dueAt"),
        state_reason=((post.get("error") or {}).get("message") or "")[:300],
    )
    return _row(manager, action_id)  # type: ignore[return-value]


def retry(manager: Any, action_id: str) -> Dict[str, Any]:
    """Operator retry of a failed publication, never a blind re-create."""
    pub = _row(manager, action_id)
    if pub is None or pub["state"] != "failed":
        raise PublishError("يمكن إعادة المحاولة للجدولة الفاشلة فقط.")
    if not pub["buffer_connection_id"]:
        raise PublishError("لم تتم الموافقة على هذا الطلب.")
    # Any earlier create may have reached Buffer: reconcile before creating again.
    state = (
        "uncertain"
        if pub["create_attempts"]
        else ("uploaded" if pub["image_url"] else "approved")
    )
    _set(
        manager,
        action_id,
        state=state,
        create_attempts=0 if state == "uncertain" else pub["create_attempts"],
        state_reason="أُعيدت المحاولة بطلب المستخدم.",
    )
    manager.campaigns.set_campaign_status(
        pub["campaign_id"], "awaiting_approval", "جارٍ إعادة محاولة الجدولة."
    )
    return _row(manager, action_id)  # type: ignore[return-value]


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


__all__ = [
    "ACTION_TYPE",
    "PublishError",
    "approve",
    "deny",
    "list_publications",
    "parse_cairo_time",
    "process_due",
    "recover_interrupted",
    "refresh_status",
    "retry",
    "submit_for_approval",
]
