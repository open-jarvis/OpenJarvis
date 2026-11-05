"""Marketing tools are bound to the running team request; no paid calls."""

import json
import struct
import zlib

import httpx
import pytest

from openjarvis.agents.manager import AgentManager
from openjarvis.tools.marketing import (
    BriaClient,
    BriaPrepareProductTool,
    MarketingCreativeTool,
    MarketingSubmitReviewTool,
)


def _png(width, height, rgb=(200, 150, 90)) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind, data):
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def running(tmp_path):
    """A team request whose production agent is running right now."""
    manager = AgentManager(str(tmp_path / "agents.db"))
    team = manager.create_team("سوفت باك")
    lead = manager.create_agent("المنسّق", team_id=team["id"])
    designer = manager.create_agent("المصمم", team_id=team["id"])
    manager.campaigns.set_team_lead(team["id"], lead["id"])

    def start(**options):
        campaign = manager.campaigns.create_campaign(
            team["id"], title="نوفمبر", brief="b", options=options
        )
        root = manager.campaigns.campaign_dir(team["id"], campaign["id"])
        (root / "originals" / "box.png").write_bytes(_png(400, 600))
        (root / "originals" / "logo.png").write_bytes(_png(300, 100, (20, 60, 50)))
        manager.campaigns.add_request(campaign["id"], content="b", files=[])
        request = manager.campaigns.list_handoffs(campaign["id"])[0]
        manager.campaigns.claim_batch(request)
        manager.campaigns.update_handoff(request["id"], status="completed")
        # Simulate the lead's task to the designer being executed.
        lead_batch = request | {"status": "running", "depth": 0}
        with manager._db_lock:
            manager._conn.execute(
                "UPDATE agent_handoffs SET status='running' WHERE id=?",
                (request["id"],),
            )
            manager._conn.commit()
        manager.campaigns.assign_tasks(
            lead["id"],
            [{"target_agent_id": designer["id"], "title": "صمّم", "instructions": "x"}],
        )
        task = manager.campaigns.list_handoffs(campaign["id"])[-1]
        manager.campaigns.update_handoff(lead_batch["id"], status="completed")
        manager.campaigns.claim_batch(task)
        return manager.campaigns.get_campaign(campaign["id"]), root

    yield manager, designer, start
    manager.close()


def test_tools_refuse_without_a_running_request(tmp_path):
    for tool in (MarketingCreativeTool(), MarketingSubmitReviewTool()):
        result = tool.execute(product_image="x", headline="y")
        assert not result.success and "الفرق" in result.content


def test_bria_requires_permission_for_paid_processing(running):
    manager, designer, start = running
    start(allow_bria=False, logo="originals/logo.png", contact="0100")
    tool = BriaPrepareProductTool(manager, designer["id"], client=BriaClient("t"))
    result = tool.execute(operation="erase_hand", image="originals/box.png")
    assert not result.success and "غير مسموحة" in result.content


def _bria_transport(states, result_bytes, seen):
    def handler(request):
        seen.append(request.url.path)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["sync"] is False and body["image"]
            assert request.headers["api_token"] == "secret"
            return httpx.Response(200, json={"request_id": "req-1"})
        if request.url.path.startswith("/v2/status/"):
            state = states.pop(0)
            payload = {"status": state}
            if state == "COMPLETED":
                payload["result"] = {"image_url": "https://cdn.bria.example/out.png"}
            return httpx.Response(200, json=payload)
        return httpx.Response(200, content=result_bytes)

    return httpx.MockTransport(handler)


def test_bria_polls_to_completion_and_flags_reconstruction(running):
    manager, designer, start = running
    campaign, root = start(allow_bria=True, logo="originals/logo.png", contact="0100")
    seen = []
    client = BriaClient(
        "secret",
        _bria_transport(["IN_PROGRESS", "COMPLETED"], _png(400, 600), seen),
        sleep=lambda s: None,
    )
    result = BriaPrepareProductTool(manager, designer["id"], client=client).execute(
        operation="erase_hand", image="originals/box.png"
    )
    data = json.loads(result.content)
    assert result.success and data["status"] == "completed" and data["needs_review"]
    out = root / data["image"]
    meta = json.loads(out.with_name(out.name + ".json").read_text())
    assert meta["reconstructed"] is True and meta["verified"] is False
    # The original stays unchanged.
    assert (root / "originals" / "box.png").read_bytes() == _png(400, 600)
    assert "secret" not in result.content


def test_bria_timeout_reports_pending_then_status_finishes(running):
    manager, designer, start = running
    campaign, root = start(allow_bria=True, logo="originals/logo.png", contact="0100")
    clock = iter(range(0, 10_000, 100))
    states = ["IN_PROGRESS"] * 3 + ["COMPLETED"]
    client = BriaClient(
        "secret",
        _bria_transport(states, _png(400, 600), []),
        sleep=lambda s: None,
        clock=lambda: next(clock),
    )
    tool = BriaPrepareProductTool(manager, designer["id"], client=client)
    first = json.loads(
        tool.execute(operation="erase_hand", image="originals/box.png").content
    )
    assert first["status"] == "pending" and first["request_id"] == "req-1"
    second = json.loads(tool.execute(operation="status", request_id="req-1").content)
    assert second["status"] == "completed"


@pytest.mark.parametrize("status", [401, 429, 500])
def test_bria_errors_are_arabic_and_redacted(running, status):
    manager, designer, start = running
    start(allow_bria=True, logo="originals/logo.png", contact="0100")
    transport = httpx.MockTransport(
        lambda r: httpx.Response(status, text="secret-body")
    )
    result = BriaPrepareProductTool(
        manager, designer["id"], client=BriaClient("secret", transport)
    ).execute(operation="remove_background", image="originals/box.png")
    assert not result.success and "secret" not in result.content
    assert "Bria" in result.content


def test_files_outside_the_request_are_rejected(running):
    manager, designer, start = running
    start(allow_bria=True, logo="originals/logo.png", contact="0100")
    result = MarketingCreativeTool(manager, designer["id"]).execute(
        product_image="../../../agents.db", headline="عنوان"
    )
    assert not result.success and "داخل ملفات" in result.content


def test_creative_needs_approved_logo_and_contact(running):
    manager, designer, start = running
    start(allow_bria=False)
    result = MarketingCreativeTool(manager, designer["id"]).execute(
        product_image="originals/box.png", headline="عنوان"
    )
    assert not result.success and "شعار" in result.content


def test_creative_exports_png_with_metadata(running):
    from openjarvis.marketing.render import RenderError, find_chrome, png_size

    try:
        find_chrome()
    except RenderError:
        pytest.skip("Chrome/Chromium not installed")
    manager, designer, start = running
    campaign, root = start(
        allow_bria=False, logo="originals/logo.png", contact="0100 000 0000 · سوفت باك"
    )
    result = MarketingCreativeTool(manager, designer["id"]).execute(
        product_image="originals/box.png", headline="عبوات تحمي منتجك"
    )
    assert result.success, result.content
    data = json.loads(result.content)
    png = root / data["final_png"]
    assert png_size(png) == (1080, 1080)
    meta = json.loads(png.with_name(png.name + ".json").read_text())
    assert meta["contact"] == "0100 000 0000 · سوفت باك" and meta["fit"]["ok"]
    html = (root / data["draft_html"]).read_text()
    assert 'dir="rtl"' in html and "عبوات تحمي منتجك" in html


def test_softpack_templates_are_arabic_and_limit_tools():
    from openjarvis.agents.manager import AgentManager as Manager

    templates = {t["id"]: t for t in Manager.list_templates()}
    for template_id in (
        "softpack_orchestrator",
        "softpack_planning",
        "softpack_production",
        "softpack_quality",
        "softpack_release",
    ):
        template = templates[template_id]
        assert "منسّق" in template["system_prompt_template"]
    assert "marketing_submit_review" in templates["softpack_release"]["tools"]
    assert "bria_prepare_product" not in templates["softpack_planning"]["tools"]
