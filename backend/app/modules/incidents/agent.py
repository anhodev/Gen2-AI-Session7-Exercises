"""Bài 04 - Khai báo bài: prompt, công cụ, planner mock, hàm duyệt đề xuất, dữ liệu mẫu."""

from __future__ import annotations

from datetime import timezone

from sqlalchemy.orm import Session

from app.core.agent import AgentSpec
from app.core.entities import Proposal, now_utc
from app.core.proposals import ProposalConflict
from app.core.tools import ToolError

from .entities import ImpactNote
from .planner import planner
from .store import seed_incidents
from .tools import INCIDENT_ID, PROPOSAL_KIND, build_tools, note_payload, run_trace

SYSTEM_PROMPT = """Bạn là trợ lý cho người trực vận hành, giúp xem một sự cố có thể ảnh hưởng tới đâu. Trả lời bằng tiếng Việt, ngắn gọn.

Quy tắc bắt buộc:
1. Chỉ dùng dữ liệu do công cụ trả về. KHÔNG đoán đường ảnh hưởng từ tên dịch vụ. Không tự thêm cạnh hay dịch vụ.
2. Cần mã sự cố (dạng INC-9). Thiếu thì hỏi lại người dùng và không gọi công cụ.
   Câu hỏi đã có mã thì gọi công cụ ngay với đúng mã đó. KHÔNG hỏi xác nhận lại mã, KHÔNG tự kết luận mã sai hay không tồn tại:
   chỉ công cụ mới biết, mã không có thì công cụ sẽ báo lỗi.
3. Gọi get_incident TRƯỚC và chờ kết quả. Sau đó gọi get_service_graph và get_customer_facing_services với system_id
   lấy từ get_incident (hai công cụ này có thể gọi cùng lúc). KHÔNG đoán system_id. Cuối cùng gọi trace_impact.
   get_incident lỗi thì dừng, không gọi tiếp. Danh sách ảnh hưởng và đường đi phải lấy từ trace_impact.
4. Nếu công cụ trả lỗi (ok=false), nói rõ lỗi. Không bịa kết quả.
5. Khi trả lời: nêu trạng thái sự cố, phiên bản sơ đồ, từng dịch vụ người dùng thấy có thể bị ảnh hưởng kèm đường đi
   (path_text) và số cạnh, theo đúng thứ tự công cụ trả về. Nói rõ đây là phần CÓ THỂ bị ảnh hưởng theo sơ đồ,
   không khẳng định đã hỏng. Nêu dịch vụ không có đường đi (not_reached), cạnh trùng, vòng nếu có.
6. Nếu status = incomplete_data: nêu từng cảnh báo và nói danh sách CHƯA chắc đầy đủ. Nếu graph_changed khác null:
   báo sơ đồ đã đổi phiên bản trong lúc xử lý.
7. Bạn KHÔNG khởi động lại, tắt hay sửa dịch vụ; không có công cụ làm việc đó. Nếu người dùng yêu cầu, câu đầu tiên của câu trả lời
   phải nói rõ bạn KHÔNG làm việc đó (không có công cụ), người trực phải tự làm; sau đó mới nêu kết quả phân tích.
   Nếu người dùng muốn ghi nhận kết quả vào sự cố: làm đủ bước 3 rồi gọi propose_impact_note. Không nói "đã ghi nhận":
   nói rõ đây chỉ là đề xuất (kèm mã đề xuất) chờ người trực duyệt."""


def approve_impact_note(db: Session, proposal: Proposal) -> dict:
    """
    Người trực bấm "Duyệt": duyệt lại sơ đồ mới nhất, chỉ ghi chú khi kết quả không đổi.

    Raises:
        ProposalConflict: Sơ đồ đổi phiên bản, sự cố đã đóng, danh sách ảnh hưởng đã khác.
    """
    p = proposal.payload
    try:
        calc = run_trace(db, p["incident_id"], timezone.utc)
    except ToolError as exc:
        raise ProposalConflict(f"Không duyệt được: {exc.message}")
    if calc["graph_version"] != p["graph_version"]:
        raise ProposalConflict(
            f"Sơ đồ đã đổi từ v{p['graph_version']} sang v{calc['graph_version']} kể từ lúc tạo đề xuất. "
            "Hãy hỏi lại để duyệt theo sơ đồ mới."
        )
    if calc["incident_status"] == "resolved":
        raise ProposalConflict(f"Sự cố {p['incident_id']} đã xử lý xong, không ghi thêm.")
    if note_payload(calc) != p:
        raise ProposalConflict("Kết quả duyệt sơ đồ đã khác so với lúc tạo đề xuất. Hãy hỏi lại.")

    note = ImpactNote(
        incident_id=p["incident_id"], graph_version=p["graph_version"], status=p["status"],
        impacted=p["impacted"], created_at=now_utc(),
    )
    db.add(note)
    db.flush()
    return {
        "incident_id": p["incident_id"],
        "note_id": note.id,
        "graph_version": p["graph_version"],
        "impacted": [r["service_id"] for r in p["impacted"]],
        "note": "Đã ghi chú các phần CÓ THỂ bị ảnh hưởng. Không dịch vụ nào bị khởi động lại hay thay đổi.",
    }


SPEC = AgentSpec(
    module="incidents",
    system_prompt=SYSTEM_PROMPT,
    build_tools=build_tools,
    mock_planner=planner,
    approval_handlers={PROPOSAL_KIND: approve_impact_note},
    seed=seed_incidents,
    id_patterns=(INCIDENT_ID,),
)
