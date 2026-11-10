"""Test thuật toán Bài 02. Không gọi GenAI, không cần database.

Chia 3 nhóm: ca thường (dữ liệu đề), ca biên, dữ liệu sai.
"""

import random
import time

import pytest

from app.modules.capacity.algo import (
    IMPOSSIBLE,
    NO_OPEN_BATCHES,
    OK,
    Batch,
    Machine,
    hours_needed,
    hours_per_batch,
    min_required_rate,
    pick_machine,
)


def batches(*quantities):
    return [Batch(f"B-{i + 1}", q) for i, q in enumerate(quantities)]


def brute_force(quantities, hours_left):
    """Thử từng tốc độ từ 1 trở lên: chậm nhưng chắc chắn đúng, dùng để đối chiếu."""
    work = [q for q in quantities if q > 0]
    if not work or hours_left < len(work):
        return None
    rate = 1
    while hours_needed(work, rate) > hours_left:
        rate += 1
    return rate


# --- Ca trong đề ----------------------------------------------------------------

def test_exercise_sample():
    result = min_required_rate(batches(30, 11, 23, 4), 8)
    assert result.status == OK
    assert result.min_rate == 11
    assert result.hours_at_min == 8
    assert hours_per_batch(result.work_batches, 11) == [3, 1, 3, 1]
    assert hours_per_batch(result.work_batches, 10) == [3, 2, 3, 1]
    assert hours_needed([30, 11, 23, 4], 10) == 9


def test_exercise_machine_pick():
    pick = pick_machine([Machine("M3", 16), Machine("M1", 8), Machine("M2", 12)], 11)
    assert pick.chosen == Machine("M2", 12)
    assert [m.id for m in pick.fast_enough] == ["M2", "M3"]
    assert [m.id for m in pick.too_slow] == ["M1"]


def test_search_steps_are_binary_not_linear():
    result = min_required_rate(batches(30, 11, 23, 4), 8)
    # Khoảng [1, 30] chỉ cần khoảng log2(30) ≈ 5 lần thử, không phải 11 lần
    assert len(result.steps) <= 5
    assert all(s.fits == (s.hours <= 8) for s in result.steps)
    # Lần thử cuối khoanh được đáp án
    assert result.steps[-1].mid in (10, 11)


# --- Ca biên --------------------------------------------------------------------

def test_no_batches():
    result = min_required_rate([], 8)
    assert result.status == NO_OPEN_BATCHES and result.min_rate is None


def test_only_zero_quantity_batches():
    result = min_required_rate(batches(0, 0), 8)
    assert result.status == NO_OPEN_BATCHES
    assert len(result.zero_batches) == 2


def test_zero_quantity_batch_is_skipped():
    """Lô 0 sản phẩm không chiếm giờ, không làm hỏng điều kiện impossible."""
    result = min_required_rate(batches(0, 20, 20), 4)
    assert result.status == OK
    assert [b.id for b in result.zero_batches] == ["B-1"]
    assert result.min_rate == 10  # 2 + 2 = 4 giờ


def test_exact_deadline_counts_as_in_time():
    result = min_required_rate(batches(20, 20), 4)
    assert result.min_rate == 10
    assert result.hours_at_min == 4  # bằng đúng số giờ còn lại vẫn kịp
    assert hours_needed([20, 20], 9) == 6


def test_zero_hours_left():
    result = min_required_rate(batches(5), 0)
    assert result.status == IMPOSSIBLE
    assert "0 giờ" in result.reason


def test_fewer_hours_than_batches():
    result = min_required_rate(batches(5, 5, 5), 2)
    assert result.status == IMPOSSIBLE and result.min_rate is None


def test_hours_equal_batch_count_needs_max_quantity():
    """Mỗi lô đúng 1 giờ: tốc độ phải bằng lô lớn nhất."""
    result = min_required_rate(batches(100, 80), 2)
    assert result.min_rate == 100


def test_single_batch_single_hour():
    assert min_required_rate(batches(1), 1).min_rate == 1
    assert min_required_rate(batches(7), 1).min_rate == 7


def test_plenty_of_hours_gives_rate_one():
    result = min_required_rate(batches(3, 4), 100)
    assert result.min_rate == 1
    assert result.hours_at_min == 7


def test_no_machine_fast_enough():
    pick = pick_machine([Machine("M8", 40), Machine("M9", 60)], 80)
    assert pick.chosen is None and [m.id for m in pick.too_slow] == ["M8", "M9"]


def test_machine_exactly_at_min_rate_is_enough():
    pick = pick_machine([Machine("M7", 15), Machine("M6", 10)], 10)
    assert pick.chosen.id == "M6"


def test_same_rate_picks_smaller_id():
    pick = pick_machine([Machine("M9", 12), Machine("M2", 12)], 11)
    assert pick.chosen.id == "M2"


def test_no_machines():
    pick = pick_machine([], 5)
    assert pick.chosen is None and pick.fast_enough == [] and pick.too_slow == []


# --- So với cách thử từng tốc độ -------------------------------------------------

def test_matches_brute_force_on_random_data():
    rng = random.Random(7)
    for _ in range(500):
        quantities = [rng.choice([0, rng.randint(1, 60)]) for _ in range(rng.randint(0, 7))]
        hours = rng.randint(0, 25)
        result = min_required_rate(batches(*quantities), hours)
        assert result.min_rate == brute_force(quantities, hours), (quantities, hours)
        if result.min_rate:
            # Đúng là nhỏ nhất: tốc độ kém hơn 1 thì không kịp
            assert hours_needed(quantities, result.min_rate) <= hours
            if result.min_rate > 1:
                assert hours_needed(quantities, result.min_rate - 1) > hours


def test_large_input_is_fast():
    rng = random.Random(1)
    quantities = [rng.randint(1, 10**9) for _ in range(100_000)]
    start = time.perf_counter()
    result = min_required_rate(batches(*quantities), 150_000)
    assert time.perf_counter() - start < 3
    assert result.status == OK
    assert len(result.steps) <= 31  # log2(10^9) ≈ 30


# --- Dữ liệu sai ------------------------------------------------------------------

@pytest.mark.parametrize("quantity", [-1, 2.5, "10", True, None])
def test_bad_quantity(quantity):
    with pytest.raises(ValueError):
        min_required_rate([Batch("B-1", quantity)], 8)


@pytest.mark.parametrize("hours", [-1, 7.5, "8", None])
def test_bad_hours(hours):
    with pytest.raises(ValueError):
        min_required_rate(batches(10), hours)


def test_bad_rate():
    with pytest.raises(ValueError):
        hours_needed([10], 0)
