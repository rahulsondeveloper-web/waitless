"""Phase 8 acceptance (test 12): the serving-time discount against the PRD §14 table and the cap."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.services.sla import DEFAULT_POLICY, apply_discount, discount_pct, next_boundary

T0 = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (0, "0"),
        (14.99, "0"),
        (15, "0"),  # "up to 15 min: 0 %"
        (15.01, "2"),
        (16, "2"),
        (20, "2"),  # "more than 15 to 20: 2 %"
        (21, "4"),
        (25, "4"),
        (26, "6"),
        (30, "6"),
        (35, "8"),  # "more than 30 to 35: 8 %"
        (60, "18"),
        (65, "20"),
        (120, "20"),  # capped at the maximum (default 20 %)
    ],
)
def test_default_policy_matches_prd_table(minutes: float, expected: str) -> None:
    assert discount_pct(minutes * 60, DEFAULT_POLICY) == Decimal(expected)


def test_custom_policy_and_cap() -> None:
    policy = {
        **DEFAULT_POLICY,
        "serving_minutes": 10,
        "initial_pct": "5",
        "interval_minutes": 10,
        "increment_pct": "2.5",
        "max_pct": "9",
    }
    assert discount_pct(10 * 60, policy) == Decimal("0")
    assert discount_pct(11 * 60, policy) == Decimal("5")
    assert discount_pct(20 * 60, policy) == Decimal("5")
    assert discount_pct(21 * 60, policy) == Decimal("7.50")
    assert discount_pct(31 * 60, policy) == Decimal("9")  # 10 % capped to 9


def test_next_boundary() -> None:
    p = DEFAULT_POLICY
    assert next_boundary(T0, T0 + timedelta(minutes=3), p) == T0 + timedelta(minutes=15)
    assert next_boundary(T0, T0 + timedelta(minutes=15), p) == T0 + timedelta(minutes=15)
    assert next_boundary(T0, T0 + timedelta(minutes=15, seconds=1), p) == T0 + timedelta(minutes=20)
    assert next_boundary(T0, T0 + timedelta(minutes=20), p) == T0 + timedelta(minutes=20)
    assert next_boundary(T0, T0 + timedelta(minutes=21), p) == T0 + timedelta(minutes=25)
    assert next_boundary(T0, T0 + timedelta(minutes=70), p) is None  # 20 % reached: no more steps


def test_discount_base() -> None:
    # food subtotal (D12): 4 % of 1000 = 40; tax charged on 960 → 48; payable 1008
    assert apply_discount(Decimal("1000"), Decimal("50"), Decimal("4"), "food_subtotal") == (
        Decimal("40.00"),
        Decimal("1008.00"),
    )
    # order total: 4 % of 1050 = 42 → 1008
    assert apply_discount(Decimal("1000"), Decimal("50"), Decimal("4"), "order_total") == (
        Decimal("42.00"),
        Decimal("1008.00"),
    )
    assert apply_discount(Decimal("378"), Decimal("18"), Decimal("0"), "food_subtotal") == (
        Decimal("0.00"),
        Decimal("396.00"),
    )
