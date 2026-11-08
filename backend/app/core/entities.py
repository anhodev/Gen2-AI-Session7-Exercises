"""Bảng dùng chung cho cả 4 bài.

- chat_runs:  mỗi câu hỏi của người dùng là một run (câu hỏi, câu trả lời, trạng thái).
- tool_calls: từng lần model gọi công cụ trong run (tên, tham số, kết quả hoặc lỗi).
- proposals:  đề xuất do công cụ tạo ra, chờ người có quyền duyệt. Không tự thay đổi dữ liệu.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def now_utc() -> datetime:
    """
    Lấy thời điểm hiện tại theo UTC.

    Returns:
        datetime: Thời điểm hiện tại, có múi giờ UTC.
    """
    return datetime.now(timezone.utc)


class ChatRun(Base):
    __tablename__ = "chat_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    module: Mapped[str] = mapped_column(String(20), index=True)  # invoices, capacity, notifications, incidents
    conversation_id: Mapped[str] = mapped_column(String(32), index=True)  # các câu hỏi nối tiếp nhau
    question: Mapped[str] = mapped_column(Text)

    # running:   đang xử lý
    # answered:  model đã trả lời
    # max_steps: vượt số vòng gọi công cụ cho phép, không có câu trả lời
    # error:     gọi model lỗi (mất mạng, sai key...)
    status: Mapped[str] = mapped_column(String(20), default="running")
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    model: Mapped[str] = mapped_column(String(50))  # tên model, hoặc "mock"
    rounds: Mapped[int] = mapped_column(Integer, default=0)  # số lần gọi model
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ToolCallLog(Base):
    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("chat_runs.id"), index=True)
    round: Mapped[int] = mapped_column(Integer)  # vòng thứ mấy của run
    tool_call_id: Mapped[str] = mapped_column(String(100))  # id model đặt, ToolMessage trả về đúng id này
    name: Mapped[str] = mapped_column(String(100))  # tên model gọi, có thể là tên không có trong danh sách
    kind: Mapped[str] = mapped_column(String(20))  # read, algorithm, action, unknown

    args: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)  # tham số model gửi, giữ nguyên
    ok: Mapped[bool] = mapped_column(Boolean)
    result: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"code", "message"}
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    module: Mapped[str] = mapped_column(String(20), index=True)
    kind: Mapped[str] = mapped_column(String(50))  # vd invoice_match, machine_booking
    target_id: Mapped[str] = mapped_column(String(50), index=True)  # vd I-77
    summary: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON)

    # pending_approval: chờ duyệt; approved: đã duyệt; rejected: bị từ chối
    status: Mapped[str] = mapped_column(String(20), default="pending_approval", index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("chat_runs.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    reviewer: Mapped[str | None] = mapped_column(String(50), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # những gì đã thay đổi khi duyệt
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
