"""Bài 01 - Khai báo bài: prompt, công cụ, planner mock, hàm duyệt đề xuất, dữ liệu mẫu."""

from __future__ import annotations

from datetime import timezone

from sqlalchemy.orm import Session

from app.core.agent import AgentSpec
from app.core.entities import Proposal
from app.core.proposals import ProposalConflict
from app.core.tools import ToolError

from .planner import planner
from .store import seed_invoices
from .tools import PROPOSAL_KIND, build_tools, validate_match

SYSTEM_PROMPT = """Bạn là trợ lý kế toán, giúp đối soát các khoản chuyển tiền với hóa đơn. Trả lời bằng tiếng Việt, ngắn gọn.

Quy tắc bắt buộc:
1. Chỉ dùng số liệu do công cụ trả về. Không tự tính, không đoán số tiền hay mã giao dịch.
2. Dùng đúng mã hóa đơn người dùng hỏi (dạng I-77). Nếu người dùng chưa nói mã hóa đơn, hãy hỏi lại và không gọi công cụ.
3. Thứ tự gọi công cụ:
   a. get_open_invoice với mã hóa đơn.
   b. list_unmatched_transfers với customer_id và currency lấy từ kết quả bước a.
   c. find_two_transfer_match với mã hóa đơn. Không tự ghép cặp thay công cụ này.
4. Nếu công cụ trả lỗi (ok=false), nói rõ lỗi cho người dùng. Không bịa kết quả.
5. Nếu find_two_transfer_match trả status=no_match: nói không tìm được cặp và nêu lý do. Không gợi ý cặp "gần đúng".
6. Nếu có cặp: nêu số tiền còn thiếu, hai giao dịch (mã, số tiền, giờ nhận), lý do chọn,
   các giao dịch bị loại (trường excluded) và các cặp khác cũng đủ tiền (trường other_pairs) nếu có.
7. Bạn KHÔNG ghi nhận thanh toán. Nếu người dùng yêu cầu ghi nhận, đối soát luôn hay đánh dấu đã thanh toán:
   gọi propose_invoice_match với đúng hai mã giao dịch find_two_transfer_match trả về, rồi nói rõ đây chỉ là
   đề xuất (kèm mã đề xuất) đang chờ người có quyền duyệt. Hóa đơn chưa được ghi nhận.
8. Viết số tiền đúng như trường amount, amount_due, total mà công cụ trả về."""


def approve_invoice_match(db: Session, proposal: Proposal) -> dict:
    """
    Người duyệt bấm "Duyệt": kiểm tra lại trên dữ liệu mới nhất rồi mới ghi nhận.

    Raises:
        ProposalConflict: Hóa đơn đã thanh toán, số còn thiếu đã đổi, giao dịch đã bị ghép...
    """
    payload = proposal.payload
    try:
        invoice, rows = validate_match(db, payload["invoice_id"], payload["transfer_ids"], timezone.utc)
    except ToolError as exc:
        problems = (exc.details or {}).get("problems", [])
        raise ProposalConflict("Dữ liệu đã đổi, không duyệt được: " + "; ".join([exc.message, *problems]))
    if invoice.amount_due_minor != payload["amount_due_minor"]:
        raise ProposalConflict("Số tiền còn thiếu của hóa đơn đã đổi kể từ lúc tạo đề xuất")

    for row in rows:
        row.status = "matched"
        row.matched_invoice_id = invoice.id
    invoice.amount_due_minor = 0
    invoice.status = "paid"
    return {"invoice_id": invoice.id, "invoice_status": "paid", "matched_transfer_ids": [r.id for r in rows]}


SPEC = AgentSpec(
    module="invoices",
    system_prompt=SYSTEM_PROMPT,
    build_tools=build_tools,
    mock_planner=planner,
    approval_handlers={PROPOSAL_KIND: approve_invoice_match},
    seed=seed_invoices,
)
