"""Bài 01 - Planner cho chế độ mock: quyết định gọi công cụ nào, theo đúng thứ tự model thật nên làm.

  1. Chưa có mã hóa đơn -> hỏi lại, không gọi công cụ.
  2. get_open_invoice -> lỗi thì dừng, nói rõ lỗi.
  3. list_unmatched_transfers với khách + loại tiền lấy từ hóa đơn.
  4. find_two_transfer_match.
  5. Người dùng muốn ghi nhận và có cặp -> propose_invoice_match (chỉ tạo đề xuất).
  6. Trả lời từ kết quả công cụ.
"""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage, BaseMessage

from app.core.mock_model import ToolOutput, answer, ask_tools, call, current_question, last_output, user_text

INVOICE_RE = re.compile(r"\bI-\d{1,10}\b", re.IGNORECASE)
WANTS_RECORD = re.compile(r"ghi nhận|ghi sổ|đối soát luôn|xác nhận luôn|chốt|đề xuất|đánh dấu.*thanh toán", re.IGNORECASE)


def find_invoice_id(messages: list[BaseMessage]) -> str | None:
    """Mã hóa đơn trong câu hỏi mới nhất; không có thì lấy mã gần nhất trong hội thoại."""
    for text in (current_question(messages), user_text(messages)):
        found = INVOICE_RE.findall(text)
        if found:
            return found[-1].upper()
    return None


def planner(messages: list[BaseMessage]) -> AIMessage:
    invoice_id = find_invoice_id(messages)
    if invoice_id is None:
        return answer("Bạn cho tôi mã hóa đơn cần kiểm tra nhé (ví dụ: I-77). Tôi cần mã để đọc đúng hóa đơn và khách hàng.")

    invoice = last_output(messages, "get_open_invoice")
    if invoice is None:
        return ask_tools(call("get_open_invoice", invoice_id=invoice_id))
    if not invoice.ok:
        return answer(f"Không đối soát được: {invoice.error['message']}.")

    transfers = last_output(messages, "list_unmatched_transfers")
    if transfers is None:
        return ask_tools(call("list_unmatched_transfers",
                              customer_id=invoice.result["customer_id"], currency=invoice.result["currency"]))

    match = last_output(messages, "find_two_transfer_match")
    if match is None:
        return ask_tools(call("find_two_transfer_match", invoice_id=invoice_id))
    if not match.ok:
        return answer(f"Công cụ tìm cặp báo lỗi: {match.error['message']}. Tôi không tự chọn cặp thay.")

    wants_record = bool(WANTS_RECORD.search(current_question(messages)))
    proposal = last_output(messages, "propose_invoice_match")
    if wants_record and match.result["status"] == "matched" and proposal is None:
        ids = [p["transfer_id"] for p in match.result["pair"]]
        return ask_tools(call("propose_invoice_match", invoice_id=invoice_id, transfer_ids=ids))

    return answer(compose_answer(match.result, transfers.result, proposal, wants_record))


def compose_answer(match: dict, transfers: dict, proposal: ToolOutput | None, wants_record: bool) -> str:
    head = f"Hóa đơn {match['invoice_id']} (khách {match['customer_id']}) còn thiếu {match['amount_due']}."
    lines = [head, f"Có {transfers['count']} giao dịch chưa ghép của khách này bằng {match['currency']}."]

    if match["status"] != "matched":
        lines.append(f"Không tìm được hai giao dịch cộng lại đúng số tiền này: {match['reason']}.")
        lines.append("Tôi không chọn cặp gần đúng. Cần kế toán liên hệ khách để kiểm tra lại.")
        if wants_record:
            lines.append("Vì không có cặp hợp lệ nên tôi không tạo đề xuất ghi nhận.")
        return "\n".join(lines)

    a, b = match["pair"]
    lines.append(
        f"Đề xuất đối soát: {a['transfer_id']} ({a['amount']}, nhận lúc {a['received_at'][11:16]}) + "
        f"{b['transfer_id']} ({b['amount']}, nhận lúc {b['received_at'][11:16]}) = {match['total']}."
    )
    lines.append(f"Lý do chọn: {match['reason']}.")
    if match["excluded"]:
        lines.append("Không chọn: " + "; ".join(f"{e['transfer_id']} vì {e['reason']}" for e in match["excluded"]) + ".")
    for other in match["other_pairs"]:
        lines.append(f"{' + '.join(other['transfer_ids'])} cũng đủ tiền nhưng hoàn tất muộn hơn khi quét theo giờ nhận.")

    if proposal is not None:
        if proposal.ok:
            lines.append(
                f"Đã tạo đề xuất #{proposal.result['proposal_id']} chờ kế toán có quyền duyệt. "
                "Hóa đơn CHƯA được ghi nhận đã thanh toán."
            )
        else:
            lines.append(f"Không tạo được đề xuất: {proposal.error['message']}.")
    else:
        lines.append("Đây là đề xuất để kế toán xem, hệ thống chưa ghi nhận thanh toán.")
    return "\n".join(lines)
