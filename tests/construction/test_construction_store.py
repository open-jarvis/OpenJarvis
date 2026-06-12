"""Tests for the construction SQLite store (in-memory)."""

from __future__ import annotations

import pytest

from openjarvis.construction.store import ConstructionStore


@pytest.fixture()
def store():
    s = ConstructionStore(":memory:")
    yield s
    s.close()


def test_cost_item_upsert_and_search(store):
    store.add_cost_item("2x4 Lumber", 4.50, category="material", unit="each")
    store.add_cost_item("Framing Labor", 65.0, category="labor", unit="hour")
    # Upsert updates rather than duplicating.
    store.add_cost_item("2x4 Lumber", 5.25, category="material", unit="each")

    all_items = store.search_cost_items()
    assert len(all_items) == 2
    lumber = store.get_cost_item("2x4 Lumber")
    assert lumber is not None
    assert lumber.unit_cost == 5.25

    labor = store.search_cost_items("labor")
    assert len(labor) == 1
    assert labor[0].name == "framing labor"


def test_cost_item_delete(store):
    store.add_cost_item("Nails", 0.10)
    assert store.delete_cost_item("Nails") == 1
    assert store.get_cost_item("Nails") is None


def test_project_lifecycle(store):
    proj = store.create_project("Kitchen Remodel", client="Smith", status="lead")
    assert proj.status == "lead"
    assert store.find_project_by_name("kitchen remodel").id == proj.id

    store.update_project_status(proj.id, "active")
    assert store.get_project(proj.id).status == "active"

    active = store.list_projects(status="active")
    assert len(active) == 1


def test_project_invalid_status_raises(store):
    proj = store.create_project("Deck")
    with pytest.raises(ValueError, match="Invalid status"):
        store.update_project_status(proj.id, "bogus")


def test_record_and_list_documents(store):
    proj = store.create_project("Bathroom")
    store.record_document(
        doc_type="quote",
        title="Bathroom Quote",
        path="/tmp/q.html",
        total=5000.0,
        project_id=proj.id,
        data={"client": "Jones"},
    )
    docs = store.list_documents(proj.id)
    assert len(docs) == 1
    assert docs[0].doc_type == "quote"
    assert docs[0].data["client"] == "Jones"
