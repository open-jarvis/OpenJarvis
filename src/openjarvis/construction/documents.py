"""Render construction quotes and contracts as print-ready HTML.

HTML is dependency-free and prints to PDF from any browser. When ``reportlab``
is available, :func:`maybe_write_pdf` also emits a real ``.pdf`` next to the
HTML. Money math is centralized in :func:`compute_quote_totals`.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class LineItem:
    description: str
    quantity: float
    unit: str
    unit_cost: float

    @property
    def total(self) -> float:
        return round(self.quantity * self.unit_cost, 2)


def normalize_line_items(
    raw_items: List[Dict[str, Any]],
    *,
    cost_lookup: Optional[Any] = None,
) -> List[LineItem]:
    """Coerce loosely-typed item dicts into :class:`LineItem` objects.

    Each item may supply ``unit_cost`` directly, or a ``catalog_item`` name
    that is resolved through *cost_lookup* (a callable name -> CostItem|None).
    """
    items: List[LineItem] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        description = str(raw.get("description") or raw.get("catalog_item") or "").strip()
        if not description:
            continue
        try:
            quantity = float(raw.get("quantity", 1) or 1)
        except (TypeError, ValueError):
            quantity = 1.0
        unit = str(raw.get("unit") or "each")
        unit_cost = raw.get("unit_cost")
        if unit_cost is None and cost_lookup is not None and raw.get("catalog_item"):
            item = cost_lookup(str(raw["catalog_item"]))
            if item is not None:
                unit_cost = item.unit_cost
                unit = unit or item.unit
        try:
            unit_cost = float(unit_cost) if unit_cost is not None else 0.0
        except (TypeError, ValueError):
            unit_cost = 0.0
        items.append(LineItem(description, quantity, unit, unit_cost))
    return items


def compute_quote_totals(
    items: List[LineItem], *, tax_rate: float = 0.0, markup_rate: float = 0.0
) -> Dict[str, float]:
    """Return subtotal, markup, tax, and grand total for a set of line items."""
    subtotal = round(sum(i.total for i in items), 2)
    markup = round(subtotal * markup_rate / 100.0, 2)
    taxable = subtotal + markup
    tax = round(taxable * tax_rate / 100.0, 2)
    total = round(taxable + tax, 2)
    return {
        "subtotal": subtotal,
        "markup": markup,
        "tax": tax,
        "total": total,
    }


_BASE_CSS = """
  body { font-family: 'Segoe UI', Arial, sans-serif; color: #1a1a1a; margin: 40px; }
  h1 { font-size: 26px; margin-bottom: 0; }
  .muted { color: #666; }
  .meta { margin: 16px 0 24px; }
  table { width: 100%; border-collapse: collapse; margin-top: 16px; }
  th, td { padding: 8px 10px; border-bottom: 1px solid #e2e2e2; text-align: left; }
  th { background: #f5f5f7; font-size: 13px; text-transform: uppercase; letter-spacing: .03em; }
  td.num, th.num { text-align: right; }
  .totals { margin-top: 16px; width: 320px; margin-left: auto; }
  .totals td { border: none; padding: 4px 10px; }
  .totals .grand { font-weight: 700; font-size: 18px; border-top: 2px solid #1a1a1a; }
  .terms { margin-top: 32px; font-size: 13px; color: #333; }
  .sign { margin-top: 48px; display: flex; gap: 60px; }
  .sign div { border-top: 1px solid #1a1a1a; padding-top: 6px; width: 240px; font-size: 13px; }
  footer { margin-top: 40px; font-size: 11px; color: #999; }
"""


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _money(value: float) -> str:
    return f"${value:,.2f}"


def render_quote_html(
    *,
    title: str,
    client: str,
    items: List[LineItem],
    totals: Dict[str, float],
    company: str = "OpenJarvis Construction",
    notes: str = "",
    tax_rate: float = 0.0,
    markup_rate: float = 0.0,
    quote_date: Optional[str] = None,
) -> str:
    quote_date = quote_date or date.today().isoformat()
    rows = "\n".join(
        f"<tr><td>{_e(i.description)}</td>"
        f"<td class='num'>{i.quantity:g}</td>"
        f"<td>{_e(i.unit)}</td>"
        f"<td class='num'>{_money(i.unit_cost)}</td>"
        f"<td class='num'>{_money(i.total)}</td></tr>"
        for i in items
    )
    total_rows = [
        f"<tr><td>Subtotal</td><td class='num'>{_money(totals['subtotal'])}</td></tr>"
    ]
    if markup_rate:
        total_rows.append(
            f"<tr><td>Markup ({markup_rate:g}%)</td>"
            f"<td class='num'>{_money(totals['markup'])}</td></tr>"
        )
    if tax_rate:
        total_rows.append(
            f"<tr><td>Tax ({tax_rate:g}%)</td>"
            f"<td class='num'>{_money(totals['tax'])}</td></tr>"
        )
    total_rows.append(
        f"<tr class='grand'><td>Total</td>"
        f"<td class='num'>{_money(totals['total'])}</td></tr>"
    )
    notes_html = (
        f"<div class='terms'><strong>Notes</strong><br>{_e(notes)}</div>"
        if notes
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{_e(title)}</title>
<style>{_BASE_CSS}</style></head><body>
  <h1>{_e(company)}</h1>
  <div class="muted">Estimate / Quote</div>
  <div class="meta">
    <strong>{_e(title)}</strong><br>
    Prepared for: {_e(client)}<br>
    Date: {_e(quote_date)}
  </div>
  <table>
    <thead><tr>
      <th>Description</th><th class="num">Qty</th><th>Unit</th>
      <th class="num">Unit Cost</th><th class="num">Line Total</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <table class="totals">{''.join(total_rows)}</table>
  {notes_html}
  <footer>Generated by OpenJarvis. This estimate is valid for 30 days.</footer>
</body></html>"""


def render_contract_html(
    *,
    title: str,
    client: str,
    contractor: str,
    scope: str,
    amount: float,
    start_date: str = "",
    end_date: str = "",
    terms: Optional[List[str]] = None,
    payment_terms: str = "",
) -> str:
    terms = terms or [
        "All work shall be performed in a professional and workmanlike manner.",
        "Any changes to the scope of work require a written change order.",
        "Contractor carries liability insurance and required licenses.",
        "Either party may terminate for material breach with written notice.",
    ]
    terms_html = "\n".join(f"<li>{_e(t)}</li>" for t in terms)
    schedule = ""
    if start_date or end_date:
        schedule = (
            f"<p><strong>Schedule:</strong> {_e(start_date)} to {_e(end_date)}.</p>"
        )
    pay = (
        f"<p><strong>Payment terms:</strong> {_e(payment_terms)}</p>"
        if payment_terms
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{_e(title)}</title>
<style>{_BASE_CSS}</style></head><body>
  <h1>Construction Contract</h1>
  <div class="muted">{_e(title)}</div>
  <div class="meta">
    This agreement is entered into between <strong>{_e(contractor)}</strong>
    ("Contractor") and <strong>{_e(client)}</strong> ("Client").
  </div>
  <h3>Scope of Work</h3>
  <p>{_e(scope)}</p>
  <h3>Contract Price</h3>
  <p>The total contract price is <strong>{_money(amount)}</strong>.</p>
  {schedule}
  {pay}
  <h3>Terms &amp; Conditions</h3>
  <ol class="terms">{terms_html}</ol>
  <div class="sign">
    <div>Contractor signature &amp; date</div>
    <div>Client signature &amp; date</div>
  </div>
  <footer>Generated by OpenJarvis. Review with qualified counsel before signing.</footer>
</body></html>"""


def write_document(html_text: str, out_path: str | Path) -> Path:
    """Write the HTML document to disk, creating parent dirs. Returns the path."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")
    return path


def maybe_write_pdf(html_text: str, html_path: Path) -> Optional[Path]:
    """Emit a sibling ``.pdf`` using reportlab when available.

    Returns the PDF path on success, or ``None`` when reportlab is not
    installed or rendering fails (HTML remains the source of truth).
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError:
        return None

    try:
        import re

        text = re.sub(r"<style[\s\S]*?</style>", "", html_text)
        text = re.sub(r"<[^>]+>", "\n", text)
        text = html.unescape(text)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        pdf_path = html_path.with_suffix(".pdf")
        doc = SimpleDocTemplate(str(pdf_path), pagesize=letter)
        styles = getSampleStyleSheet()
        flow: List[Any] = []
        for ln in lines:
            flow.append(Paragraph(html.escape(ln), styles["Normal"]))
            flow.append(Spacer(1, 6))
        doc.build(flow)
        return pdf_path
    except Exception:
        return None


def render_and_save(
    html_text: str, out_path: str | Path
) -> Tuple[Path, Optional[Path]]:
    """Write HTML and (optionally) a PDF. Returns (html_path, pdf_path|None)."""
    html_path = write_document(html_text, out_path)
    pdf_path = maybe_write_pdf(html_text, html_path)
    return html_path, pdf_path


__all__ = [
    "LineItem",
    "normalize_line_items",
    "compute_quote_totals",
    "render_quote_html",
    "render_contract_html",
    "write_document",
    "maybe_write_pdf",
    "render_and_save",
]
