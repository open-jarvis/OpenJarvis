"""Marketing production tools bound to the team request an agent is running.

Credentials never enter prompts or artifacts. Every file read or written stays
inside the current request's folder (``team-data/<team>/campaigns/<id>/``):
``originals/`` (operator uploads, never modified), ``drafts/`` (HTML layouts,
images returned by the team's MCP services) and ``final/`` (exported PNGs
the operator reviews and downloads). Image editing services are team MCP
connections, not built-in tools.
Text, logo and contact details are composed deterministically; no image model
writes package labels, headlines or numbers.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional, Tuple

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


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


__all__ = ["MarketingCreativeTool"]
