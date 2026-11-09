"""Test thuật toán Bài 01. Không gọi GenAI, không cần database.

Chia 3 nhóm: ca thường (dữ liệu đề), ca biên, dữ liệu sai.
"""

import random
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.invoices.algo import (
    MATCHED,
    NO_MATCH,
    Transfer,
    find_pair,
    format_amount,
    match_two_transfers,
)

T0 = datetime(2026, 11, 3, 2, 0, tzinfo=timezone.utc)  # 09:00 giờ Việt Nam


def tr(id, amount, minute=0, customer="C-12", currency="VND", status="unmatched"):
    return Transfer(id, customer, currency, amount, T0 + timedelta(minutes=minute), status)


def exercise_transfers():
    """Bảng giao dịch trong đề, cố tình xáo thứ tự để thấy thuật toán tự sắp."""
    return [
        tr("P3", 600_000, 10),
        tr("P5", 600_000, 3, currency="USD"),
        tr("P1", 900_000, 0),
        tr("P4", 600_000, 2, customer="C-99"),
        tr("P2", 600_000, 5),
    ]


def ids(result):
    return [t.id for t in result.pair] if result.pair else None


# --- Ca thường --------------------------------------------------------------

def test_exercise_sample_picks_p1_p2():
    result = match_two_transfers(exercise_transfers(), "C-12", "VND", 1_500_000)
    assert result.status == MATCHED
    assert ids(result) == ["P1", "P2"]
    assert sum(t.amount_minor for t in result.pair) == 1_500_000


def test_exercise_sample_explains_exclusions_and_tie():
    result = match_two_transfers(exercise_transfers(), "C-12", "VND", 1_500_000)
    assert [t.id for t in result.eligible] == ["P1", "P2", "P3"]
    assert [(t.id, why) for t, why in result.excluded] == [("P4", "wrong_customer"), ("P5", "wrong_currency")]
    assert result.other_pairs == [("P1", "P3")]  # cũng đủ tiền nhưng P2 đến sớm hơn


def test_no_pair_returns_no_match_not_closest():
    transfers = [tr("A", 500_000, 0), tr("B", 700_000, 1), tr("C", 900_000, 2)]
    result = match_two_transfers(transfers, "C-12", "VND", 2_000_000)
    assert result.status == NO_MATCH
    assert result.pair is None
    assert "3 giao dịch hợp lệ" in result.reason


def test_two_transfers_with_same_amount_can_pair():
    transfers = [tr("Q1", 500_000, 0), tr("Q2", 500_000, 5)]
    result = match_two_transfers(transfers, "C-12", "VND", 1_000_000)
    assert ids(result) == ["Q1", "Q2"]


def test_usd_in_cents():
    transfers = [tr("U1", 15_000, 0, currency="USD"), tr("U2", 10_050, 1, currency="USD")]
    result = match_two_transfers(transfers, "C-12", "USD", 25_050)
    assert ids(result) == ["U1", "U2"]


# --- Ca biên ----------------------------------------------------------------

def test_transfer_never_pairs_with_itself():
    result = match_two_transfers([tr("S1", 500_000)], "C-12", "VND", 1_000_000)
    assert result.status == NO_MATCH
    assert "Chỉ có 1 giao dịch" in result.reason


def test_no_transfers_at_all():
    result = match_two_transfers([], "C-12", "VND", 1_000_000)
    assert result.status == NO_MATCH
    assert result.eligible == []


def test_already_matched_transfer_is_skipped():
    transfers = [tr("M1", 900_000, 0, status="matched"), tr("M2", 600_000, 1), tr("M3", 900_000, 2)]
    result = match_two_transfers(transfers, "C-12", "VND", 1_500_000)
    assert ids(result) == ["M2", "M3"]
    assert [(t.id, why) for t, why in result.excluded] == [("M1", "already_matched")]


@pytest.mark.parametrize("amount", [0, -300_000])
def test_zero_or_refund_is_skipped(amount):
    transfers = [tr("R1", amount, 0), tr("R2", 1_500_000 - amount, 1)]
    result = match_two_transfers(transfers, "C-12", "VND", 1_500_000)
    assert result.status == NO_MATCH
    assert ("R1", "non_positive_amount") in [(t.id, why) for t, why in result.excluded]


def test_same_time_sorted_by_id():
    transfers = [tr("P9", 600_000, 0), tr("P8", 600_000, 0), tr("P7", 900_000, 0)]
    result = match_two_transfers(transfers, "C-12", "VND", 1_500_000)
    assert [t.id for t in result.eligible] == ["P7", "P8", "P9"]
    assert ids(result) == ["P7", "P8"]


def test_pair_that_completes_first_wins():
    # A+D và B+C đều đủ 1000. Quét: A, B, C (B+C hoàn tất ở C), D -> chọn B+C
    transfers = [tr("A", 100, 0), tr("B", 400, 1), tr("C", 600, 2), tr("D", 900, 3)]
    result = match_two_transfers(transfers, "C-12", "VND", 1_000)
    assert ids(result) == ["B", "C"]
    assert result.other_pairs == [("A", "D")]


def test_result_does_not_depend_on_input_order():
    transfers = exercise_transfers()
    for seed in range(5):
        random.Random(seed).shuffle(transfers)
        assert ids(match_two_transfers(transfers, "C-12", "VND", 1_500_000)) == ["P1", "P2"]


def brute_force(amounts, target):
    """Cách chậm O(n²) để so: j nhỏ nhất, rồi i nhỏ nhất."""
    for j in range(len(amounts)):
        for i in range(j):
            if amounts[i] + amounts[j] == target:
                return i, j
    return None


def test_hash_map_agrees_with_brute_force():
    rng = random.Random(7)
    for _ in range(500):
        amounts = [rng.randint(1, 20) for _ in range(rng.randint(0, 12))]
        target = rng.randint(2, 40)
        assert find_pair(amounts, target) == brute_force(amounts, target)


def test_large_input_is_fast():
    amounts = list(range(1, 200_001))
    assert find_pair(amounts, 399_999) == (199_998, 199_999)


# --- Dữ liệu sai ------------------------------------------------------------

@pytest.mark.parametrize("due", [0, -1])
def test_amount_due_must_be_positive(due):
    with pytest.raises(ValueError):
        match_two_transfers([], "C-12", "VND", due)


@pytest.mark.parametrize("bad", [1500000.0, "1500000", True])
def test_amount_due_must_be_integer(bad):
    with pytest.raises(ValueError):
        match_two_transfers([], "C-12", "VND", bad)


def test_transfer_amount_must_be_integer():
    with pytest.raises(ValueError):
        match_two_transfers([tr("F1", 0.1 + 0.2)], "C-12", "VND", 1)


# --- Hiển thị tiền ------------------------------------------------------------

@pytest.mark.parametrize("amount, currency, text", [
    (1_500_000, "VND", "1.500.000 VND"),
    (0, "VND", "0 VND"),
    (25_050, "USD", "250.50 USD"),
    (5, "USD", "0.05 USD"),
    (-300_000, "VND", "-300.000 VND"),
    (100, "EUR", "100 EUR (đơn vị nhỏ nhất)"),
])
def test_format_amount(amount, currency, text):
    assert format_amount(amount, currency) == text
