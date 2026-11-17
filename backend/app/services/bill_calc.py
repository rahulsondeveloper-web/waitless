"""The bill arithmetic (PRD §9, §14; decisions D12, D16, D82–D84) — pure functions, no database.

Order of operations, every amount rounded half-up to the paisa:
1. Food = Σ line totals (price × quantity, before tax).
2. Serving-time discount per order (Phase 8, the order's own %): on the food (D12), split over the order's
   lines in proportion (largest remainder), so an order split over two bills still adds up to its discount.
   Orders whose policy takes the discount off the order *total* get it after tax instead.
3. Manual discount (% or amount) on the food left after (2), split over the lines the same way.
4. Taxable food = food − (2) − (3). Service charge = % of the taxable food.
5. Tax per rate: round(Σ taxable at that rate × rate). The service charge is taxed at its own rate.
   Shown as CGST + SGST halves when the restaurant uses that split.
6. Booking credit (paid booking fee, D16) up to what is due. 7. Round off to the rupee (optional).
"""

import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
HUNDRED = Decimal(100)


def money(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def allocate(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Split `total` (paise exact) over `weights` in proportion — largest remainder, ties to the first."""
    if not weights:
        return []
    paise = int((total * 100).to_integral_value(rounding=ROUND_HALF_UP))
    wsum = sum(weights, Decimal(0))
    if wsum <= 0 or paise == 0:
        return [ZERO for _ in weights]
    raw = [Decimal(paise) * w / wsum for w in weights]
    floors = [int(r) for r in raw]
    left = paise - sum(floors)
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - floors[i]), i))
    for i in order[:left]:
        floors[i] += 1
    return [Decimal(f) / 100 for f in floors]


@dataclass
class OrderInfo:
    """What the bill needs from an order: its serving-time %, its policy base and all its line totals."""

    pct: Decimal
    base: str  # food_subtotal | order_total
    line_totals: dict[uuid.UUID, Decimal]  # every line of the order (also those on other bills)
    tax_pcts: dict[uuid.UUID, Decimal]


@dataclass
class LineIn:
    order_item_id: uuid.UUID
    order_id: uuid.UUID
    line_total: Decimal
    tax_pct: Decimal


@dataclass
class LineOut:
    order_item_id: uuid.UUID
    sla_pct: Decimal
    sla_discount: Decimal
    manual_discount: Decimal
    taxable: Decimal


@dataclass
class Settings:
    service_charge_pct: Decimal = ZERO
    service_charge_tax_pct: Decimal = Decimal("5")
    tax_split: str = "cgst_sgst"  # or "single"
    round_off: bool = True


@dataclass
class Result:
    lines: list[LineOut]
    subtotal: Decimal
    sla_discount: Decimal
    sla_discount_after_tax: Decimal
    manual_discount: Decimal
    taxable: Decimal
    service_charge: Decimal
    tax_total: Decimal
    booking_credit: Decimal
    round_off: Decimal
    grand_total: Decimal
    taxes: list[dict[str, str]] = field(default_factory=list)  # per rate: rate, taxable, tax, cgst, sgst


def _order_discount(info: OrderInfo) -> Decimal:
    """Same rounding as the order screen (Phase 8 `apply_discount`)."""
    food = sum(info.line_totals.values(), Decimal(0))
    if info.pct <= 0:
        return ZERO
    if info.base == "order_total":
        tax = sum((money(t * info.tax_pcts[i] / HUNDRED) for i, t in info.line_totals.items()), Decimal(0))
        return money((food + tax) * info.pct / HUNDRED)
    return money(food * info.pct / HUNDRED)


def compute(
    lines: list[LineIn],
    orders: dict[uuid.UUID, OrderInfo],
    settings: Settings,
    *,
    manual_pct: Decimal | None = None,
    manual_amount: Decimal | None = None,
    credit_available: Decimal = ZERO,
) -> Result:
    # 2. serving-time discount, allocated over each order's lines
    sla_line: dict[uuid.UUID, Decimal] = {}
    after_tax = ZERO
    for oid, info in orders.items():
        ids = list(info.line_totals)
        shares = dict(zip(ids, allocate(_order_discount(info), [info.line_totals[i] for i in ids]), strict=True))
        for ln in lines:
            if ln.order_id != oid:
                continue
            if info.base == "order_total":
                after_tax += shares[ln.order_item_id]
                sla_line[ln.order_item_id] = ZERO
            else:
                sla_line[ln.order_item_id] = shares[ln.order_item_id]
    subtotal = sum((ln.line_total for ln in lines), Decimal(0))
    sla = sum(sla_line.values(), Decimal(0))

    # 3. manual discount on what is left of the food
    after_sla = [ln.line_total - sla_line.get(ln.order_item_id, ZERO) for ln in lines]
    base = sum(after_sla, Decimal(0))
    if manual_pct is not None and manual_pct > 0:
        manual = money(base * manual_pct / HUNDRED)
    elif manual_amount is not None and manual_amount > 0:
        manual = min(money(manual_amount), base)
    else:
        manual = ZERO
    manual_lines = allocate(manual, after_sla)

    # 4–5. taxable, service charge, tax per rate
    out: list[LineOut] = []
    by_rate: dict[Decimal, Decimal] = {}
    for ln, rest, m in zip(lines, after_sla, manual_lines, strict=True):
        taxable = rest - m
        pct = orders[ln.order_id].pct if ln.order_id in orders else ZERO
        out.append(LineOut(ln.order_item_id, pct, sla_line.get(ln.order_item_id, ZERO), m, taxable))
        by_rate[ln.tax_pct] = by_rate.get(ln.tax_pct, Decimal(0)) + taxable
    taxable_food = sum((lo.taxable for lo in out), Decimal(0))
    service = money(taxable_food * settings.service_charge_pct / HUNDRED)
    if service > 0:
        rate = settings.service_charge_tax_pct
        by_rate[rate] = by_rate.get(rate, Decimal(0)) + service
    taxes = []
    tax_total = ZERO
    for rate in sorted(by_rate):
        amount = money(by_rate[rate] * rate / HUNDRED)
        tax_total += amount
        half = money(amount / 2)
        taxes.append(
            {
                "rate": str(rate),
                "taxable": str(money(by_rate[rate])),
                "tax": str(amount),
                "cgst": str(half if settings.tax_split == "cgst_sgst" else ZERO),
                "sgst": str(amount - half if settings.tax_split == "cgst_sgst" else ZERO),
            }
        )

    # 6–7. booking credit and round off
    due = max(taxable_food + service + tax_total - after_tax, ZERO)
    credit = min(money(credit_available), due) if credit_available > 0 else ZERO
    total = due - credit
    round_off = ZERO
    if settings.round_off and total > 0:
        round_off = total.quantize(Decimal(1), rounding=ROUND_HALF_UP) - total
    return Result(
        lines=out,
        subtotal=money(subtotal),
        sla_discount=money(sla),
        sla_discount_after_tax=money(after_tax),
        manual_discount=manual,
        taxable=money(taxable_food),
        service_charge=service,
        tax_total=money(tax_total),
        booking_credit=credit,
        round_off=money(round_off),
        grand_total=money(total + round_off),
        taxes=taxes,
    )
