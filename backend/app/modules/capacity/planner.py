"""Bài 02 - Planner cho chế độ mock: quyết định gọi công cụ nào, theo đúng thứ tự model thật nên làm.

  1. Thiếu mã dây chuyền hoặc mã ca -> hỏi lại, không gọi công cụ.
  2. Gọi cùng lúc 3 công cụ đọc: lô, giờ ca, máy rảnh. Lỗi thì dừng, nói rõ lỗi.
  3. calculate_min_required_rate.
  4. Người dùng muốn đặt máy và có tốc độ khả thi -> propose_machine_booking (chỉ tạo đề xuất).
  5. Trả lời từ kết quả công cụ.
"""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage, BaseMessage

from app.core.mock_model import ToolOutput, answer, ask_tools, call, current_question, last_output, user_text

LINE_RE = re.compile(r"\bL-\d{1,10}\b", re.IGNORECASE)
SHIFT_RE = re.compile(r"\bCA-\d{1,10}\b", re.IGNORECASE)
MACHINE_RE = re.compile(r"\bM\d{1,10}\b")
WANTS_BOOKING = re.compile(r"đặt máy|giữ máy|khóa máy|chốt máy|đặt luôn|giữ chỗ|book", re.IGNORECASE)
READ_TOOLS = ("get_open_batches", "get_shift_hours", "get_available_machines")


def find_id(pattern: re.Pattern, messages: list[BaseMessage]) -> str | None:
    """Mã trong câu hỏi mới nhất; không có thì lấy mã gần nhất trong hội thoại."""
    for text in (current_question(messages), user_text(messages)):
        found = pattern.findall(text)
        if found:
            return found[-1].upper()
    return None


def planner(messages: list[BaseMessage]) -> AIMessage:
    line_id, shift_id = find_id(LINE_RE, messages), find_id(SHIFT_RE, messages)
    missing = [name for name, value in (("mã dây chuyền", line_id), ("mã ca", shift_id)) if value is None]
    if missing:
        return answer(
            f"Bạn cho tôi {' và '.join(missing)} nhé (ví dụ: dây chuyền L-1, ca CA-1). "
            "Tôi cần mã để đọc đúng lô hàng, số giờ của ca và máy đang rảnh."
        )

    reads = {name: last_output(messages, name) for name in READ_TOOLS}
    if any(output is None for output in reads.values()):
        # Ba nguồn dữ liệu độc lập: gọi cùng một lượt
        return ask_tools(
            call("get_open_batches", line_id=line_id),
            call("get_shift_hours", line_id=line_id, shift_id=shift_id),
            call("get_available_machines", line_id=line_id),
        )
    errors = list(dict.fromkeys(o.error["message"] for o in reads.values() if not o.ok))
    if errors:
        return answer("Không tính được: " + "; ".join(errors) + ".")

    calc = last_output(messages, "calculate_min_required_rate")
    if calc is None:
        return ask_tools(call("calculate_min_required_rate", line_id=line_id, shift_id=shift_id))
    if not calc.ok:
        return answer(f"Công cụ tính tốc độ báo lỗi: {calc.error['message']}. Tôi không tự tính thay.")

    question = current_question(messages)
    wants_booking = bool(WANTS_BOOKING.search(question))
    booking = last_output(messages, "propose_machine_booking")
    result = calc.result
    if wants_booking and booking is None and result["min_rate"] is not None:
        asked = MACHINE_RE.findall(question)
        machine_id = asked[-1] if asked else (result["chosen_machine"] or {}).get("machine_id")
        if machine_id:
            return ask_tools(call("propose_machine_booking", line_id=line_id, shift_id=shift_id, machine_id=machine_id))

    return answer(compose_answer(result, booking, wants_booking))


def machine_list(machines: list[dict]) -> str:
    return ", ".join(f"{m['machine_id']} ({m['rate_per_hour']})" for m in machines)


def compose_answer(calc: dict, booking: ToolOutput | None, wants_booking: bool) -> str:
    hours = calc["hours_left"]
    lines = [f"Dây chuyền {calc['line_id']}, ca {calc['shift_id']} ({calc['shift_name']}) còn {hours} giờ."]
    if calc["batches"]:
        lines.append(
            f"Có {len(calc['batches'])} lô cần làm: "
            + ", ".join(f"{b['batch_id']} {b['quantity']}" for b in calc["batches"]) + " sản phẩm."
        )
    if calc["zero_batches"]:
        lines.append("Bỏ qua lô 0 sản phẩm: " + ", ".join(b["batch_id"] for b in calc["zero_batches"]) + ".")

    status = calc["status"]
    if status == "no_open_batches":
        lines.append("Không còn lô nào cần làm trong ca này, nên không cần chọn máy.")
    elif status == "impossible_under_rules":
        lines.append(f"Không thể kịp theo quy tắc: {calc['reason']}.")
        lines.append("Cần thêm giờ hoặc chuyển bớt lô sang ca khác.")
    else:
        at, below = calc["check_at_min"], calc["check_below_min"]
        lines.append(f"Tốc độ tối thiểu: {calc['min_rate']} sản phẩm/giờ.")
        lines.append(f"Ở tốc độ {at['rate']}: {at['calculation']}, không vượt {hours} giờ.")
        if below:
            lines.append(f"Ở tốc độ {below['rate']}: {below['calculation']}, vượt {hours} giờ.")
        if status == "ok":
            chosen = calc["chosen_machine"]
            lines.append(
                f"Máy đề xuất: {chosen['machine_id']} ({chosen['rate_per_hour']} sản phẩm/giờ, cần {chosen['hours_needed']} giờ), "
                "là máy rảnh chậm nhất vẫn đạt yêu cầu."
            )
            others = [m for m in calc["fast_enough"] if m["machine_id"] != chosen["machine_id"]]
            if others:
                lines.append(f"Cũng đạt nhưng nhanh hơn mức cần: {machine_list(others)}.")
            if calc["too_slow"]:
                lines.append(f"Quá chậm: {machine_list(calc['too_slow'])}.")
        else:
            slow = f" ({machine_list(calc['too_slow'])})" if calc["too_slow"] else ""
            lines.append(f"Thiếu công suất: không máy rảnh nào đạt {calc['min_rate']} sản phẩm/giờ{slow}.")
            lines.append("Ca này CHƯA khả thi với máy hiện có.")

    if calc["data_changed"]:
        changed = "; ".join(f"{c['machine_id']}: {c['before']} → {c['now']}" for c in calc["data_changed"])
        lines.append(f"Lưu ý: dữ liệu máy đã đổi sau khi tôi đọc ({changed}). Kết quả trên tính theo dữ liệu mới nhất.")

    if booking is not None:
        if booking.ok:
            r = booking.result
            lines.append(f"Đã tạo đề xuất #{r['proposal_id']} chờ trưởng ca xác nhận. Máy CHƯA bị khóa.")
            if not r["is_algorithm_choice"] and r["algorithm_choice"]:
                lines.append(f"Lưu ý: thuật toán chọn {r['algorithm_choice']}; máy bạn chọn nhanh hơn mức cần.")
        else:
            lines.append(f"Không tạo được đề xuất đặt máy: {booking.error['message']}.")
    elif wants_booking:
        lines.append("Vì không có phương án đặt máy hợp lệ nên tôi không tạo đề xuất.")
    elif status == "ok":
        lines.append("Đây là gợi ý để trưởng ca xem, chưa đặt máy.")
    return "\n".join(lines)
