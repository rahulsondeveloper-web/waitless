"""Invoice / credit note PDF (PRD §9 "generate receipts, print invoices"), drawn from the immutable snapshot.

A4 or 80 mm receipt layout from the same data. Built-in PDF fonts have no ₹ sign, so amounts print as
"Rs 1,234.00" — portable on every server without shipping font files.
"""

from decimal import Decimal
from typing import Any

from fpdf import FPDF


def _amt(v: Any, currency: str = "INR") -> str:
    n = Decimal(str(v))
    sign = "-" if n < 0 else ""
    sym = "Rs " if currency == "INR" else f"{currency} "
    return f"{sign}{sym}{abs(n):,.2f}"


def _safe(text: Any) -> str:
    """Core fonts are Latin-1 only."""
    return (
        str(text or "")
        .replace("₹", "Rs ")
        .replace("—", "-")
        .replace("–", "-")
        .replace("×", "x")
        .encode("latin-1", "replace")
        .decode("latin-1")
    )


def render(
    number: str,
    issued_at: str,
    snapshot: dict[str, Any],
    *,
    receipt: bool = False,
    names: dict[str, str] | None = None,
) -> bytes:
    """`names` (order_item_id → who ordered it) prints the "with names" copy: dishes grouped per person
    with each person's total, then the usual totals. Without it the invoice never shows names."""
    r = snapshot["restaurant"]
    b = snapshot["bill"]
    cur = r.get("currency", "INR")
    credit_note = snapshot.get("kind") == "credit_note"
    width = 80 if receipt else 210
    pdf = FPDF(unit="mm", format=(width, 297) if receipt else "A4")
    margin = 5 if receipt else 15
    pdf.set_margins(margin, margin, margin)
    pdf.set_auto_page_break(True, margin)
    pdf.add_page()
    w = width - 2 * margin
    small = 7.5 if receipt else 9
    body = 8.5 if receipt else 10

    def line(text: str, size: float = body, style: str = "", align: str = "L", h: float | None = None) -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(w, h or size * 0.5, _safe(text), align=align, new_x="LMARGIN", new_y="NEXT")

    def row(left: str, right: str, style: str = "", size: float = body) -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.cell(w * 0.62, size * 0.5, _safe(left))
        pdf.cell(w * 0.38, size * 0.5, _safe(right), align="R", new_x="LMARGIN", new_y="NEXT")

    def rule() -> None:
        pdf.ln(1)
        y = pdf.get_y()
        pdf.set_draw_color(160, 160, 160)
        pdf.line(margin, y, width - margin, y)
        pdf.ln(2)

    line(r.get("legal_name") or r["name"], 13 if receipt else 16, "B", "C")
    if r.get("address"):
        line(r["address"], small, align="C")
    if r.get("gstin"):
        line(f"GSTIN {r['gstin']}", small, align="C")
    pdf.ln(2)
    line("CREDIT NOTE" if credit_note else "TAX INVOICE", body + 1, "B", "C")
    rule()
    row(f"No. {number}", issued_at[:16].replace("T", " "), "B", small)
    if credit_note and snapshot.get("original_number"):
        row(f"Against invoice {snapshot['original_number']}", "", size=small)
    tables = ", ".join(b.get("table_labels") or [])
    row(f"Table {tables}" if tables else r.get("branch", ""), f"Order ID {b['session_code']}", size=small)
    if b.get("guest_name"):
        row(f"Guest: {b['guest_name']}", "", size=small)
    rule()

    if credit_note:
        line(f"Refund: {snapshot.get('reason') or ''}", body)
        pdf.ln(2)
        row("Credit amount", _amt(abs(Decimal(snapshot["total"])), cur), "B", body + 1)
    else:

        def dish(ln: dict[str, Any]) -> None:
            row(f"{ln['quantity']} x {ln['name']}", _amt(ln["line_total"], cur), size=body)
            if not receipt:
                pdf.set_text_color(110, 110, 110)
                row(
                    f"   #{ln['order_number']} · {_amt(ln['unit_price'], cur)} each"
                    f" · GST {Decimal(ln['tax_pct']).normalize():f}%",
                    "",
                    size=small,
                )
                pdf.set_text_color(0, 0, 0)

        if names is None:
            for ln in b["lines"]:
                dish(ln)
        else:
            groups: dict[str, list[dict[str, Any]]] = {}
            for ln in b["lines"]:
                groups.setdefault(names.get(str(ln.get("order_item_id"))) or "Shared / table", []).append(ln)
            for who, lines in groups.items():
                line(who, body + 0.5, "B")
                for ln in lines:
                    dish(ln)
                # what this person ordered, with GST, after any discount on their dishes
                own = sum((Decimal(ln["taxable"]) * (1 + Decimal(ln["tax_pct"]) / 100) for ln in lines), Decimal(0))
                row(f"{who} - total incl. GST", _amt(own.quantize(Decimal("0.01")), cur), "B", small)
                pdf.ln(1.5)
            if Decimal(b["service_charge"]) > 0 or Decimal(b["booking_credit"]) > 0:
                pdf.set_text_color(110, 110, 110)
                line("Service charge, booking credit and round-off apply to the whole bill below.", small)
                pdf.set_text_color(0, 0, 0)
        rule()
        row("Food", _amt(b["subtotal"], cur))
        if Decimal(b["sla_discount"]) > 0:
            row("Serving-time discount", _amt(-Decimal(b["sla_discount"]), cur))
        if Decimal(b["manual_discount"]) > 0:
            label = "Discount" + (
                f" ({Decimal(b['manual_discount_pct']).normalize():f}%)" if b.get("manual_discount_pct") else ""
            )
            row(label, _amt(-Decimal(b["manual_discount"]), cur))
        if Decimal(b["service_charge"]) > 0:
            row(f"Service charge {Decimal(b['service_charge_pct']).normalize():f}%", _amt(b["service_charge"], cur))
        for t in b.get("taxes", []):
            rate = Decimal(t["rate"])
            if Decimal(t["tax"]) == 0:
                continue
            if r.get("tax_split") == "cgst_sgst":
                half = (rate / 2).normalize()
                row(f"CGST {half:f}% on {_amt(t['taxable'], cur)}", _amt(t["cgst"], cur), size=small)
                row(f"SGST {half:f}% on {_amt(t['taxable'], cur)}", _amt(t["sgst"], cur), size=small)
            else:
                row(f"GST {rate.normalize():f}% on {_amt(t['taxable'], cur)}", _amt(t["tax"], cur), size=small)
        if Decimal(b["sla_discount_after_tax"]) > 0:
            row("Serving-time discount", _amt(-Decimal(b["sla_discount_after_tax"]), cur))
        if Decimal(b["booking_credit"]) > 0:
            row("Booking fee paid", _amt(-Decimal(b["booking_credit"]), cur))
        if Decimal(b["round_off"]) != 0:
            row("Round off", _amt(b["round_off"], cur))
        rule()
        row("TOTAL", _amt(b["grand_total"], cur), "B", body + 2)
        pdf.ln(1)
        for p in b.get("payments", []):
            if p["status"] != "captured":
                continue
            label = {
                "cash": "Cash",
                "upi": "UPI",
                "card": "Card",
                "gateway": "Paid online",
                "other": p.get("method_label") or "Other",
            }[p["method"]]
            row(f"{label}" + (f" ({p['reference']})" if p.get("reference") else ""), _amt(p["amount"], cur), size=small)
            if p.get("tendered") and Decimal(p["change_due"]) > 0:
                row("   Cash given / change", f"{_amt(p['tendered'], cur)} / {_amt(p['change_due'], cur)}", size=small)
    rule()
    if r.get("footer"):
        line(r["footer"], small, align="C")
    line("Powered by WaitLess", small - 1, align="C")
    out = pdf.output()
    return bytes(out)
