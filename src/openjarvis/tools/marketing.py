"""Marketing production tools bound to the team request an agent is running.

Credentials never enter prompts or artifacts. Every file read or written stays
inside the current request's folder (``team-data/<team>/campaigns/<id>/``):
``originals/`` (operator uploads, never modified), ``drafts/`` (HTML layouts,
Bria outputs), ``final/`` (exported PNGs) and ``approved/`` (immutable copies).
Text, logo and contact details are composed deterministically; no image model
writes package labels, headlines or numbers.
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from typing import Any, Dict, Optional, Tuple

import httpx

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

BRIA_ORIGIN = "https://engine.prod.bria-api.com"
BRIA_POLL_SECONDS = 2.0
BRIA_TIMEOUT_SECONDS = 120.0
_MAX_IMAGE_BYTES = 20_000_000


class ToolFailure(ValueError):
    """Arabic message returned to the agent and shown to the operator."""


class _CampaignTool(BaseTool):
    """Resolve the request this agent is executing; never a model-chosen folder."""

    needs_agent_context = True

    def __init__(self, manager: Any = None, agent_id: Optional[str] = None):
        self._manager = manager
        self._agent_id = agent_id

    def _campaign(self) -> Tuple[Any, Dict[str, Any]]:
        if self._manager is None or not self._agent_id:
            raise ToolFailure("هذه الأداة تعمل فقط لوكلاء الفرق أثناء تنفيذ طلب.")
        store = self._manager.campaigns
        batch = store.running_batch_for(self._agent_id)
        if not batch:
            raise ToolFailure(
                "لا يوجد طلب فريق قيد التنفيذ لهذا الوكيل؛ الأداة متاحة أثناء "
                "المهام المسندة فقط."
            )
        campaign = store.get_campaign(batch[0]["campaign_id"])
        if campaign is None or campaign["status"] != "active":
            raise ToolFailure("الطلب لم يعد نشطًا.")
        return store, campaign

    def _result(self, ok: bool, content: Any) -> ToolResult:
        text = (
            content
            if isinstance(content, str)
            else json.dumps(content, ensure_ascii=False)
        )
        return ToolResult(tool_name=self.spec.name, success=ok, content=text)


# ── Bria ─────────────────────────────────────────────────────────────


class BriaClient:
    """Inject an httpx transport for tests. A configured token is not a health check."""

    def __init__(
        self,
        token: str | None = None,
        transport: Any = None,
        *,
        sleep: Any = time.sleep,
        clock: Any = time.monotonic,
    ):
        self.token = token if token is not None else os.getenv("BRIA_API_TOKEN", "")
        self.transport = transport
        self._sleep, self._clock = sleep, clock

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=60, transport=self.transport, follow_redirects=False
        )

    def _headers(self) -> dict:
        return {"api_token": self.token, "User-Agent": "BriaPlatform/APIdocs/LLMsAgent"}

    @staticmethod
    def _check(response: httpx.Response) -> dict:
        if response.status_code in {401, 403}:
            raise ToolFailure(
                "رفضت Bria بيانات الدخول؛ راجع BRIA_API_TOKEN في الإعدادات."
            )
        if response.status_code == 429:
            raise ToolFailure("Bria مشغولة أو وصل الحساب لحده؛ أعد المحاولة لاحقًا.")
        if response.is_error:
            raise ToolFailure(f"فشل طلب Bria (HTTP {response.status_code}).")
        try:
            return response.json()
        except ValueError:
            raise ToolFailure("ردّ Bria غير مفهوم.") from None

    def submit(self, operation: str, image_b64: str) -> str:
        if not self.token:
            raise ToolFailure(
                "Bria تحتاج إعدادًا: أضف BRIA_API_TOKEN من الإعدادات ← الأدوات."
            )
        payload: dict[str, Any] = {"image": image_b64, "sync": False}
        endpoint = "remove_background"
        if operation == "erase_hand":
            endpoint = "erase_by_text"
            payload["object_name"] = "the hand and sleeve holding the box"
        with self._client() as client:
            data = self._check(
                client.post(
                    f"{BRIA_ORIGIN}/v2/image/edit/{endpoint}",
                    headers=self._headers(),
                    json=payload,
                )
            )
        request_id = str(data.get("request_id") or "")
        if not request_id or not all(c.isalnum() or c in "-_" for c in request_id):
            raise ToolFailure("لم تُرجع Bria معرّف طلب صالحًا.")
        return request_id

    def status(self, request_id: str) -> dict:
        if not request_id or not all(c.isalnum() or c in "-_" for c in request_id):
            raise ToolFailure("معرّف طلب Bria غير صالح.")
        with self._client() as client:
            return self._check(
                client.get(
                    f"{BRIA_ORIGIN}/v2/status/{request_id}", headers=self._headers()
                )
            )

    def wait(
        self, request_id: str, timeout: float = BRIA_TIMEOUT_SECONDS
    ) -> Optional[str]:
        """Poll until done. Returns the result URL, or None if still running."""
        deadline = self._clock() + timeout
        while True:
            data = self.status(request_id)
            state = str(data.get("status", "")).upper()
            if state == "COMPLETED":
                result = data.get("result") or {}
                url = result.get("image_url") or data.get("image_url")
                if not isinstance(url, str) or not url.startswith("https://"):
                    raise ToolFailure("اكتملت معالجة Bria دون رابط صورة صالح.")
                return url
            if state in {"ERROR", "FAILED", "UNKNOWN"}:
                raise ToolFailure(
                    "فشلت معالجة Bria أو انتهت صلاحيتها؛ راجع الصورة الأصلية."
                )
            if self._clock() >= deadline:
                return None
            self._sleep(BRIA_POLL_SECONDS)

    def download(self, url: str) -> bytes:
        with self._client() as client:
            response = client.get(url)
        if response.is_error:
            raise ToolFailure(f"تعذّر تنزيل نتيجة Bria (HTTP {response.status_code}).")
        data = response.content
        if len(data) > _MAX_IMAGE_BYTES or not (
            data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")
        ):
            raise ToolFailure("نتيجة Bria ليست صورة PNG/JPEG صالحة.")
        return data


@ToolRegistry.register("bria_prepare_product")
class BriaPrepareProductTool(_CampaignTool):
    tool_id = "bria_prepare_product"
    is_local = False

    def __init__(
        self, manager: Any = None, agent_id: Optional[str] = None, client=None
    ):
        super().__init__(manager, agent_id)
        self.client = client or BriaClient()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "جهّز صورة منتج حقيقية بـ Bria (خدمة مدفوعة، فقط إذا سمح بها الطلب): "
                "erase_hand لإزالة اليد/الكم، أو remove_background. تنتظر الأداة "
                "اكتمال المعالجة حتى دقيقتين وتحفظ النتيجة في drafts/ مع الأصل دون "
                "تعديل. إن لم تكتمل أعادت request_id؛ استخدم operation=status لاحقًا. "
                "أي جزء مخفي أعادت Bria بناءه يحتاج مراجعة ولا يُعتبر مطابقًا للأصل."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["erase_hand", "remove_background", "status"],
                    },
                    "image": {
                        "type": "string",
                        "description": "مسار نسبي، مثل originals/box.jpg",
                    },
                    "request_id": {"type": "string"},
                },
                "required": ["operation"],
            },
            category="media",
            required_capabilities=["network:fetch"],
            metadata={"credentials_configured": bool(self.client.token)},
        )

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.marketing.render import sha256

        try:
            store, campaign = self._campaign()
            if not (campaign.get("options") or {}).get("allow_bria"):
                raise ToolFailure(
                    "معالجة Bria المدفوعة غير مسموحة في هذا الطلب؛ اطلب إذن المستخدم."
                )
            operation = params.get("operation")
            drafts = store.campaign_dir(campaign["team_id"], campaign["id"]) / "drafts"
            if operation == "status":
                request_id = str(params.get("request_id") or "")
                pending = drafts / f"bria-pending-{request_id}.json"
                if not pending.is_file():
                    raise ToolFailure("لا يوجد طلب Bria معلّق بهذا المعرّف في هذا الطلب.")
                info = json.loads(pending.read_text(encoding="utf-8"))
                source = store.resolve_campaign_file(campaign, info["source"])
                operation = info["operation"]
            elif operation in {"erase_hand", "remove_background"}:
                source = store.resolve_campaign_file(campaign, params.get("image", ""))
                if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    raise ToolFailure("استخدم صورة PNG أو JPEG أو WebP.")
                if source.stat().st_size > _MAX_IMAGE_BYTES:
                    raise ToolFailure("الصورة أكبر من 20 ميجابايت.")
                request_id = self.client.submit(
                    operation, base64.b64encode(source.read_bytes()).decode()
                )
            else:
                raise ToolFailure("اختر erase_hand أو remove_background أو status.")
            root = store.campaign_dir(campaign["team_id"], campaign["id"]).resolve()
            source_rel = str(source.resolve().relative_to(root))
            url = self.client.wait(request_id)
            if url is None:
                (drafts / f"bria-pending-{request_id}.json").write_text(
                    json.dumps({"source": source_rel, "operation": operation}),
                    encoding="utf-8",
                )
                return self._result(
                    True,
                    {
                        "status": "pending",
                        "request_id": request_id,
                        "message": "المعالجة ما زالت جارية؛ لم تكتمل الصورة بعد.",
                    },
                )
            data = self.client.download(url)
            ext = ".png" if data.startswith(b"\x89PNG") else ".jpg"
            out = drafts / f"bria-{operation}-{uuid.uuid4().hex[:8]}{ext}"
            out.write_bytes(data)
            meta = {
                "source": source_rel,
                "source_sha256": sha256(source),
                "operation": operation,
                "bria_request_id": request_id,
                # Removing a hand rebuilds hidden edges: never "matches original".
                "reconstructed": operation == "erase_hand",
                "verified": False,
            }
            out.with_name(out.name + ".json").write_text(
                json.dumps(meta, ensure_ascii=False), encoding="utf-8"
            )
            (drafts / f"bria-pending-{request_id}.json").unlink(missing_ok=True)
            return self._result(
                True,
                {
                    "status": "completed",
                    "image": str(out.relative_to(root)),
                    "original": source_rel,
                    "needs_review": operation == "erase_hand",
                    "message": (
                        "أعادت Bria بناء أجزاء كانت مخفية خلف اليد؛ تحتاج مقارنة "
                        "بالأصل أو بصورة أصلية أخرى ولا تُعتبر مطابقة تلقائيًا."
                        if operation == "erase_hand"
                        else "أُزيلت الخلفية؛ راجع حواف العبوة."
                    ),
                },
            )
        except ToolFailure as exc:
            return self._result(False, str(exc))
        except httpx.HTTPError:
            return self._result(
                False, "تعذّر الوصول إلى Bria خلال المهلة؛ أعد المحاولة لاحقًا."
            )
        except (OSError, ValueError) as exc:
            return self._result(False, f"تعذّر تنفيذ طلب Bria: {exc}")


# ── Creative ─────────────────────────────────────────────────────────


@ToolRegistry.register("marketing_creative")
class MarketingCreativeTool(_CampaignTool):
    tool_id = "marketing_creative"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "ركّب إعلانًا ثابتًا 1080×1080 من صورة منتج حقيقية والعنوان، مع الشعار "
                "وبيانات التواصل المعتمدة للطلب تلقائيًا، وصدّره PNG جاهزًا للنشر. "
                "عربي من اليمين لليسار. لا يولّد صورًا ولا يعيد كتابة نصوص العبوة. "
                "يفشل بوضوح إذا لم يتسع النص بدل قصّه."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "product_image": {
                        "type": "string",
                        "description": "مسار نسبي: originals/box.jpg أو drafts/...png",
                    },
                    "headline": {"type": "string", "description": "حتى 85 حرفًا"},
                    "language": {"type": "string", "enum": ["ar", "en"]},
                },
                "required": ["product_image", "headline"],
            },
            category="media",
        )

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.marketing.render import (
            RenderError,
            build_html,
            render_png,
            sha256,
            sidecar,
        )

        try:
            store, campaign = self._campaign()
            options = campaign.get("options") or {}
            if not options.get("logo") or not options.get("contact"):
                raise ToolFailure(
                    "لا يوجد شعار أو بيانات تواصل معتمدة لهذا الطلب؛ "
                    "اطلبها من المستخدم."
                )
            root = store.campaign_dir(campaign["team_id"], campaign["id"]).resolve()
            product = store.resolve_campaign_file(
                campaign, params.get("product_image", "")
            )
            logo = store.resolve_campaign_file(campaign, options["logo"])
            name = uuid.uuid4().hex[:10]
            html_path = root / "drafts" / f"creative-{name}.html"
            html_path.write_text(
                build_html(
                    product=product,
                    logo=logo,
                    headline=str(params.get("headline", "")),
                    contact=options["contact"],
                    language=params.get("language") or "ar",
                    accent=options.get("accent") or "#153d30",
                ),
                encoding="utf-8",
            )
            png = root / "final" / f"creative-{name}.png"
            fit = render_png(html_path, png)
            product_meta = sidecar(product) or {}
            meta = {
                "png_sha256": sha256(png),
                "html": str(html_path.relative_to(root)),
                "product": str(product.relative_to(root)),
                "product_sha256": sha256(product),
                "logo": options["logo"],
                "logo_sha256": sha256(logo),
                "headline": str(params.get("headline", "")).strip(),
                "contact": options["contact"],
                "fit": fit,
                "needs_reconstruction_review": bool(product_meta.get("reconstructed")),
                "renderer": "headless-chrome",
            }
            png.with_name(png.name + ".json").write_text(
                json.dumps(meta, ensure_ascii=False), encoding="utf-8"
            )
            return self._result(
                True,
                {
                    "final_png": str(png.relative_to(root)),
                    "draft_html": meta["html"],
                    "status": "needs_review",
                    "needs_reconstruction_review": meta["needs_reconstruction_review"],
                },
            )
        except (ToolFailure, RenderError) as exc:
            return self._result(False, str(exc))
        except (OSError, ValueError) as exc:
            return self._result(False, f"تعذّر تركيب التصميم: {exc}")


# ── Approval submission ──────────────────────────────────────────────


@ToolRegistry.register("marketing_submit_review")
class MarketingSubmitReviewTool(_CampaignTool):
    tool_id = "marketing_submit_review"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "أرسل الصورة النهائية (final/*.png) ونص المنشور والموعد بتوقيت القاهرة "
                "ونتيجة مراجعة الجودة إلى المستخدم للموافقة. لا تُجدول أو تنشر شيئًا: "
                "الجدولة في Buffer تتم فقط بعد موافقة المستخدم الصريحة على هذه النسخة "
                "بالتحديد. أي تغيير بعد الإرسال يحتاج موافقة جديدة."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "final_png": {"type": "string"},
                    "caption": {"type": "string"},
                    "scheduled_at": {
                        "type": "string",
                        "description": "YYYY-MM-DD HH:MM بتوقيت القاهرة",
                    },
                    "quality_review": {"type": "string"},
                },
                "required": ["final_png", "caption", "scheduled_at", "quality_review"],
            },
            category="proactive",
        )

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.marketing.publisher import PublishError, submit_for_approval
        from openjarvis.marketing.render import RenderError

        try:
            _, campaign = self._campaign()
            result = submit_for_approval(
                self._manager,
                agent_id=self._agent_id,
                campaign=campaign,
                final_png=str(params.get("final_png", "")),
                caption=str(params.get("caption", "")),
                scheduled_at=str(params.get("scheduled_at", "")),
                quality_review=str(params.get("quality_review", "")),
            )
            result["message"] = (
                "أُرسلت المسودة للمستخدم للموافقة. لم تُجدول بعد في Buffer."
            )
            return self._result(True, result)
        except (ToolFailure, PublishError, RenderError) as exc:
            return self._result(False, str(exc))
        except (OSError, ValueError) as exc:
            return self._result(False, f"تعذّر إرسال المسودة للموافقة: {exc}")


__all__ = [
    "BriaClient",
    "BriaPrepareProductTool",
    "MarketingCreativeTool",
    "MarketingSubmitReviewTool",
]
