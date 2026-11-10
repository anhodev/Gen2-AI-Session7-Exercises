"""Test thuật toán xếp lịch Bài 03 (max-heap + hàng đợi chờ). Không cần database hay model."""

import random
import time
from functools import lru_cache

import pytest

from app.modules.notifications.algo import (
    IDLE, NO_MESSAGES, OK, PARTIAL, SEND, UNUSED, Message, build_schedule, check_schedule, min_finish_slots,
)


def msgs(spec: dict[str, int]) -> list[Message]:
    """{"A": 3} -> A1, A2, A3 của khách A."""
    return [Message(f"{c}{i}", c) for c, n in spec.items() for i in range(1, n + 1)]


def row(result) -> list[str]:
    return [s.message_id if s.state == SEND else s.state for s in result.slots]


# --- Ca trong đề -------------------------------------------------------------------

def test_exercise_sample():
    result = build_schedule(msgs({"A": 3, "B": 3}), slot_count=8, gap=2)
    assert result.status == OK
    assert row(result) == ["A1", "B1", "idle", "A2", "B2", "idle", "A3", "B3"]
    assert result.scheduled_count == 6 and result.idle_count == 2
    assert result.finish_slot == 7
    assert [s.index for s in result.slots if s.customer_id == "A"] == [0, 3, 6]
    assert [s.index for s in result.slots if s.customer_id == "B"] == [1, 4, 7]
    assert check_schedule(result.slots, 2) == []


def test_exercise_trace_explains_choice():
    result = build_schedule(msgs({"A": 3, "B": 3}), slot_count=8, gap=2)
    first, idle = result.trace[0], result.trace[2]
    assert first.ready == [("A", 3), ("B", 3)] and first.picked == "A"  # bằng số tin -> theo alphabet
    assert idle.ready == [] and idle.waiting == [("A", 3), ("B", 4)] and idle.picked is None


# --- Ưu tiên ------------------------------------------------------------------------

def test_more_messages_goes_first():
    result = build_schedule(msgs({"A": 1, "B": 3}), slot_count=8, gap=2)
    assert row(result)[0] == "B1"
    assert row(result) == ["B1", "A1", "idle", "B2", "idle", "idle", "B3", "unused"]


def test_same_count_alphabetical_customers():
    result = build_schedule(msgs({"M": 2, "K": 2, "L": 2}), slot_count=6, gap=2)
    assert row(result) == ["K1", "L1", "M1", "K2", "L2", "M2"]
    assert result.idle_count == 0


def test_messages_alphabetical_within_customer():
    messages = [Message("A-zeta", "A"), Message("A-alpha", "A"), Message("A-mid", "A")]
    result = build_schedule(messages, slot_count=7, gap=2)
    assert [s.message_id for s in result.slots if s.state == SEND] == ["A-alpha", "A-mid", "A-zeta"]


def test_customer_back_from_waiting_competes_by_count():
    # Sau khi chờ xong, A (còn 2 tin) phải được ưu tiên hơn C (còn 1 tin)
    result = build_schedule(msgs({"A": 3, "B": 1, "C": 1}), slot_count=8, gap=1)
    assert row(result) == ["A1", "B1", "A2", "C1", "A3", "unused", "unused", "unused"]


# --- Ca biên --------------------------------------------------------------------------

def test_single_customer_has_idle_gaps():
    result = build_schedule(msgs({"F": 3}), slot_count=8, gap=2)
    assert row(result) == ["F1", "idle", "idle", "F2", "idle", "idle", "F3", "unused"]
    assert result.idle_count == 4


def test_gap_zero_allows_back_to_back():
    result = build_schedule(msgs({"G": 2, "H": 1}), slot_count=4, gap=0)
    assert row(result) == ["G1", "G2", "H1", "unused"]
    assert check_schedule(result.slots, 0) == []


def test_out_of_slots_reports_unscheduled():
    result = build_schedule(msgs({"N": 4, "P": 1}), slot_count=6, gap=2)
    assert result.status == PARTIAL
    assert row(result) == ["N1", "P1", "idle", "N2", "idle", "idle"]
    assert [m.id for m in result.unscheduled] == ["N3", "N4"]


def test_no_messages():
    result = build_schedule([], slot_count=3, gap=2)
    assert result.status == NO_MESSAGES
    assert [s.state for s in result.slots] == [UNUSED] * 3


def test_zero_slots():
    result = build_schedule(msgs({"A": 1}), slot_count=0, gap=2)
    assert result.status == PARTIAL and result.slots == [] and [m.id for m in result.unscheduled] == ["A1"]


def test_exact_fit_last_slot():
    result = build_schedule(msgs({"A": 2}), slot_count=4, gap=2)
    assert result.status == OK and row(result) == ["A1", "idle", "idle", "A2"]


@pytest.mark.parametrize("slot_count, gap, messages", [
    (-1, 2, []),
    (3, -1, []),
    (3, 1.5, []),
    (True, 1, []),
    (3, 1, [Message("A1", "A"), Message("A1", "B")]),
])
def test_bad_input(slot_count, gap, messages):
    with pytest.raises(ValueError):
        build_schedule(messages, slot_count, gap)


# --- Kiểm tra lịch -----------------------------------------------------------------------

def test_check_schedule_finds_violation():
    from app.modules.notifications.algo import Slot
    slots = [Slot(0, SEND, "A1", "A"), Slot(1, IDLE), Slot(2, SEND, "A2", "A")]
    assert check_schedule(slots, 2) == ["Khách A nhận ở ô 0 và 2, cần cách ít nhất 2 ô ở giữa"]
    assert check_schedule(slots, 1) == []


# --- So với lời giải tối ưu ----------------------------------------------------------------

@lru_cache(maxsize=None)
def brute_min_slots(counts: tuple[int, ...], cooldown: tuple[int, ...], gap: int) -> int:
    """Thử mọi cách chọn ở mỗi ô (kể cả idle). counts/cooldown theo từng khách."""
    if sum(counts) == 0:
        return 0
    best = 10**9
    tick = tuple(max(0, c - 1) for c in cooldown)
    for k, (n, wait) in enumerate(zip(counts, cooldown)):
        if n and wait == 0:
            nc = counts[:k] + (n - 1,) + counts[k + 1:]
            cd = tick[:k] + (gap,) + tick[k + 1:]
            best = min(best, 1 + brute_min_slots(nc, cd, gap))
    if best == 10**9:  # không ai sẵn sàng: bắt buộc idle
        best = 1 + brute_min_slots(counts, tick, gap)
    return best


@pytest.mark.parametrize("seed", range(150))
def test_greedy_is_optimal_on_small_cases(seed):
    rng = random.Random(seed)
    counts = {chr(65 + k): rng.randint(0, 4) for k in range(rng.randint(1, 4))}
    gap = rng.randint(0, 3)
    messages = msgs(counts)
    result = build_schedule(messages, slot_count=60, gap=gap)
    finish = 0 if result.finish_slot is None else result.finish_slot + 1

    assert finish == brute_min_slots(tuple(counts.values()), (0,) * len(counts), gap)
    assert finish == min_finish_slots(list(counts.values()), gap)
    assert check_schedule(result.slots, gap) == []
    assert sorted(s.message_id for s in result.slots if s.state == SEND) == sorted(m.id for m in messages)


def test_random_schedules_are_valid_with_limited_slots():
    rng = random.Random(7)
    for _ in range(300):
        counts = {f"C{k:02d}": rng.randint(0, 6) for k in range(rng.randint(1, 8))}
        gap, slot_count = rng.randint(0, 4), rng.randint(0, 25)
        messages = msgs(counts)
        result = build_schedule(messages, slot_count, gap)
        assert len(result.slots) == slot_count
        assert check_schedule(result.slots, gap) == []
        sent = [s.message_id for s in result.slots if s.state == SEND]
        assert sorted(sent + [m.id for m in result.unscheduled]) == sorted(m.id for m in messages)
        # Còn tin chưa xếp thì mọi ô phải đã dùng (gửi hoặc idle), không bỏ trống
        if result.unscheduled:
            assert all(s.state != UNUSED for s in result.slots)


def test_large_input_is_fast():
    messages = msgs({f"K{k:05d}": 5 for k in range(20_000)})
    start = time.perf_counter()
    result = build_schedule(messages, slot_count=100_000, gap=3)
    assert time.perf_counter() - start < 3
    assert result.status == OK and result.scheduled_count == 100_000
