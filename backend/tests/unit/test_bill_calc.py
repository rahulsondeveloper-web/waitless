"""Phase 10 acceptance (test 14): the bill matches a hand-calculated fixture to the paisa —
items, serving-time discount, manual discount, tax, service charge and booking credit."""

import uuid
from decimal import Decimal as D

from app.services.bill_calc import LineIn, OrderInfo, Settings, allocate, compute

A1, A2, B1, B2, C1 = (uuid.uuid4() for _ in range(5))
OA, OB, OC = (uuid.uuid4() for _ in range(3))


def test_hand_calculated_bill() -> None:
    """
    Order A (served 21 min after accepting → 4 %): 2 × Paneer Tikka 249.00 = 498.00
                                                  3 × Butter Naan 45.50 = 136.50 (5 % GST)
    Order B (on time): 2 × Fresh Lime Soda 89.00 = 178.00 (12 %) · 1 × Gulab Jamun 120.00 (5 %)
    Manual discount 10 %, service charge 5 % (taxed at 5 %), booking fee 300 credited, round off.

    Food 932.50
    Serving-time discount A: 4 % × 634.50 = 25.38 → Paneer 19.92, Naan 5.46 (in proportion)
    Manual 10 % × (932.50 − 25.38 = 907.12) = 90.71 → 47.81 / 13.10 / 17.80 / 12.00 (largest remainder)
    Taxable food 816.41 = 430.27 + 117.94 + 160.20 + 108.00
    Service charge 5 % × 816.41 = 40.82
    GST 5 %: (430.27 + 117.94 + 108.00 + 40.82 = 697.03) × 5 % = 34.85 → CGST 17.43 + SGST 17.42
    GST 12 %: 160.20 × 12 % = 19.22 → 9.61 + 9.61
    Due 816.41 + 40.82 + 54.07 = 911.30 − booking credit 300.00 = 611.30 → round off −0.30 → 611.00
    """
    orders = {
        OA: OrderInfo(D("4"), "food_subtotal", {A1: D("498.00"), A2: D("136.50")}, {A1: D("5"), A2: D("5")}),
        OB: OrderInfo(D("0"), "food_subtotal", {B1: D("178.00"), B2: D("120.00")}, {B1: D("12"), B2: D("5")}),
    }
    lines = [
        LineIn(A1, OA, D("498.00"), D("5")),
        LineIn(A2, OA, D("136.50"), D("5")),
        LineIn(B1, OB, D("178.00"), D("12")),
        LineIn(B2, OB, D("120.00"), D("5")),
    ]
    r = compute(
        lines,
        orders,
        Settings(service_charge_pct=D("5"), service_charge_tax_pct=D("5"), tax_split="cgst_sgst", round_off=True),
        manual_pct=D("10"),
        credit_available=D("300.00"),
    )
    assert r.subtotal == D("932.50")
    assert r.sla_discount == D("25.38") and r.sla_discount_after_tax == D("0.00")
    assert [ln.sla_discount for ln in r.lines] == [D("19.92"), D("5.46"), D("0.00"), D("0.00")]
    assert r.manual_discount == D("90.71")
    assert [ln.manual_discount for ln in r.lines] == [D("47.81"), D("13.10"), D("17.80"), D("12.00")]
    assert [ln.taxable for ln in r.lines] == [D("430.27"), D("117.94"), D("160.20"), D("108.00")]
    assert r.taxable == D("816.41")
    assert r.service_charge == D("40.82")
    assert r.taxes == [
        {"rate": "5", "taxable": "697.03", "tax": "34.85", "cgst": "17.43", "sgst": "17.42"},
        {"rate": "12", "taxable": "160.20", "tax": "19.22", "cgst": "9.61", "sgst": "9.61"},
    ]
    assert r.tax_total == D("54.07")
    assert r.booking_credit == D("300.00")
    assert r.round_off == D("-0.30")
    assert r.grand_total == D("611.00")


def test_order_total_base_credit_cap_and_no_round_off() -> None:
    # 1 × 200.00 at 5 %, 6 % off the order *total* (210.00) = 12.60 after tax.
    orders = {OC: OrderInfo(D("6"), "order_total", {C1: D("200.00")}, {C1: D("5")})}
    lines = [LineIn(C1, OC, D("200.00"), D("5"))]
    r = compute(lines, orders, Settings(round_off=False, tax_split="single"))
    assert (r.taxable, r.tax_total, r.sla_discount_after_tax, r.grand_total) == (
        D("200.00"),
        D("10.00"),
        D("12.60"),
        D("197.40"),
    )
    assert r.taxes[0]["cgst"] == "0.00"
    covered = compute(lines, orders, Settings(round_off=True), credit_available=D("500"))
    assert covered.booking_credit == D("197.40") and covered.grand_total == D("0.00") and covered.round_off == D("0.00")


def test_split_order_keeps_its_discount_exact() -> None:
    """An order split across two bills: the two shares add up to the order's own discount."""
    info = OrderInfo(D("2"), "food_subtotal", {A1: D("333.33"), A2: D("333.34")}, {A1: D("5"), A2: D("5")})
    one = compute([LineIn(A1, OA, D("333.33"), D("5"))], {OA: info}, Settings(round_off=False))
    two = compute([LineIn(A2, OA, D("333.34"), D("5"))], {OA: info}, Settings(round_off=False))
    assert one.sla_discount + two.sla_discount == D("13.33")  # 2 % of 666.67


def test_allocate() -> None:
    assert allocate(D("1.00"), [D("1"), D("1"), D("1")]) == [D("0.34"), D("0.33"), D("0.33")]
    assert allocate(D("0"), [D("5")]) == [D("0")]
    assert allocate(D("5"), []) == []
