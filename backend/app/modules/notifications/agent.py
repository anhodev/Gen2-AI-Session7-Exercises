"""Bài 03 - Khai báo bài: prompt, công cụ, planner mock, hàm duyệt đề xuất, dữ liệu mẫu."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.agent import AgentSpec
from app.core.entities import Proposal
from app.core.proposals import ProposalConflict
from app.core.tools import ToolError

from .entities import Notification
from .planner import planner
from .store import PENDING, SCHEDULED, seed_notifications
from .tools import CAMPAIGN_ID, PROPOSAL_KIND, build_tools, run_schedule, schedule_payload

SYSTEM_PROMPT = """Bạn là trợ lý cho đội marketing, giúp xếp lịch gửi thông báo trong ngày để không làm phiền khách. Trả lời bằng tiếng Việt, ngắn gọn.

Quy tắc bắt buộc:
1. Chỉ dùng số liệu do công cụ trả về. Không tự nghĩ ra tin, khách, khung giờ hay trạng thái đồng ý. Không tự xếp lịch.
2. Cần mã chiến dịch (dạng CP-1). Thiếu thì hỏi lại người dùng và không gọi công cụ.
   Câu hỏi đã có mã thì gọi công cụ ngay với đúng mã đó. KHÔNG hỏi xác nhận lại mã, KHÔNG tự kết luận mã sai hay không tồn tại:
   chỉ công cụ mới biết, mã không có thì công cụ sẽ báo lỗi.
3. Gọi get_pending_messages và get_contact_policy (có thể gọi cùng lúc), rồi get_opt_in_status với customer_ids
   lấy từ get_pending_messages, rồi LUÔN gọi build_send_schedule (kể cả khi chỉ có một khách hay khách đã từ chối).
   Lịch, tin bị loại và tin chưa xếp được phải lấy từ build_send_schedule. Đừng dừng sau khi chỉ đọc quy tắc.
4. Nếu công cụ trả lỗi (ok=false), nói rõ lỗi. Nếu không đọc được trạng thái đồng ý thì dừng: KHÔNG gọi build_send_schedule,
   KHÔNG đưa ra lịch nào (kể cả lịch toàn ô idle), không giả định khách đã đồng ý hay chưa đồng ý; chỉ nói chưa đọc được.
5. Khi trả lời: nêu quy tắc (số ô, gap), tin bị loại vì khách chưa đồng ý, lịch từng ô (gồm ô idle),
   ô mỗi khách nhận tin, tin chưa xếp được vì hết giờ (không đẩy sang ngày khác). Nếu data_changed không rỗng
   thì báo trạng thái đồng ý đã đổi sau khi đọc. Luôn nói đây là lịch đề xuất, chưa gửi.
6. Bạn KHÔNG gửi tin; không có công cụ gửi tin. Nếu người dùng yêu cầu "gửi ngay" hoặc chốt lịch: giải thích cần người
   có quyền duyệt, làm đủ bước 3 và trình bày lịch như bước 5, rồi mới gọi propose_send_schedule để tạo đề xuất
   (kèm mã đề xuất), và nói rõ chưa tin nào được gửi."""


def approve_send_schedule(db: Session, proposal: Proposal) -> dict:
    """
    Người có quyền bấm "Duyệt": xếp lại lịch trên dữ liệu mới nhất, chỉ chốt khi lịch không đổi.
    Chốt lịch = ghi giờ gửi cho từng tin. Bài tập không gửi tin thật.

    Raises:
        ProposalConflict: Không đọc được quyền nhận tin, khách đổi trạng thái đồng ý, tin chờ gửi đã đổi...
    """
    p = proposal.payload
    try:
        calc = run_schedule(db, p["campaign_id"])
    except ToolError as exc:
        raise ProposalConflict(f"Không duyệt được: {exc.message}")
    current = schedule_payload(calc)

    changed = sorted(
        c for c in set(p["customer_versions"]) | set(current["customer_versions"])
        if p["customer_versions"].get(c) != current["customer_versions"].get(c)
    )
    if changed:
        raise ProposalConflict(
            f"Trạng thái đồng ý nhận tin của khách {', '.join(changed)} đã đổi kể từ lúc tạo đề xuất. "
            "Hãy hỏi lại để xếp lịch với dữ liệu mới."
        )
    if current != p:
        raise ProposalConflict("Tin chờ gửi hoặc quy tắc liên hệ đã đổi kể từ lúc tạo đề xuất. Hãy hỏi lại để xếp lịch mới.")

    for item in p["schedule"]:
        row = db.get(Notification, item["message_id"])
        if row is None or row.status != PENDING:
            raise ProposalConflict(f"Tin {item['message_id']} không còn chờ gửi")
        row.status = SCHEDULED
        row.scheduled_at = f"{p['send_date']} {item['start']}"
    return {
        "campaign_id": p["campaign_id"],
        "scheduled": len(p["schedule"]),
        "unscheduled": p["unscheduled"],
        "sent": 0,
        "note": "Đã chốt giờ gửi cho từng tin. Bài tập không gửi tin thật.",
    }


SPEC = AgentSpec(
    module="notifications",
    system_prompt=SYSTEM_PROMPT,
    build_tools=build_tools,
    mock_planner=planner,
    approval_handlers={PROPOSAL_KIND: approve_send_schedule},
    seed=seed_notifications,
    id_patterns=(CAMPAIGN_ID,),
)
