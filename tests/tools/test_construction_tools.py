"""Tests for construction agent tools (in-memory store, temp doc dir)."""

from __future__ import annotations

from pathlib import Path

import pytest

import openjarvis.tools.construction_tools as ct
from openjarvis.construction.store import ConstructionStore
from openjarvis.tools.construction_tools import (
    ContractCreateTool,
    CostAddTool,
    CostLookupTool,
    ProjectCreateTool,
    ProjectListTool,
    ProjectUpdateStatusTool,
    QuoteCreateTool,
)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ConstructionStore(":memory:")
    monkeypatch.setattr(ct, "_STORE", store)
    monkeypatch.setattr(ct, "_DOC_DIR", tmp_path / "docs")
    yield store
    store.close()


def test_cost_add_and_lookup(env):
    add = CostAddTool().execute(
        name="2x4 Lumber", unit_cost=4.5, unit="each", category="material"
    )
    assert add.success is True
    look = CostLookupTool().execute(query="lumber")
    assert look.success is True
    assert "2x4 lumber" in look.content.lower()


def test_project_create_list_update(env):
    created = ProjectCreateTool().execute(name="Deck Build", client="Smith")
    assert created.success is True
    pid = created.metadata["project_id"]

    listed = ProjectListTool().execute()
    assert "Deck Build" in listed.content

    updated = ProjectUpdateStatusTool().execute(project=pid, status="active")
    assert updated.success is True
    assert env.get_project(pid).status == "active"


def test_project_update_invalid_status(env):
    ProjectCreateTool().execute(name="Patio")
    result = ProjectUpdateStatusTool().execute(project="Patio", status="bogus")
    assert result.success is False


def test_quote_create_writes_file(env, tmp_path):
    result = QuoteCreateTool().execute(
        title="Garage Slab",
        client="Acme",
        items=[
            {"description": "Concrete", "quantity": 10, "unit": "yd", "unit_cost": 150},
            {"description": "Labor", "quantity": 16, "unit": "hour", "unit_cost": 65},
        ],
        tax_rate=8.0,
    )
    assert result.success is True
    html_path = Path(result.metadata["html_path"])
    assert html_path.exists()
    # subtotal = 1500 + 1040 = 2540; tax 8% = 203.2; total = 2743.2
    assert result.metadata["total"] == pytest.approx(2743.2)
    # document recorded in the store
    assert len(env.list_documents()) == 1


def test_quote_create_uses_catalog(env):
    env.add_cost_item("framing", 65.0, category="labor", unit="hour")
    result = QuoteCreateTool().execute(
        title="Framing Job",
        items=[{"catalog_item": "framing", "quantity": 8}],
    )
    assert result.success is True
    # 8 * 65 = 520, no tax
    assert result.metadata["total"] == pytest.approx(520.0)


def test_quote_create_requires_items(env):
    result = QuoteCreateTool().execute(title="Empty", items=[])
    assert result.success is False


def test_quote_links_to_project(env):
    proj = ProjectCreateTool().execute(name="Reno", client="X")
    pid = proj.metadata["project_id"]
    QuoteCreateTool().execute(
        title="Reno Quote",
        items=[{"description": "Work", "quantity": 1, "unit_cost": 100}],
        project="Reno",
    )
    docs = env.list_documents(pid)
    assert len(docs) == 1
    assert docs[0].title == "Reno Quote"


def test_contract_create_writes_file(env):
    result = ContractCreateTool().execute(
        title="Build Agreement",
        client="Smith",
        contractor="BuildCo",
        scope="Full remodel",
        amount=25000,
        payment_terms="50/50",
    )
    assert result.success is True
    assert Path(result.metadata["html_path"]).exists()
    assert result.metadata["amount"] == pytest.approx(25000.0)
