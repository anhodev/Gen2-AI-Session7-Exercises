"""Bài 02 - Công cụ cho model gọi.

  get_open_batches(line_id)                                read       Lô chưa làm và số sản phẩm mỗi lô
  get_shift_hours(line_id, shift_id)                       read       Số giờ còn dùng được trong ca
  get_available_machines(line_id)                          read       Máy đang rảnh và tốc độ (sản phẩm/giờ)
  calculate_min_required_rate(line_id, shift_id)           algorithm  Tự đọc lại 3 nguồn, tìm kiếm nhị phân, chọn máy
  propose_machine_booking(line_id, shift_id, machine_id)   action     Đề xuất đặt máy, chờ trưởng ca xác nhận

Model chỉ truyền mã. Số lượng, số giờ, tốc độ máy luôn đọc từ database, không nhận từ model.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.proposals import create_proposal, proposal_view
from app.core.tools import ToolArgs, ToolContext, ToolError, with_kind

from . import algo
from .entities import Machine, ProductionLine, Shift
from .store import AVAILABLE, available_machines, open_batches

LINE_ID = r"^L-\d{1,10}$"
SHIFT_ID = r"^CA-\d{1,10}$"
MACHINE_ID = r"^M\d{1,10}$"

PROPOSAL_KIND = "machine_booking"
RULE = (
    "Mỗi máy làm từng lô lần lượt; lô q sản phẩm ở tốc độ r chiếm ceil(q/r) giờ; không ghép giờ lẻ của hai lô; "
    "đổi lô mất 0 giờ; tổng giờ không vượt số giờ còn lại (bằng đúng vẫn kịp). "
    "Tìm r nhỏ nhất bằng tìm kiếm nhị phân; chọn máy rảnh chậm nhất vẫn đạt r."
)
MACHINE_STATUS = {"busy": "đang chạy việc khác", "maintenance": "đang bảo trì", "reserved": "đã được đặt"}


class LineArgs(ToolArgs):
    line_id: str = Field(pattern=LINE_ID, description="Mã dây chuyền người dùng nói, vd L-1")


class LineShiftArgs(ToolArgs):
    line_id: str = Field(pattern=LINE_ID, description="Mã dây chuyền, vd L-1")
    shift_id: str = Field(pattern=SHIFT_ID, description="Mã ca người dùng nói, vd CA-1")


class BookingArgs(LineShiftArgs):
    machine_id: str = Field(pattern=MACHINE_ID, description="Mã máy muốn đặt, vd M2")


# --- Đọc và kiểm tra --------------------------------------------------------

def load_line(db: Session, line_id: str) -> ProductionLine:
    """Raises: ToolError line_not_found."""
    line = db.get(ProductionLine, line_id)
    if line is None:
        raise ToolError("line_not_found", f"Không có dây chuyền {line_id} trong hệ thống")
    return line


def load_shift(db: Session, line_id: str, shift_id: str) -> Shift:
    """Raises: ToolError line_not_found, shift_not_found, shift_not_on_line."""
    load_line(db, line_id)
    shift = db.get(Shift, shift_id)
    if shift is None:
        raise ToolError("shift_not_found", f"Không có ca {shift_id} trong hệ thống")
    if shift.line_id != line_id:
        raise ToolError("shift_not_on_line", f"Ca {shift_id} thuộc dây chuyền {shift.line_id}, không phải {line_id}")
    return shift


def machine_view(m: Machine, quantities: list[int] | None = None) -> dict:
    view = {"machine_id": m.id, "name": m.name, "rate_per_hour": m.rate_per_hour, "status": m.status, "version": m.version}
    if quantities:
        view["hours_needed"] = algo.hours_needed(quantities, m.rate_per_hour)
    return view


def machine_snapshot(m: Machine) -> dict:
    """Những gì AI đã thấy về một máy, để so khi tính."""
    return {"version": m.version, "rate_per_hour": m.rate_per_hour, "status": m.status}


def describe(snapshot: dict | None) -> str:
    if snapshot is None:
        return "không còn trong hệ thống"
    status = "rảnh" if snapshot["status"] == AVAILABLE else MACHINE_STATUS.get(snapshot["status"], snapshot["status"])
    return f"{snapshot['rate_per_hour']} sp/giờ, {status}"


def machine_changes(db: Session, line_id: str, seen: dict[str, dict] | None) -> list[dict]:
    """So máy AI đã đọc (get_available_machines) với dữ liệu hiện tại của dây chuyền."""
    if seen is None:
        return []
    current = {m.id: m for m in db.scalars(select(Machine).where(Machine.line_id == line_id))}
    changes = []
    for machine_id, before in seen.items():
        row = current.get(machine_id)
        if row is None or row.version != before["version"]:
            now = machine_snapshot(row) if row else None
            changes.append({"machine_id": machine_id, "before": describe(before), "now": describe(now)})
    for row in current.values():
        if row.id not in seen and row.status == AVAILABLE:
            changes.append({"machine_id": row.id, "before": "chưa có trong danh sách AI đã đọc", "now": describe(machine_snapshot(row))})
    return changes


def sum_text(hours: list[int]) -> str:
    return " + ".join(map(str, hours)) + f" = {sum(hours)} giờ"


def run_calculation(db: Session, line_id: str, shift_id: str, seen_machines: dict[str, dict] | None = None) -> dict:
    """Đọc lại lô, giờ ca, máy rảnh từ database; tìm tốc độ tối thiểu; chọn máy."""
    shift = load_shift(db, line_id, shift_id)
    batch_rows = open_batches(db, line_id)
    machines = available_machines(db, line_id)

    rate = algo.min_required_rate([algo.Batch(b.id, b.quantity) for b in batch_rows], shift.hours_left)
    products = {b.id: b.product for b in batch_rows}
    quantities = [b.quantity for b in rate.work_batches]

    result = {
        "line_id": line_id,
        "shift_id": shift_id,
        "shift_name": shift.name,
        "hours_left": shift.hours_left,
        "status": rate.status,
        "min_rate": rate.min_rate,
        "reason": rate.reason,
        "batches": [{"batch_id": b.id, "product": products[b.id], "quantity": b.quantity} for b in rate.work_batches],
        "zero_batches": [{"batch_id": b.id, "product": products[b.id], "note": "0 sản phẩm, bỏ qua"} for b in rate.zero_batches],
        "check_at_min": None,
        "check_below_min": None,
        "search_steps": [vars(s) for s in rate.steps],
        "chosen_machine": None,
        "fast_enough": [],
        "too_slow": [],
        "data_changed": machine_changes(db, line_id, seen_machines),
        "rule": RULE,
    }
    if rate.status != algo.OK:
        return result

    for key, r in (("check_at_min", rate.min_rate), ("check_below_min", rate.min_rate - 1)):
        if r < 1:
            continue
        per_batch = algo.hours_per_batch(rate.work_batches, r)
        result[key] = {
            "rate": r,
            "hours_per_batch": per_batch,
            "total_hours": sum(per_batch),
            "fits": sum(per_batch) <= shift.hours_left,
            "calculation": sum_text(per_batch),
        }

    pick = algo.pick_machine([algo.Machine(m.id, m.rate_per_hour) for m in machines], rate.min_rate)
    rows = {m.id: m for m in machines}
    result["fast_enough"] = [machine_view(rows[m.id], quantities) for m in pick.fast_enough]
    result["too_slow"] = [machine_view(rows[m.id], quantities) for m in pick.too_slow]
    if pick.chosen:
        result["chosen_machine"] = machine_view(rows[pick.chosen.id], quantities)
        result["reason"] += f"; {pick.chosen.id} là máy rảnh chậm nhất vẫn đạt {rate.min_rate} sp/giờ"
    else:
        result["status"] = algo.NO_MACHINE
        result["reason"] += (
            "; nhưng không có máy nào đang rảnh" if not machines
            else f"; nhưng máy rảnh nhanh nhất chỉ {machines[-1].rate_per_hour} sp/giờ, thiếu công suất"
        )
    return result


def validate_booking(db: Session, line_id: str, shift_id: str, machine_id: str) -> tuple[dict, Machine]:
    """
    Kiểm tra có nên đặt máy này cho ca này không, trên dữ liệu mới nhất.
    Dùng cho cả công cụ tạo đề xuất và bước trưởng ca bấm "Duyệt".

    Raises:
        ToolError: machine_not_found, machine_not_on_line, machine_not_available, no_feasible_rate, machine_too_slow.
    """
    calc = run_calculation(db, line_id, shift_id)
    machine = db.get(Machine, machine_id)
    if machine is None:
        raise ToolError("machine_not_found", f"Không có máy {machine_id} trong hệ thống")
    if machine.line_id != line_id:
        raise ToolError("machine_not_on_line", f"Máy {machine_id} thuộc dây chuyền {machine.line_id}, không phải {line_id}")
    if machine.status != AVAILABLE:
        raise ToolError("machine_not_available", f"Máy {machine_id} {MACHINE_STATUS.get(machine.status, machine.status)}")
    if calc["min_rate"] is None:
        raise ToolError("no_feasible_rate", f"Không đặt máy được: {calc['reason']}", details={"status": calc["status"]})
    if machine.rate_per_hour < calc["min_rate"]:
        raise ToolError(
            "machine_too_slow",
            f"Máy {machine_id} chỉ {machine.rate_per_hour} sp/giờ, cần ít nhất {calc['min_rate']} sp/giờ",
        )
    return calc, machine


# --- Công cụ --------------------------------------------------------------------

def build_tools(ctx: ToolContext) -> list[BaseTool]:
    """Tạo công cụ gắn với database session và run hiện tại."""

    @tool(args_schema=LineArgs)
    def get_open_batches(line_id: str) -> dict:
        """Đọc các lô chưa làm của một dây chuyền và số sản phẩm còn lại của từng lô (từ hệ thống sản xuất)."""
        load_line(ctx.db, line_id)
        rows = open_batches(ctx.db, line_id)
        return {
            "line_id": line_id,
            "count": len(rows),
            "total_quantity": sum(r.quantity for r in rows),
            "batches": [{"batch_id": r.id, "product": r.product, "quantity": r.quantity} for r in rows],
        }

    @tool(args_schema=LineShiftArgs)
    def get_shift_hours(line_id: str, shift_id: str) -> dict:
        """Đọc số giờ còn dùng được trong một ca của dây chuyền (từ lịch ca)."""
        shift = load_shift(ctx.db, line_id, shift_id)
        return {"line_id": line_id, "shift_id": shift.id, "name": shift.name, "hours_left": shift.hours_left}

    @tool(args_schema=LineArgs)
    def get_available_machines(line_id: str) -> dict:
        """Đọc các máy đang rảnh của dây chuyền và tốc độ mỗi máy, đơn vị sản phẩm/giờ (từ danh sách máy)."""
        load_line(ctx.db, line_id)
        rows = available_machines(ctx.db, line_id)
        ctx.seen.setdefault("machines", {})[line_id] = {m.id: machine_snapshot(m) for m in rows}
        return {"line_id": line_id, "count": len(rows), "machines": [machine_view(m) for m in rows]}

    @tool(args_schema=LineShiftArgs)
    def calculate_min_required_rate(line_id: str, shift_id: str) -> dict:
        """Chạy thuật toán tìm tốc độ nguyên nhỏ nhất (sản phẩm/giờ) để làm xong mọi lô trong số giờ còn lại của ca,
        rồi chọn máy rảnh chậm nhất vẫn đạt. Công cụ tự đọc lại lô, giờ ca và máy từ hệ thống.
        Trả phép tính từng lô, các bước tìm kiếm nhị phân, máy đề xuất; báo nếu dữ liệu máy đã đổi so với lúc đọc."""
        return run_calculation(ctx.db, line_id, shift_id, ctx.seen.get("machines", {}).get(line_id))

    @tool(args_schema=BookingArgs)
    def propose_machine_booking(line_id: str, shift_id: str, machine_id: str) -> dict:
        """Tạo đề xuất đặt một máy cho ca, chờ trưởng ca xác nhận. KHÔNG khóa máy, KHÔNG đổi lịch.
        Chỉ gọi khi người dùng yêu cầu đặt/giữ máy."""
        calc, machine = validate_booking(ctx.db, line_id, shift_id, machine_id)
        quantities = [b["quantity"] for b in calc["batches"]]
        hours = algo.hours_needed(quantities, machine.rate_per_hour)
        proposal, created = create_proposal(
            ctx,
            kind=PROPOSAL_KIND,
            target_id=machine.id,
            payload={
                "line_id": line_id,
                "shift_id": shift_id,
                "machine_id": machine.id,
                "machine_version": machine.version,
                "rate_per_hour": machine.rate_per_hour,
                "min_rate": calc["min_rate"],
                "hours_needed": hours,
                "hours_left": calc["hours_left"],
            },
            summary=(
                f"Đặt máy {machine.id} ({machine.rate_per_hour} sp/giờ) cho ca {shift_id} của {line_id}: "
                f"cần {hours}/{calc['hours_left']} giờ, tốc độ tối thiểu {calc['min_rate']} sp/giờ"
            ),
        )
        chosen = calc["chosen_machine"]["machine_id"] if calc["chosen_machine"] else None
        return {**proposal_view(proposal, created), "is_algorithm_choice": chosen == machine.id, "algorithm_choice": chosen}

    return [
        with_kind(get_open_batches, "read"),
        with_kind(get_shift_hours, "read"),
        with_kind(get_available_machines, "read"),
        with_kind(calculate_min_required_rate, "algorithm"),
        with_kind(propose_machine_booking, "action"),
    ]
