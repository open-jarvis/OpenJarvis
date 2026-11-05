"""Approved Buffer scheduling: exact version, company account, no duplicates.

All Buffer and R2 traffic goes to an in-process ``httpx.MockTransport``; no
real service is called and no post is published.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import struct
import zlib
from zoneinfo import ZoneInfo

import httpx
import pytest

from openjarvis.agents.manager import AgentManager
from openjarvis.marketing import publisher
from openjarvis.tools.approval_store import ApprovalStore

CAIRO = ZoneInfo("Africa/Cairo")


def _png(width=1080, height=1080) -> bytes:
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))

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


class FakeServices:
    """Buffer GraphQL + R2 S3 endpoints with configurable failures."""

    def __init__(self):
        self.creates = 0
        self.uploads = []
        self.posts = []
        self.fail_next_create_with_timeout = False
        self.tokens = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host.endswith("r2.cloudflarestorage.com"):
            assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256")
            if request.method == "HEAD":
                return httpx.Response(200)
            self.uploads.append((request.url.path, request.content))
            return httpx.Response(200)
        assert request.url.host == "api.buffer.com"
        self.tokens.add(request.headers["authorization"])
        body = json.loads(request.content)
        query = body["query"]
        if "createPost" in query:
            self.creates += 1
            data = body["variables"]["input"]
            post = {
                "id": f"post-{self.creates}",
                "text": data["text"],
                "dueAt": data["dueAt"],
                "status": "scheduled",
                "channelId": data["channelId"],
            }
            self.posts.append(post)
            if self.fail_next_create_with_timeout:
                self.fail_next_create_with_timeout = False
                raise httpx.ReadTimeout("lost reply", request=request)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "createPost": {"__typename": "PostActionSuccess", "post": post}
                    }
                },
            )
        if "posts(" in query:
            return httpx.Response(
                200,
                json={"data": {"posts": {"edges": [{"node": p} for p in self.posts]}}},
            )
        if "post(" in query:
            return httpx.Response(200, json={"data": {"post": self.posts[-1]}})
        return httpx.Response(400)


@pytest.fixture
def env(tmp_path, monkeypatch):
    import openjarvis.tools.proactive_tools as proactive

    store = ApprovalStore(str(tmp_path / "approvals.db"))
    monkeypatch.setattr(proactive, "_store", store)
    manager = AgentManager(str(tmp_path / "agents.db"))
    team = manager.create_team("سوفت باك")
    lead = manager.create_agent("المنسّق", team_id=team["id"])
    release = manager.create_agent("النشر", team_id=team["id"])
    manager.campaigns.set_team_lead(team["id"], lead["id"])
    campaign = manager.campaigns.create_campaign(team["id"], title="نوفمبر", brief="b")
    root = manager.campaigns.campaign_dir(team["id"], campaign["id"])
    final = root / "final" / "creative-1.png"
    final.write_bytes(_png())
    digest = hashlib.sha256(final.read_bytes()).hexdigest()
    final.with_name(final.name + ".json").write_text(
        json.dumps({"png_sha256": digest, "needs_reconstruction_review": True})
    )
    yield manager, store, team, release, campaign, root
    manager.close()


def _connect(manager, team, services):
    buffer = manager.create_team_connection(
        team["id"],
        name="Buffer سوفت باك",
        provider="Buffer",
        url="",
        token="buffer-company-key",
        kind="buffer",
        settings={"organization_id": "org1"},
    )
    r2 = manager.create_team_connection(
        team["id"],
        name="R2",
        provider="Cloudflare R2",
        url="",
        token="r2-secret",
        kind="r2",
        settings={
            "account_id": "a" * 32,
            "bucket": "softpack-media",
            "access_key_id": "AKIAEXAMPLE000001",
            "public_base_url": "https://media.softpack.example",
        },
    )
    for conn in (buffer, r2):
        manager.update_team_connection_settings(team["id"], conn["id"], verified_at=1.0)
    manager.update_team_connection_settings(
        team["id"], buffer["id"], channel_id="ch1", channel_name="Facebook سوفت باك"
    )
    return buffer, r2


def _submit(manager, release, campaign, when="2026-11-20 19:00"):
    return publisher.submit_for_approval(
        manager,
        agent_id=release["id"],
        campaign=manager.campaigns.get_campaign(campaign["id"]),
        final_png="final/creative-1.png",
        caption="عبوات سوفت باك",
        scheduled_at=when,
        quality_review="PASS",
    )


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    class Frozen(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            value = dt.datetime(2026, 11, 5, 12, 0, tzinfo=dt.UTC)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(publisher.dt, "datetime", Frozen)


def test_cairo_time_and_approval_bound_to_exact_version(env):
    manager, store, team, release, campaign, root = env
    result = _submit(manager, release, campaign)
    pub = publisher.list_publications(manager, campaign["id"])[0]
    # 19:00 Cairo (UTC+2 in November) is 17:00 UTC.
    assert pub["due_at_utc"] == "2026-11-20T17:00:00.000Z"
    assert result["needs_reconstruction_review"] is True
    action = store.get_action(result["action_id"])
    assert action.tier == "high" and "القاهرة" in action.description
    approved = root / pub["image_path"]
    assert approved.is_file() and approved.parent.name == "approved"
    # The same draft resubmitted does not create a second approval.
    assert _submit(manager, release, campaign)["action_id"] == result["action_id"]


def test_saved_but_unverified_connections_block_approval(env):
    manager, store, team, release, campaign, _ = env
    result = _submit(manager, release, campaign)
    with pytest.raises(publisher.PublishError, match="Buffer"):
        publisher.approve(manager, result["action_id"])
    manager.create_team_connection(
        team["id"],
        name="Buffer",
        provider="Buffer",
        url="",
        token="k",
        kind="buffer",
        settings={},
    )
    with pytest.raises(publisher.PublishError, match="لم يُتحقق"):
        publisher.approve(manager, result["action_id"])
    assert store.get_action(result["action_id"]).status == "pending"


def test_changed_image_requires_new_approval(env):
    manager, store, team, release, campaign, root = env
    _connect(manager, team, FakeServices())
    result = _submit(manager, release, campaign)
    pub = publisher.list_publications(manager, campaign["id"])[0]
    (root / pub["image_path"]).write_bytes(_png(1080, 1080)[:-12] + b"tampered1234")
    with pytest.raises(publisher.PublishError, match="تغيّرت"):
        publisher.approve(manager, result["action_id"])


def test_approve_uploads_only_approved_png_and_schedules_once(env):
    manager, store, team, release, campaign, root = env
    services = FakeServices()
    _connect(manager, team, services)
    result = _submit(manager, release, campaign)
    publisher.approve(manager, result["action_id"])
    transport = httpx.MockTransport(services)
    for _ in range(4):
        publisher.process_due(manager, transport=transport)
    pub = publisher.list_publications(manager, campaign["id"])[0]
    assert pub["state"] == "scheduled" and pub["buffer_post_id"] == "post-1"
    assert services.creates == 1
    ((path, body),) = services.uploads
    assert (
        path.startswith("/softpack-media/approved/")
        and body == (root / pub["image_path"]).read_bytes()
    )
    # The object key reveals no company folder, campaign or file name.
    assert campaign["id"] not in path and "creative" not in path
    assert pub["image_url"].startswith("https://media.softpack.example/approved/")
    assert services.tokens == {"Bearer buffer-company-key"}
    assert store.get_action(result["action_id"]).status == "executed"
    assert manager.campaigns.get_campaign(campaign["id"])["status"] == "scheduled"


def test_uncertain_create_is_reconciled_not_repeated(env):
    manager, store, team, release, campaign, _ = env
    services = FakeServices()
    services.fail_next_create_with_timeout = True
    _connect(manager, team, services)
    result = _submit(manager, release, campaign)
    publisher.approve(manager, result["action_id"])
    transport = httpx.MockTransport(services)
    publisher.process_due(manager, transport=transport)  # upload
    publisher.process_due(manager, transport=transport)  # create → timeout
    pub = publisher.list_publications(manager, campaign["id"])[0]
    assert pub["state"] == "uncertain"
    publisher.process_due(manager, transport=transport)  # look up, do not create
    pub = publisher.list_publications(manager, campaign["id"])[0]
    assert pub["state"] == "scheduled" and services.creates == 1


def test_restart_during_create_reconciles_first(env):
    manager, store, team, release, campaign, _ = env
    services = FakeServices()
    _connect(manager, team, services)
    result = _submit(manager, release, campaign)
    publisher.approve(manager, result["action_id"])
    publisher._set(manager, result["action_id"], state="creating", create_attempts=1)
    publisher.recover_interrupted(manager)
    assert (
        publisher.list_publications(manager, campaign["id"])[0]["state"] == "uncertain"
    )


def test_deny_requests_changes(env):
    manager, store, team, release, campaign, _ = env
    result = _submit(manager, release, campaign)
    publisher.deny(manager, result["action_id"])
    assert publisher.list_publications(manager, campaign["id"])[0]["state"] == "denied"
    status = manager.campaigns.get_campaign(campaign["id"])["status"]
    assert status == "changes_requested"


def test_submission_rejects_unrendered_or_wrong_size_images(env):
    manager, store, team, release, campaign, root = env
    (root / "final" / "manual.png").write_bytes(_png())
    with pytest.raises(publisher.PublishError, match="marketing_creative"):
        publisher.submit_for_approval(
            manager,
            agent_id=release["id"],
            campaign=campaign,
            final_png="final/manual.png",
            caption="x",
            scheduled_at="2026-11-20 19:00",
            quality_review="PASS",
        )
    with pytest.raises(publisher.PublishError, match="10 دقائق"):
        _submit(manager, release, campaign, when="2026-11-05 14:05")


def test_publisher_connections_are_never_agent_tools(env):
    manager, store, team, release, campaign, _ = env
    _connect(manager, team, FakeServices())
    from openjarvis.agents.team_tools import discover_team_connections

    tools, clients = discover_team_connections(manager, release["id"])
    assert tools == [] and clients == []
    listed = json.dumps(manager.list_team_connections(team["id"]), ensure_ascii=False)
    assert "r2-secret" not in listed and "buffer-company-key" not in listed
