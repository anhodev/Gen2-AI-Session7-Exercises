"""Bài 03 - Planner cho chế độ mock: quyết định gọi công cụ nào, theo đúng thứ tự model thật nên làm.

  1. Thiếu mã chiến dịch -> hỏi lại, không gọi công cụ.
  2. Gọi cùng lúc get_pending_messages và get_contact_policy. Lỗi thì dừng, nói rõ lỗi.
  3. get_opt_in_status với mã khách lấy từ tin chờ gửi. Nguồn đồng ý lỗi thì dừng, không tự giả định.
  4. build_send_schedule.
  5. Người dùng muốn gửi ngay / chốt lịch và có tin xếp được -> propose_send_schedule (chỉ tạo đề xuất).
  6. Trả lời từ kết quả công cụ.
"""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage, BaseMessage

from app.core.mock_model import ToolOutput, answer, ask_tools, call, current_question, last_output, user_text

CAMPAIGN_RE = re.compile(r"\bCP-\d{1,10}\b", re.IGNORECASE)
WANTS_SEND = re.compile(r"gửi ngay|gửi luôn|gửi đi|bấm gửi|send now", re.IGNORECASE)
WANTS_PROPOSAL = re.compile(r"chốt lịch|duyệt lịch|đề xuất lịch|tạo đề xuất|lưu lịch", re.IGNORECASE)


def find_campaign(messages: list[BaseMessage]) -> str | None:
    """Mã trong câu hỏi mới nhất; không có thì lấy mã gần nhất trong hội thoại."""
    for text in (current_question(messages), user_text(messages)):
        found = CAMPAIGN_RE.findall(text)
        if found:
            return found[-1].upper()
    return None


def planner(messages: list[BaseMessage]) -> AIMessage:
    campaign_id = find_campaign(messages)
    if campaign_id is None:
        return answer(
            "Bạn cho tôi mã chiến dịch nhé (ví dụ: CP-1). "
            "Tôi cần mã để đọc đúng các tin chờ gửi, quy tắc liên hệ và trạng thái đồng ý nhận tin."
        )

    pending = last_output(messages, "get_pending_messages")
    policy = last_output(messages, "get_contact_policy")
    if pending is None or policy is None:
        # Hai nguồn độc lập: gọi cùng một lượt
        return ask_tools(
            call("get_pending_messages", campaign_id=campaign_id),
            call("get_contact_policy", campaign_id=campaign_id),
        )
    errors = list(dict.fromkeys(o.error["message"] for o in (pending, policy) if not o.ok))
    if errors:
        return answer("Không xếp lịch được: " + "; ".join(errors) + ".")

    customer_ids = pending.result["customer_ids"]
    opt_in = last_output(messages, "get_opt_in_status")
    if customer_ids and opt_in is None:
        return ask_tools(call("get_opt_in_status", customer_ids=customer_ids))
    if opt_in is not None and not opt_in.ok:
        return answer(
            f"Không xếp lịch được: {opt_in.error['message']}. "
            "Tôi không thể tự giả định khách đã đồng ý nhận tin, nên chưa tạo lịch. "
            "Hãy thử lại khi nguồn dữ liệu hoạt động."
        )

    schedule = last_output(messages, "build_send_schedule")
    if schedule is None:
        return ask_tools(call("build_send_schedule", campaign_id=campaign_id))
    if not schedule.ok:
        return answer(f"Công cụ xếp lịch báo lỗi: {schedule.error['message']}. Tôi không tự xếp thay.")

    question = current_question(messages)
    wants_send = bool(WANTS_SEND.search(question))
    wants_proposal = wants_send or bool(WANTS_PROPOSAL.search(question))
    proposal = last_output(messages, "propose_send_schedule")
    if wants_proposal and proposal is None and schedule.result["scheduled_count"] > 0:
        return ask_tools(call("propose_send_schedule", campaign_id=campaign_id))

    return answer(compose_answer(schedule.result, proposal, wants_send, wants_proposal))


def slot_label(slot: dict) -> str:
    if slot["state"] == "send":
        return f"{slot['start']} {slot['message_id']}"
    return f"{slot['start']} {'idle' if slot['state'] == 'idle' else 'trống'}"


def compose_answer(calc: dict, proposal: ToolOutput | None, wants_send: bool, wants_proposal: bool) -> str:
    policy = calc["policy"]
    lines = [
        f"Chiến dịch {calc['campaign_id']} ({calc['campaign_name']}), ngày {calc['send_date']}: "
        f"{policy['slot_count']} ô ({policy['window']}), mỗi ô tối đa 1 tin, gap = {policy['gap']}."
    ]
    if calc["excluded"]:
        by_customer: dict[str, list[str]] = {}
        for m in calc["excluded"]:
            by_customer.setdefault(f"{m['customer_id']} ({m['reason'].lower()})", []).append(m["message_id"])
        lines.append("Loại trước khi xếp: " + "; ".join(f"{', '.join(ids)} của khách {who}" for who, ids in by_customer.items()) + ".")

    status = calc["status"]
    if status == "no_messages":
        lines.append("Không còn tin nào để xếp lịch" + (" sau khi loại khách chưa đồng ý." if calc["excluded"] else "."))
    else:
        used = [s for s in calc["slots"] if s["state"] != "unused"]
        lines.append("Lịch đề xuất: " + " | ".join(slot_label(s) for s in used) + ".")
        lines.append(
            f"Xếp {calc['scheduled_count']} tin, {calc['idle_count']} ô idle"
            + (f", tin cuối gửi lúc {calc['last_send_time']}" if calc["last_send_time"] else "")
            + (f", {calc['unused_count']} ô cuối để trống" if calc["unused_count"] else "") + "."
        )
        received = [f"{c['customer_id']} ở ô {', '.join(map(str, c['slots']))}" for c in calc["customers"] if c["slots"]]
        if received:
            spacing = f" Không ai nhận hai tin mà ở giữa ít hơn {policy['gap']} ô." if policy["gap"] else ""
            lines.append("Mỗi khách nhận: " + "; ".join(received) + "." + spacing)
        if calc["unscheduled"]:
            lines.append(
                "Chưa xếp được: " + ", ".join(m["message_id"] for m in calc["unscheduled"])
                + " vì hết khung giờ trong ngày. Tôi không tự đẩy sang ngày khác."
            )

    if calc["data_changed"]:
        changed = "; ".join(f"{c['customer_id']}: {c['before']} → {c['now']}" for c in calc["data_changed"])
        lines.append(f"Lưu ý: trạng thái đồng ý đã đổi sau khi tôi đọc ({changed}). Lịch trên tính theo dữ liệu mới nhất.")

    if wants_send:
        lines.append("Tôi không gửi tin được: bài này không có công cụ gửi tin, và việc gửi cần người có quyền duyệt.")
    if proposal is not None:
        if proposal.ok:
            lines.append(
                f"Đã tạo đề xuất #{proposal.result['proposal_id']} chốt lịch này, chờ người có quyền duyệt. Chưa tin nào được gửi."
            )
        else:
            lines.append(f"Không tạo được đề xuất: {proposal.error['message']}.")
    elif wants_proposal:
        lines.append("Vì không có tin nào xếp được nên tôi không tạo đề xuất.")
    elif status != "no_messages":
        lines.append("Đây là lịch đề xuất, chưa phải lịch đã gửi.")
    return "\n".join(lines)
