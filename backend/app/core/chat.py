"""Nhận một câu hỏi: nối với hội thoại cũ, chạy vòng lặp tool calling, lưu lại toàn bộ."""

from __future__ import annotations

import time
import uuid
from typing import Callable
from zoneinfo import ZoneInfo

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent import AgentSpec, ToolCallRecord, make_model, mentions_ids, run_agent
from .config import Settings
from .entities import ChatRun, ToolCallLog, now_utc
from .tools import ToolContext

HISTORY_TURNS = 6  # số câu hỏi/trả lời cũ gửi kèm cho model


class ConversationNotFoundError(Exception):
    pass


class ConversationMismatchError(Exception):
    pass


def ask(
    db: Session,
    spec: AgentSpec,
    question: str,
    settings: Settings,
    conversation_id: str | None = None,
    model: BaseChatModel | None = None,
    on_tool_done: Callable[[ToolCallRecord], None] | None = None,
) -> ChatRun:
    """
    Trả lời một câu hỏi bằng tool calling và lưu lại câu hỏi, các lần gọi công cụ, câu trả lời.

    Args:
        db (Session): Database session.
        spec (AgentSpec): Bài đang hỏi.
        question (str): Câu hỏi của người dùng.
        settings (Settings): Cấu hình (mock hay model thật, số vòng tối đa).
        conversation_id (str | None, optional): Nối tiếp hội thoại cũ, vd sau khi AI hỏi lại
            line_id. None thì mở hội thoại mới.
        model (BaseChatModel | None, optional): Test truyền model viết sẵn kịch bản.
        on_tool_done (Callable | None, optional): Gọi sau mỗi lần chạy công cụ.

    Raises:
        ConversationNotFoundError: conversation_id không tồn tại.
        ConversationMismatchError: conversation_id thuộc bài khác.

    Returns:
        ChatRun: Run đã lưu, có trạng thái và câu trả lời.
    """
    if conversation_id:
        history = load_history(db, spec.module, conversation_id)
    else:
        conversation_id, history = uuid.uuid4().hex[:12], []

    if model is None:
        model, model_name = make_model(spec, settings)
    else:
        model_name = getattr(model, "model_name", None) or "mock"

    # Lưu run trước để công cụ tạo đề xuất có run_id gắn vào
    run = ChatRun(module=spec.module, conversation_id=conversation_id, question=question, status="running",
                  model=model_name, created_at=now_utc())
    db.add(run)
    db.commit()
    db.refresh(run)

    ctx = ToolContext(db=db, module=spec.module, run_id=run.id, conversation_id=conversation_id,
                      tz=ZoneInfo(settings.app_timezone))

    def after_tool(record: ToolCallRecord) -> None:
        # Công cụ lỗi giữa chừng có thể để session hỏng; rollback để công cụ sau vẫn đọc được
        if not record.ok and record.error and record.error.get("code") == "tool_failed":
            db.rollback()
        if on_tool_done:
            on_tool_done(record)

    start = time.perf_counter()
    outcome = run_agent(
        model,
        spec.build_tools(ctx),
        spec.system_prompt,
        question,
        history=history,
        max_rounds=settings.max_tool_rounds,
        on_tool_done=after_tool,
        require_tool_first=mentions_ids(question, spec.id_patterns),
    )

    # Bỏ thay đổi dở dang (nếu có) trước khi lưu lịch sử
    db.rollback()
    for record in outcome.calls:
        db.add(ToolCallLog(
            run_id=run.id,
            round=record.round,
            tool_call_id=record.tool_call_id,
            name=record.name,
            kind=record.kind,
            args=record.args,
            ok=record.ok,
            result=record.result,
            error=record.error,
            latency_ms=record.latency_ms,
            created_at=now_utc(),
        ))
    run.status = outcome.status
    run.answer = outcome.answer
    run.error = outcome.error
    run.rounds = outcome.rounds
    run.latency_ms = int((time.perf_counter() - start) * 1000)
    run.finished_at = now_utc()
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def load_history(db: Session, module: str, conversation_id: str) -> list[BaseMessage]:
    """
    Câu hỏi và câu trả lời cũ của hội thoại, chỉ phần chữ.

    Không gửi lại kết quả công cụ cũ: dữ liệu có thể đã đổi, model phải gọi công cụ đọc lại.

    Raises:
        ConversationNotFoundError: Không có run nào với conversation_id này.
        ConversationMismatchError: Hội thoại thuộc bài khác.
    """
    runs = db.scalars(
        select(ChatRun).where(ChatRun.conversation_id == conversation_id).order_by(ChatRun.id)
    ).all()
    if not runs:
        raise ConversationNotFoundError(f"Không có hội thoại {conversation_id}")
    if runs[0].module != module:
        raise ConversationMismatchError(f"Hội thoại {conversation_id} thuộc bài {runs[0].module}, không phải {module}")

    messages: list[BaseMessage] = []
    for run in [r for r in runs if r.status == "answered" and r.answer][-HISTORY_TURNS:]:
        messages.append(HumanMessage(content=run.question))
        messages.append(AIMessage(content=run.answer))
    return messages


def tool_calls_of(db: Session, run_id: int) -> list[ToolCallLog]:
    """Các lần gọi công cụ của một run, theo thứ tự đã gọi."""
    return list(db.scalars(select(ToolCallLog).where(ToolCallLog.run_id == run_id).order_by(ToolCallLog.id)))
