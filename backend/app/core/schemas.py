"""Schema request/response dùng chung: chat, lịch sử, đề xuất."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .database import as_utc


class ChatIn(BaseModel):
    module: str = Field(description="Bài đang hỏi: invoices, capacity, notifications, incidents")
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{12}$", description="Nối tiếp hội thoại cũ")

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Câu hỏi không được để trống")
        return v


class UtcModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # đọc thẳng từ object SQLAlchemy


class ToolCallOut(UtcModel):
    round: int
    tool_call_id: str
    name: str
    kind: str
    args: Any
    ok: bool
    result: Any
    error: dict | None
    latency_ms: int


class ProposalOut(UtcModel):
    id: int
    module: str
    kind: str
    target_id: str
    summary: str
    payload: dict
    status: str
    run_id: int | None
    created_at: datetime
    reviewer: str | None
    note: str | None
    decision_result: dict | None
    decided_at: datetime | None

    @field_validator("created_at", "decided_at")
    @classmethod
    def time_must_have_timezone(cls, v):
        # Database lưu UTC; SQLite trả về không có múi giờ -> gắn UTC để UI hiện đúng
        return as_utc(v)


class RunOut(UtcModel):
    """Một câu hỏi và kết quả, không kèm chi tiết công cụ."""

    id: int
    module: str
    conversation_id: str
    question: str
    status: str
    answer: str | None
    error: str | None
    model: str
    rounds: int
    latency_ms: int
    created_at: datetime
    finished_at: datetime | None
    tool_count: int = 0

    @field_validator("created_at", "finished_at")
    @classmethod
    def time_must_have_timezone(cls, v):
        return as_utc(v)


class RunDetail(RunOut):
    """Một câu hỏi kèm các lần gọi công cụ và đề xuất đã tạo."""

    tool_calls: list[ToolCallOut]
    proposals: list[ProposalOut]


class DecisionIn(BaseModel):
    reviewer: str = Field(min_length=1, max_length=50, description="Tên người duyệt")
    note: str | None = Field(default=None, max_length=500)

    @field_validator("reviewer")
    @classmethod
    def reviewer_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Cần ghi tên người duyệt")
        return v
