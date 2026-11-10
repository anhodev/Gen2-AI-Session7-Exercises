"""Bài 03 - Xếp lịch gửi thông báo: max-heap + hàng đợi chờ (thời gian chờ giữa hai tin cho cùng khách).

Quy tắc (theo đề):
  - Có n ô thời gian, mỗi ô gửi tối đa một tin.
  - Gửi cho khách A ở ô i thì phải có ít nhất `gap` ô khác ở giữa: A nhận tiếp sớm nhất ở ô i + gap + 1.
  - Tin của khách chưa đồng ý nhận bị loại trước khi xếp (do tầng gọi hàm lọc, xem tools.py).
  - Ưu tiên khách còn nhiều tin chưa gửi (max-heap). Bằng số tin thì chọn mã khách theo alphabet.
    Trong cùng một khách, gửi tin theo mã tin alphabet.
  - Không có khách nào đủ điều kiện ở một ô -> ô đó idle.
  - Hết ô mà còn tin -> báo tin chưa xếp được, không đẩy sang ngày khác.

Cách chạy: heap chứa khách sẵn sàng (-số tin còn lại, mã khách). Gửi xong một tin, nếu khách còn tin thì cho vào
hàng đợi chờ kèm ô sớm nhất được nhận tiếp. Mỗi ô chỉ đẩy tối đa một khách vào hàng đợi, nên ô sẵn sàng trong
hàng đợi tăng dần: chỉ cần xem đầu hàng đợi.

Không phụ thuộc database hay GenAI, test được riêng.
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field

# Trạng thái kết quả
OK = "ok"  # xếp hết tin
PARTIAL = "partial"  # hết ô mà còn tin chưa xếp
NO_MESSAGES = "no_messages"  # không còn tin nào để xếp (sau khi loại khách chưa đồng ý)

# Trạng thái ô
SEND = "send"
IDLE = "idle"  # còn tin nhưng không khách nào đủ điều kiện ở ô này
UNUSED = "unused"  # đã xếp hết tin, ô để trống

TRACE_LIMIT = 48  # chỉ ghi các bước của 48 ô đầu, đủ cho một ngày; dữ liệu lớn không phình kết quả


@dataclass(frozen=True)
class Message:
    id: str
    customer_id: str


@dataclass
class Slot:
    index: int
    state: str  # send, idle, unused
    message_id: str | None = None
    customer_id: str | None = None


@dataclass
class TraceStep:
    """Trạng thái lúc bắt đầu một ô, để giải thích vì sao chọn khách đó."""

    slot: int
    ready: list[tuple[str, int]]  # (mã khách, số tin còn lại), theo thứ tự ưu tiên của heap
    waiting: list[tuple[str, int]]  # (mã khách, ô sớm nhất được nhận tiếp)
    picked: str | None


@dataclass
class ScheduleResult:
    status: str
    slots: list[Slot] = field(default_factory=list)
    unscheduled: list[Message] = field(default_factory=list)
    trace: list[TraceStep] = field(default_factory=list)
    finish_slot: int | None = None  # ô của tin cuối cùng được xếp

    @property
    def scheduled_count(self) -> int:
        return sum(1 for s in self.slots if s.state == SEND)

    @property
    def idle_count(self) -> int:
        return sum(1 for s in self.slots if s.state == IDLE)


def check_input(messages: list[Message], slot_count: int, gap: int) -> None:
    """
    Raises:
        ValueError: Số ô hoặc gap không phải số nguyên không âm, hoặc mã tin bị trùng.
    """
    for name, value in (("slot_count", slot_count), ("gap", gap)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} phải là số nguyên không âm, nhận {value!r}")
    ids = [m.id for m in messages]
    if len(ids) != len(set(ids)):
        raise ValueError("Mã tin bị trùng")


def build_schedule(messages: list[Message], slot_count: int, gap: int, trace_limit: int = TRACE_LIMIT) -> ScheduleResult:
    """
    Xếp tin vào các ô thời gian.

    Args:
        messages (list[Message]): Tin của khách đã đồng ý nhận.
        slot_count (int): Số ô thời gian trong ngày.
        gap (int): Số ô tối thiểu phải có ở giữa hai tin cho cùng khách.
        trace_limit (int, optional): Số ô đầu được ghi lại các bước chọn khách.

    Raises:
        ValueError: Dữ liệu không hợp lệ.

    Returns:
        ScheduleResult: Lịch từng ô, tin chưa xếp được, các bước chọn khách.
    """
    check_input(messages, slot_count, gap)
    if not messages:
        return ScheduleResult(status=NO_MESSAGES, slots=[Slot(i, UNUSED) for i in range(slot_count)])

    queues: dict[str, deque[str]] = {}
    for m in sorted(messages, key=lambda m: m.id):
        queues.setdefault(m.customer_id, deque()).append(m.id)

    ready = [(-len(q), customer) for customer, q in queues.items()]
    heapq.heapify(ready)
    waiting: deque[tuple[int, str]] = deque()  # (ô sớm nhất được nhận tiếp, mã khách)
    result = ScheduleResult(status=OK)

    for i in range(slot_count):
        if not ready and not waiting:
            result.slots.append(Slot(i, UNUSED))
            continue
        while waiting and waiting[0][0] <= i:
            _, customer = waiting.popleft()
            heapq.heappush(ready, (-len(queues[customer]), customer))

        step = None
        if i < trace_limit:
            step = TraceStep(i, [(c, -n) for n, c in sorted(ready)], [(c, at) for at, c in waiting], None)
            result.trace.append(step)
        if not ready:
            result.slots.append(Slot(i, IDLE))
            continue

        _, customer = heapq.heappop(ready)
        message_id = queues[customer].popleft()
        result.slots.append(Slot(i, SEND, message_id, customer))
        result.finish_slot = i
        if step:
            step.picked = customer
        if queues[customer]:
            waiting.append((i + gap + 1, customer))

    left = [Message(mid, c) for c, q in queues.items() for mid in q]
    if left:
        result.status = PARTIAL
        result.unscheduled = sorted(left, key=lambda m: (m.customer_id, m.id))
    return result


def check_schedule(slots: list[Slot], gap: int) -> list[str]:
    """
    Kiểm tra lại một lịch: mỗi ô tối đa một tin, khoảng cách giữa hai tin cùng khách đủ gap.

    Returns:
        list[str]: Các vi phạm; rỗng nghĩa là lịch hợp lệ.
    """
    problems = []
    last: dict[str, int] = {}
    seen_slots = set()
    for s in slots:
        if s.index in seen_slots:
            problems.append(f"Ô {s.index} có nhiều hơn một tin")
        seen_slots.add(s.index)
        if s.state != SEND:
            continue
        prev = last.get(s.customer_id)
        if prev is not None and s.index - prev <= gap:
            problems.append(f"Khách {s.customer_id} nhận ở ô {prev} và {s.index}, cần cách ít nhất {gap} ô ở giữa")
        last[s.customer_id] = s.index
    return problems


def min_finish_slots(counts: list[int], gap: int) -> int:
    """
    Số ô ít nhất để gửi hết tin khi không giới hạn số ô (công thức của bài xếp việc có thời gian chờ).
    Dùng trong test để so với thuật toán tham lam.
    """
    counts = [c for c in counts if c > 0]
    if not counts:
        return 0
    top = max(counts)
    with_top = counts.count(top)
    return max(sum(counts), (top - 1) * (gap + 1) + with_top)
