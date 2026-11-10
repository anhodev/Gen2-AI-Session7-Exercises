"""Bài 02 - Khai báo bài: prompt, công cụ, planner mock, hàm duyệt đề xuất, dữ liệu mẫu."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.agent import AgentSpec
from app.core.entities import Proposal, now_utc
from app.core.proposals import ProposalConflict
from app.core.tools import ToolError

from .planner import planner
from .store import seed_capacity
from .tools import LINE_ID, PROPOSAL_KIND, SHIFT_ID, build_tools, validate_booking

SYSTEM_PROMPT = """Bạn là trợ lý cho trưởng ca sản xuất, giúp tính máy cần nhanh cỡ nào để làm xong các lô trong ca. Trả lời bằng tiếng Việt, ngắn gọn.

Quy tắc bắt buộc:
1. Chỉ dùng số liệu do công cụ trả về. Không tự nghĩ ra lô hàng, số giờ, tốc độ máy. Không tự tính nhẩm.
2. Cần cả mã dây chuyền (dạng L-1) và mã ca (dạng CA-1). Thiếu mã nào thì hỏi lại người dùng và không gọi công cụ.
   Câu hỏi đã có mã thì gọi công cụ ngay với đúng mã đó. KHÔNG hỏi xác nhận lại mã, KHÔNG tự kết luận mã sai hay không tồn tại:
   chỉ công cụ mới biết, mã không có thì công cụ sẽ báo lỗi.
3. Gọi get_open_batches, get_shift_hours, get_available_machines để đọc dữ liệu (có thể gọi cùng lúc),
   rồi LUÔN gọi calculate_min_required_rate, kể cả khi không còn lô hay ca đã hết giờ. Tốc độ tối thiểu, máy đề xuất
   và kết luận khả thi hay không phải lấy từ công cụ này.
4. Nếu công cụ trả lỗi (ok=false), nói rõ lỗi cho người dùng. Không bịa kết quả.
5. Theo status của calculate_min_required_rate:
   - ok: nêu tốc độ tối thiểu, phép tính ở tốc độ đó và ở tốc độ thấp hơn 1 (check_at_min, check_below_min),
     máy đề xuất (chosen_machine) và lý do, máy cũng đạt và máy quá chậm.
   - no_machine_fast_enough: nói rõ thiếu công suất, ca CHƯA khả thi. Không gợi ý máy chậm hơn mức cần.
   - impossible_under_rules: giải thích số giờ ít hơn số lô; máy nhanh đến đâu cũng không kịp.
   - no_open_batches: nói không còn lô nào cần làm.
6. Nếu data_changed không rỗng: báo dữ liệu máy đã đổi sau khi đọc và kết quả tính theo dữ liệu mới nhất.
7. Bạn KHÔNG đặt hay khóa máy. Nếu người dùng muốn đặt/giữ máy: gọi propose_machine_booking với máy người dùng nêu
   (nếu không nêu thì dùng chosen_machine), rồi nói rõ đây chỉ là đề xuất (kèm mã đề xuất) chờ trưởng ca xác nhận."""


def approve_machine_booking(db: Session, proposal: Proposal) -> dict:
    """
    Trưởng ca bấm "Duyệt": kiểm tra lại trên dữ liệu mới nhất rồi mới giữ máy cho ca.

    Raises:
        ProposalConflict: Máy đã đổi (tốc độ/trạng thái), không còn rảnh, không còn đủ nhanh...
    """
    p = proposal.payload
    try:
        calc, machine = validate_booking(db, p["line_id"], p["shift_id"], p["machine_id"])
    except ToolError as exc:
        raise ProposalConflict(f"Dữ liệu đã đổi, không duyệt được: {exc.message}")
    if machine.version != p["machine_version"]:
        raise ProposalConflict(
            f"Dữ liệu máy {machine.id} đã đổi kể từ lúc tạo đề xuất "
            f"(phiên bản {p['machine_version']} → {machine.version}). Hãy hỏi lại để tính với dữ liệu mới."
        )

    machine.status = "reserved"
    machine.reserved_shift_id = p["shift_id"]
    machine.version += 1
    machine.updated_at = now_utc()
    return {
        "machine_id": machine.id,
        "machine_status": "reserved",
        "shift_id": p["shift_id"],
        "min_rate": calc["min_rate"],
    }


SPEC = AgentSpec(
    module="capacity",
    system_prompt=SYSTEM_PROMPT,
    build_tools=build_tools,
    mock_planner=planner,
    approval_handlers={PROPOSAL_KIND: approve_machine_booking},
    seed=seed_capacity,
    id_patterns=(LINE_ID, SHIFT_ID),
)
