"""Marketing tools are bound to the running team request; no paid calls."""

import json
import struct
import zlib

import pytest

from openjarvis.agents.manager import AgentManager
from openjarvis.tools.marketing import (
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


def test_files_outside_the_request_are_rejected(running):
    manager, designer, start = running
    start(allow_paid=True, logo="originals/logo.png", contact="0100")
    result = MarketingCreativeTool(manager, designer["id"]).execute(
        product_image="../../../agents.db", headline="عنوان"
    )
    assert not result.success and "داخل ملفات" in result.content


def test_creative_needs_approved_logo_and_contact(running):
    manager, designer, start = running
    start(allow_paid=False)
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
        allow_paid=False, logo="originals/logo.png", contact="0100 000 0000 · سوفت باك"
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
    assert "campaign:" in templates["softpack_production"]["system_prompt_template"]
    # Image services are ordinary team MCP connections, so the design agent
    # must be allowed to discover them (team agents never get global MCP).
    assert templates["softpack_production"]["mcp_tools"] is True
