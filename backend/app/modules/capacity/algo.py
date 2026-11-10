"""Bài 02 - Tìm tốc độ máy tối thiểu để xong các lô trong ca, bằng tìm kiếm nhị phân trên đáp án.

Quy tắc (theo đề):
  - Một máy làm từng lô lần lượt. Lô q sản phẩm, máy r sản phẩm/giờ -> chiếm ceil(q / r) giờ.
  - Không ghép phần giờ lẻ của hai lô. Thời gian đổi lô = 0.
  - Tổng giờ không được vượt số giờ còn lại của ca (bằng đúng vẫn kịp).

Vì tốc độ r kịp thì mọi tốc độ lớn hơn cũng kịp (số giờ không tăng khi r tăng),
nên tìm r nhỏ nhất bằng tìm kiếm nhị phân trên đoạn [1, max(q)]:
ở r = max(q) mỗi lô chỉ cần 1 giờ, nên nếu ca còn ít nhất (số lô) giờ thì r = max(q) chắc chắn kịp.

Không phụ thuộc database hay GenAI, test được riêng.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Trạng thái kết quả
OK = "ok"  # có tốc độ tối thiểu và có máy đủ nhanh
NO_OPEN_BATCHES = "no_open_batches"  # không còn lô nào có sản phẩm
IMPOSSIBLE = "impossible_under_rules"  # số giờ còn lại ít hơn số lô có sản phẩm
NO_MACHINE = "no_machine_fast_enough"  # có tốc độ tối thiểu nhưng không máy rảnh nào đạt


@dataclass(frozen=True)
class Batch:
    id: str
    quantity: int


@dataclass(frozen=True)
class Machine:
    id: str
    rate: int  # sản phẩm/giờ


@dataclass(frozen=True)
class SearchStep:
    """Một bước tìm kiếm nhị phân: thử tốc độ mid trong khoảng [low, high]."""

    low: int
    high: int
    mid: int
    hours: int  # số giờ cần ở tốc độ mid
    fits: bool  # hours <= số giờ còn lại


@dataclass
class RateResult:
    status: str
    hours_left: int
    work_batches: list[Batch]  # lô có sản phẩm, đưa vào tính
    zero_batches: list[Batch]  # lô số lượng 0, bỏ qua (cần 0 giờ)
    min_rate: int | None = None
    hours_at_min: int | None = None
    steps: list[SearchStep] = field(default_factory=list)
    reason: str = ""


@dataclass
class MachinePick:
    chosen: Machine | None  # máy chậm nhất vẫn đạt; None nếu không có
    fast_enough: list[Machine]  # theo tốc độ tăng dần
    too_slow: list[Machine]


def ceil_div(a: int, b: int) -> int:
    """ceil(a / b) với số nguyên dương, không dùng số thực để khỏi sai số."""
    return -(-a // b)


def hours_needed(quantities: list[int], rate: int) -> int:
    """Tổng giờ cần ở tốc độ rate. Lô số lượng 0 cần 0 giờ."""
    if rate <= 0:
        raise ValueError("Tốc độ phải là số nguyên dương")
    return sum(ceil_div(q, rate) for q in quantities if q > 0)


def hours_per_batch(batches: list[Batch], rate: int) -> list[int]:
    return [ceil_div(b.quantity, rate) for b in batches]


def check_input(batches: list[Batch], hours_left: int) -> None:
    """
    Raises:
        ValueError: Số lượng hoặc số giờ không phải số nguyên, hoặc âm.
    """
    if isinstance(hours_left, bool) or not isinstance(hours_left, int) or hours_left < 0:
        raise ValueError(f"Số giờ còn lại phải là số nguyên không âm, nhận {hours_left!r}")
    for b in batches:
        if isinstance(b.quantity, bool) or not isinstance(b.quantity, int) or b.quantity < 0:
            raise ValueError(f"Lô {b.id}: số lượng phải là số nguyên không âm, nhận {b.quantity!r}")


def min_required_rate(batches: list[Batch], hours_left: int) -> RateResult:
    """
    Tìm tốc độ nguyên nhỏ nhất để làm xong mọi lô trong số giờ còn lại.

    Args:
        batches (list[Batch]): Các lô chưa làm.
        hours_left (int): Số giờ còn dùng được trong ca.

    Raises:
        ValueError: Dữ liệu không phải số nguyên không âm.

    Returns:
        RateResult: status ok (kèm min_rate), no_open_batches hoặc impossible_under_rules.
    """
    check_input(batches, hours_left)
    work = [b for b in batches if b.quantity > 0]
    zero = [b for b in batches if b.quantity == 0]
    result = RateResult(status=OK, hours_left=hours_left, work_batches=work, zero_batches=zero)

    if not work:
        result.status = NO_OPEN_BATCHES
        result.reason = "Không còn lô nào có sản phẩm cần làm"
        return result
    if hours_left < len(work):
        result.status = IMPOSSIBLE
        result.reason = (
            f"Ca còn {hours_left} giờ nhưng có {len(work)} lô; mỗi lô cần ít nhất 1 giờ "
            "và không ghép giờ lẻ, nên máy nhanh đến đâu cũng không kịp"
        )
        return result

    quantities = [b.quantity for b in work]
    low, high = 1, max(quantities)  # high luôn kịp (giải thích ở đầu file)
    while low < high:
        mid = (low + high) // 2
        hours = hours_needed(quantities, mid)
        fits = hours <= hours_left
        result.steps.append(SearchStep(low, high, mid, hours, fits))
        if fits:
            high = mid  # mid kịp: đáp án <= mid
        else:
            low = mid + 1  # mid không kịp: đáp án > mid

    result.min_rate = low
    result.hours_at_min = hours_needed(quantities, low)
    result.reason = f"{low} là tốc độ nguyên nhỏ nhất có tổng giờ ({result.hours_at_min}) không vượt {hours_left} giờ"
    return result


def pick_machine(machines: list[Machine], min_rate: int) -> MachinePick:
    """
    Chọn máy chậm nhất vẫn đạt tốc độ tối thiểu, để dành máy nhanh hơn cho việc khác.
    Cùng tốc độ thì lấy mã nhỏ hơn cho kết quả ổn định.
    """
    ordered = sorted(machines, key=lambda m: (m.rate, m.id))
    fast = [m for m in ordered if m.rate >= min_rate]
    slow = [m for m in ordered if m.rate < min_rate]
    return MachinePick(chosen=fast[0] if fast else None, fast_enough=fast, too_slow=slow)
