"""Endpoint dùng chung: chat, lịch sử xử lý, duyệt đề xuất.

  GET  /health                     App đang dùng mock hay model thật, Supabase hay SQLite.
  POST /chat                       Hỏi một bài. AI gọi công cụ, backend chạy, lưu lại toàn bộ.
  GET  /runs                       Lịch sử câu hỏi, mới nhất trước.
  GET  /runs/{id}                  Một câu hỏi kèm các lần gọi công cụ và đề xuất.
  GET  /proposals                  Đề xuất, lọc theo bài và trạng thái.
  POST /proposals/{id}/approve     Người duyệt đồng ý. Model không gọi được endpoint này.
  POST /proposals/{id}/reject      Người duyệt từ chối.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agent import AgentSpec
from .chat import ConversationMismatchError, ConversationNotFoundError, ask, tool_calls_of
from .config import Settings
from .dependencies import get_app_settings, get_db
from .entities import ChatRun, Proposal, ToolCallLog
from .proposals import (
    ProposalConflict,
    ProposalNotFoundError,
    ProposalStateError,
    decide,
    proposals_of_run,
)
from .schemas import ChatIn, DecisionIn, ProposalOut, RunDetail, RunOut, ToolCallOut

router = APIRouter(tags=["Chung"])


@router.get("/health")
def health(request: Request):
    """
    Kiểm tra app đang chạy và đang dùng model/database nào.

    Returns:
        dict: Trạng thái app.
    """
    settings = request.app.state.settings
    return {
        "status": "ok",
        "llm": "mock" if settings.use_mock else settings.openai_model,
        "database": request.app.state.engine.dialect.name,  # postgresql hoặc sqlite
    }


@router.post("/chat", response_model=RunDetail)
def chat(
    payload: ChatIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
):
    """
    Hỏi một bài bằng lời thường. Model chọn công cụ, backend kiểm tra và chạy công cụ.

    Model lỗi hay vượt số vòng vẫn trả 200, với status "error"/"max_steps" và lý do,
    để giao diện hiện rõ và lịch sử vẫn lưu lại.

    Raises:
        HTTPException: 404 không có bài hoặc không có hội thoại; 400 hội thoại thuộc bài khác.

    Returns:
        RunDetail: Câu trả lời, các lần gọi công cụ, đề xuất đã tạo.
    """
    spec = get_spec(request, payload.module)
    try:
        run = ask(db, spec, payload.question, settings, conversation_id=payload.conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ConversationMismatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return to_run_detail(db, run)


@router.get("/runs", response_model=list[RunOut])
def list_runs(
    module: str | None = None,
    conversation_id: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Lịch sử câu hỏi, mới nhất trước.

    Args:
        module (str | None, optional): Lọc theo bài, vd "invoices".
        conversation_id (str | None, optional): Lọc theo hội thoại.
        limit (int, optional): Số dòng tối đa. Defaults to 20.
    """
    query = select(ChatRun).order_by(ChatRun.id.desc()).limit(limit)
    if module:
        query = query.where(ChatRun.module == module)
    if conversation_id:
        query = query.where(ChatRun.conversation_id == conversation_id)
    runs = db.scalars(query).all()

    counts = dict(db.execute(
        select(ToolCallLog.run_id, func.count())
        .where(ToolCallLog.run_id.in_([r.id for r in runs]))
        .group_by(ToolCallLog.run_id)
    ).all())
    return [RunOut.model_validate(r).model_copy(update={"tool_count": counts.get(r.id, 0)}) for r in runs]


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: int, db: Session = Depends(get_db)):
    """
    Một câu hỏi kèm các lần gọi công cụ (tên, tham số, kết quả hoặc lỗi) và đề xuất.

    Raises:
        HTTPException: 404 nếu không tìm thấy.
    """
    run = db.get(ChatRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy lần xử lý")
    return to_run_detail(db, run)


@router.get("/proposals", response_model=list[ProposalOut])
def list_proposals(
    module: str | None = None,
    status: Literal["pending_approval", "approved", "rejected"] | None = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Đề xuất, mới nhất trước."""
    query = select(Proposal).order_by(Proposal.id.desc()).limit(limit)
    if module:
        query = query.where(Proposal.module == module)
    if status:
        query = query.where(Proposal.status == status)
    return db.scalars(query).all()


@router.post("/proposals/{proposal_id}/approve", response_model=ProposalOut)
def approve_proposal(proposal_id: int, payload: DecisionIn, request: Request, db: Session = Depends(get_db)):
    """
    Người duyệt đồng ý đề xuất. Backend kiểm tra lại dữ liệu mới nhất trước khi thay đổi.

    Raises:
        HTTPException: 404 không có đề xuất; 409 đã quyết định rồi, hoặc dữ liệu đã đổi.
    """
    return decide_proposal(request, db, proposal_id, "approve", payload)


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
def reject_proposal(proposal_id: int, payload: DecisionIn, request: Request, db: Session = Depends(get_db)):
    """
    Người duyệt từ chối đề xuất. Không thay đổi dữ liệu.

    Raises:
        HTTPException: 404 không có đề xuất; 409 đã quyết định rồi.
    """
    return decide_proposal(request, db, proposal_id, "reject", payload)


# --- Hàm phụ ----------------------------------------------------------------

def get_spec(request: Request, module: str) -> AgentSpec:
    """Tìm bài theo tên. Raises HTTPException 404 nếu không có."""
    agents: dict[str, AgentSpec] = request.app.state.agents
    spec = agents.get(module)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Không có bài '{module}'. Có: {', '.join(sorted(agents)) or '(chưa có)'}")
    return spec


def decide_proposal(request: Request, db: Session, proposal_id: int, action: str, payload: DecisionIn) -> Proposal:
    proposal = db.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Không có đề xuất #{proposal_id}")
    spec = request.app.state.agents.get(proposal.module)
    handler = spec.approval_handlers.get(proposal.kind) if spec else None
    try:
        return decide(db, proposal_id, action, payload.reviewer, payload.note, handler)
    except ProposalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ProposalStateError, ProposalConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


def to_run_detail(db: Session, run: ChatRun) -> RunDetail:
    calls = tool_calls_of(db, run.id)
    return RunDetail.model_validate({
        **RunOut.model_validate(run).model_dump(),
        "tool_count": len(calls),
        "tool_calls": [ToolCallOut.model_validate(c) for c in calls],
        "proposals": [ProposalOut.model_validate(p) for p in proposals_of_run(db, run.id)],
    })
