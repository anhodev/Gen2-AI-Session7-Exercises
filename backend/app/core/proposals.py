"""Đề xuất chờ duyệt, dùng chung cho các bài.

Công cụ loại action chỉ gọi create_proposal: lưu một bản nháp, không thay đổi dữ liệu thật.
Chỉ người duyệt (qua endpoint, không phải model) mới duyệt hoặc từ chối được.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .entities import Proposal, now_utc
from .tools import ToolContext

PENDING = "pending_approval"
APPROVED = "approved"
REJECTED = "rejected"


class ProposalNotFoundError(Exception):
    pass


class ProposalStateError(Exception):
    """Đề xuất đã được duyệt hoặc từ chối trước đó."""


class ProposalConflict(Exception):
    """Dữ liệu đã đổi kể từ lúc tạo đề xuất, không duyệt được nữa."""


def create_proposal(ctx: ToolContext, kind: str, target_id: str, payload: dict, summary: str) -> tuple[Proposal, bool]:
    """
    Tạo đề xuất chờ duyệt. Nếu đã có đề xuất y hệt đang chờ thì dùng lại, không tạo trùng.

    Args:
        ctx (ToolContext): Bài, run đang chạy và database session.
        kind (str): Loại đề xuất, vd "invoice_match".
        target_id (str): Đối tượng được đề xuất, vd "I-77".
        payload (dict): Nội dung đề xuất, vd {"transfer_ids": ["P1", "P2"]}.
        summary (str): Một câu mô tả cho người duyệt.

    Returns:
        tuple[Proposal, bool]: Đề xuất, và True nếu vừa tạo mới.
    """
    existing = ctx.db.scalars(
        select(Proposal).where(
            Proposal.module == ctx.module,
            Proposal.kind == kind,
            Proposal.target_id == target_id,
            Proposal.status == PENDING,
        )
    ).all()
    for proposal in existing:
        if proposal.payload == payload:
            return proposal, False

    proposal = Proposal(
        module=ctx.module, kind=kind, target_id=target_id, payload=payload, summary=summary,
        status=PENDING, run_id=ctx.run_id, created_at=now_utc(),
    )
    ctx.db.add(proposal)
    ctx.db.commit()
    ctx.db.refresh(proposal)
    return proposal, True


def proposal_view(proposal: Proposal, created: bool) -> dict:
    """Kết quả công cụ trả cho model sau khi tạo đề xuất."""
    return {
        "proposal_id": proposal.id,
        "status": proposal.status,
        "created": created,
        "summary": proposal.summary,
        "note": "Đây chỉ là đề xuất. Chưa thay đổi dữ liệu, cần người có quyền duyệt.",
    }


def decide(
    db: Session,
    proposal_id: int,
    action: str,
    reviewer: str,
    note: str | None,
    handler: Callable[[Session, Proposal], dict] | None,
) -> Proposal:
    """
    Duyệt hoặc từ chối một đề xuất.

    Args:
        db (Session): Database session.
        proposal_id (int): Mã đề xuất.
        action (str): "approve" hoặc "reject".
        reviewer (str): Tên người duyệt.
        note (str | None): Ghi chú.
        handler (Callable | None): Hàm của bài, chạy khi duyệt: kiểm tra lại dữ liệu mới nhất
            rồi thay đổi. Không có hàm thì chỉ ghi nhận quyết định.

    Raises:
        ProposalNotFoundError: Không có đề xuất.
        ProposalStateError: Đề xuất không còn chờ duyệt.
        ProposalConflict: Dữ liệu đã đổi, không duyệt được. Đề xuất vẫn giữ trạng thái chờ.

    Returns:
        Proposal: Đề xuất sau khi quyết định.
    """
    proposal = db.get(Proposal, proposal_id)
    if proposal is None:
        raise ProposalNotFoundError(f"Không có đề xuất #{proposal_id}")
    if proposal.status != PENDING:
        raise ProposalStateError(f"Đề xuất #{proposal_id} đã ở trạng thái {proposal.status}")

    result: dict = {}
    if action == "approve":
        if handler is not None:
            try:
                result = handler(db, proposal)
            except ProposalConflict:
                db.rollback()
                raise
        proposal.status = APPROVED
    else:
        proposal.status = REJECTED

    proposal.reviewer = reviewer
    proposal.note = note
    proposal.decision_result = result
    proposal.decided_at = now_utc()
    db.commit()
    db.refresh(proposal)
    return proposal


def proposals_of_run(db: Session, run_id: int) -> list[Proposal]:
    return list(db.scalars(select(Proposal).where(Proposal.run_id == run_id).order_by(Proposal.id)))
