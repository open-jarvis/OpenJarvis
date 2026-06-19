"""Tests for construction document rendering and money math."""

from __future__ import annotations

from openjarvis.construction import documents as docs


def test_normalize_line_items_with_direct_cost():
    items = docs.normalize_line_items(
        [
            {"description": "Drywall", "quantity": 20, "unit": "sheet", "unit_cost": 12.5},
            {"description": "", "quantity": 1},  # dropped (no description)
        ]
    )
    assert len(items) == 1
    assert items[0].total == 250.0


def test_normalize_line_items_with_catalog_lookup():
    class _Item:
        unit_cost = 65.0
        unit = "hour"

    def lookup(name):
        return _Item() if name == "framing" else None

    items = docs.normalize_line_items(
        [{"catalog_item": "framing", "quantity": 8}], cost_lookup=lookup
    )
    assert len(items) == 1
    assert items[0].unit_cost == 65.0
    assert items[0].total == 520.0


def test_compute_quote_totals():
    items = [docs.LineItem("A", 10, "each", 100.0)]  # subtotal 1000
    totals = docs.compute_quote_totals(items, tax_rate=10, markup_rate=20)
    assert totals["subtotal"] == 1000.0
    assert totals["markup"] == 200.0  # 20% of 1000
    assert totals["tax"] == 120.0  # 10% of (1000 + 200)
    assert totals["total"] == 1320.0


def test_render_quote_html_contains_key_fields():
    items = [docs.LineItem("Concrete pour", 5, "yd", 150.0)]
    totals = docs.compute_quote_totals(items, tax_rate=8)
    html = docs.render_quote_html(
        title="Driveway", client="Acme Co", items=items, totals=totals, tax_rate=8
    )
    assert "<!DOCTYPE html>" in html
    assert "Driveway" in html
    assert "Acme Co" in html
    assert "Concrete pour" in html
    assert "$750.00" in html  # line total


def test_render_quote_html_escapes_input():
    items = [docs.LineItem("<script>x</script>", 1, "each", 1.0)]
    totals = docs.compute_quote_totals(items)
    html = docs.render_quote_html(
        title="T", client="C", items=items, totals=totals
    )
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_contract_html():
    html = docs.render_contract_html(
        title="Remodel Agreement",
        client="Smith",
        contractor="BuildCo",
        scope="Full kitchen remodel.",
        amount=25000.0,
        start_date="2026-07-01",
        end_date="2026-08-15",
        payment_terms="50% upfront, 50% on completion.",
    )
    assert "Construction Contract" in html
    assert "BuildCo" in html
    assert "$25,000.00" in html
    assert "2026-07-01" in html


def test_render_and_save_writes_html(tmp_path):
    items = [docs.LineItem("Item", 1, "each", 10.0)]
    totals = docs.compute_quote_totals(items)
    html = docs.render_quote_html(title="Q", client="C", items=items, totals=totals)
    out = tmp_path / "sub" / "quote.html"
    html_path, pdf_path = docs.render_and_save(html, out)
    assert html_path.exists()
    assert html_path.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    # reportlab not installed in CI → no PDF, which is acceptable.
    assert pdf_path is None or pdf_path.suffix == ".pdf"
