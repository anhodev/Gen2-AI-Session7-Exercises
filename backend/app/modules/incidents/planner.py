"""Bài 04 - Planner cho chế độ mock: quyết định gọi công cụ nào, theo đúng thứ tự model thật nên làm.

  1. Thiếu mã sự cố -> hỏi lại, không gọi công cụ.
  2. get_incident. Lỗi thì dừng, nói rõ lỗi.
  3. Gọi cùng lúc get_service_graph và get_customer_facing_services (cần system_id từ sự cố).
  4. trace_impact.
  5. Người dùng muốn ghi nhận vào sự cố -> propose_impact_note (chỉ tạo đề xuất).
  6. Trả lời từ kết quả công cụ. Yêu cầu khởi động lại/sửa dịch vụ -> giải thích bài này chỉ phân tích.
"""

from __future__ import annotations

import re
from datetime import datetime

from langchain_core.messages import AIMessage, BaseMessage

from app.core.mock_model import ToolOutput, answer, ask_tools, call, current_question, last_output, user_text

INCIDENT_RE = re.compile(r"\bINC-\d{1,10}\b", re.IGNORECASE)
WANTS_NOTE = re.compile(r"ghi nhận|ghi chú|ghi vào|lưu vào sự cố|cập nhật sự cố", re.IGNORECASE)
WANTS_ACTION = re.compile(r"khởi động lại|restart|reboot|tắt dịch vụ|sửa dịch vụ|rollback", re.IGNORECASE)


def find_incident(messages: list[BaseMessage]) -> str | None:
    """Mã trong câu hỏi mới nhất; không có thì lấy mã gần nhất trong hội thoại."""
    for text in (current_question(messages), user_text(messages)):
        found = INCIDENT_RE.findall(text)
        if found:
            return found[-1].upper()
    return None


def planner(messages: list[BaseMessage]) -> AIMessage:
    incident_id = find_incident(messages)
    if incident_id is None:
        return answer(
            "Bạn cho tôi mã sự cố nhé (ví dụ: INC-9). "
            "Tôi cần mã để đọc đúng dịch vụ bị lỗi và sơ đồ phụ thuộc của hệ thống, không đoán từ tên dịch vụ."
        )

    incident = last_output(messages, "get_incident")
    if incident is None:
        return ask_tools(call("get_incident", incident_id=incident_id))
    if not incident.ok:
        return answer(f"Không phân tích được: {incident.error['message']}.")

    system_id = incident.result["system_id"]
    graph = last_output(messages, "get_service_graph")
    facing = last_output(messages, "get_customer_facing_services")
    if graph is None or facing is None:
        # Hai nguồn độc lập: gọi cùng một lượt
        return ask_tools(
            call("get_service_graph", system_id=system_id),
            call("get_customer_facing_services", system_id=system_id),
        )
    errors = list(dict.fromkeys(o.error["message"] for o in (graph, facing) if not o.ok))
    if errors:
        return answer("Không phân tích được: " + "; ".join(errors) + ".")

    impact = last_output(messages, "trace_impact")
    if impact is None:
        return ask_tools(call("trace_impact", incident_id=incident_id))
    if not impact.ok:
        return answer(f"Công cụ duyệt sơ đồ báo lỗi: {impact.error['message']}. Tôi không tự đoán đường ảnh hưởng.")

    question = current_question(messages)
    wants_note = bool(WANTS_NOTE.search(question))
    proposal = last_output(messages, "propose_impact_note")
    if wants_note and proposal is None:
        return ask_tools(call("propose_impact_note", incident_id=incident_id))

    return answer(compose_answer(incident.result, impact.result, proposal, bool(WANTS_ACTION.search(question))))


def when(iso: str) -> str:
    value = datetime.fromisoformat(iso)
    return value.strftime("%H:%M ngày %d/%m/%Y")


def compose_answer(incident: dict, calc: dict, proposal: ToolOutput | None, wants_action: bool) -> str:
    lines = []
    if wants_action:
        lines.append(
            "Tôi không khởi động lại hay sửa dịch vụ được: bài này chỉ phân tích, không có công cụ thao tác hệ thống. "
            "Việc đó cần người trực vận hành tự làm theo quy trình."
        )
    lines.append(
        f"Sự cố {incident['incident_id']} ({incident['title']}) tại {calc['failed_service']} của hệ thống {calc['system_id']}, "
        f"{incident['status_label']}, bắt đầu {when(incident['started_at'])}. "
        f"Sơ đồ phụ thuộc v{calc['graph_version']} (chụp {when(calc['graph_captured_at'])})."
    )
    if calc["incident_status"] == "resolved":
        lines.append("Sự cố này đã xử lý xong; kết quả dưới đây là phân tích lại theo sơ đồ hiện tại.")

    blocking = [w for w in calc["warnings"] if w["code"] != "graph_version_changed"]
    if calc["status"] == "incomplete_data":
        lines.append("CẢNH BÁO incomplete_data: " + "; ".join(w["message"] for w in blocking) + ".")
        lines.append("Danh sách dưới đây CHƯA chắc đầy đủ, cần cập nhật sơ đồ rồi kiểm tra lại.")

    if not calc["bfs_steps"]:
        lines.append(f"Không duyệt được từ {calc['failed_service']} nên chưa có danh sách ảnh hưởng.")
    elif calc["impacted"]:
        lines.append("Dịch vụ người dùng thấy có thể bị ảnh hưởng (theo số cạnh):")
        lines += [f"- {r['service_id']}: {r['path_text']} ({r['distance']} cạnh)" for r in calc["impacted"]]
    else:
        lines.append(f"Không có dịch vụ người dùng thấy nào có đường đi từ {calc['failed_service']} theo sơ đồ.")

    if calc["not_reached"]:
        lines.append(
            "Không đưa vào danh sách: " + ", ".join(r["service_id"] for r in calc["not_reached"])
            + f" (không có đường đi từ {calc['failed_service']})."
        )
    if calc["duplicate_edges"]:
        dup = ", ".join(f"{e['from']} → {e['to']}" for e in calc["duplicate_edges"])
        lines.append(f"Sơ đồ có cạnh trùng ({dup}), chỉ tính một lần.")
    loops = [f"{s['service']} → {x}" for s in calc["bfs_steps"] for x in s["already_seen"]]
    if loops:
        lines.append(f"Có cạnh dẫn về dịch vụ đã duyệt ({', '.join(loops)}); BFS không đi lại nên không lặp vô hạn.")
    if calc["graph_changed"]:
        c = calc["graph_changed"]
        lines.append(f"Lưu ý: sơ đồ đã đổi từ v{c['before']} sang v{c['now']} sau khi tôi đọc; kết quả trên tính theo v{c['now']}.")

    if calc["impacted"]:
        lines.append(calc["note"])
    if proposal is not None:
        if proposal.ok:
            lines.append(
                f"Đã tạo đề xuất #{proposal.result['proposal_id']} ghi kết quả này vào sự cố, chờ người trực duyệt. Chưa ghi gì vào sự cố."
            )
        else:
            lines.append(f"Không tạo được đề xuất: {proposal.error['message']}.")
    return "\n".join(lines)
