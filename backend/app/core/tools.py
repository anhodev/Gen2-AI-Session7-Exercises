"""Những thứ dùng chung khi viết công cụ (@tool) cho từng bài.

Mỗi công cụ có một loại (kind):
  - read:      đọc dữ liệu theo ID từ database
  - algorithm: chạy thuật toán, tự đọc lại dữ liệu từ database (không nhận số liệu từ model)
  - action:    tạo đề xuất chờ duyệt, không thay đổi dữ liệu thật
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timezone, tzinfo
from typing import Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

ToolKind = Literal["read", "algorithm", "action"]


class ToolArgs(BaseModel):
    """Lớp cha cho tham số công cụ: không nhận ô lạ ngoài các ô đã khai báo."""

    model_config = ConfigDict(extra="forbid")


class ToolError(Exception):
    """
    Lỗi nghiệp vụ trả về cho model, ví dụ không tìm thấy hóa đơn.

    Khác với lỗi code: lỗi này là kết quả hợp lệ, model cần đọc và nói lại với người dùng.
    """

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def to_dict(self) -> dict:
        data = {"code": self.code, "message": self.message}
        if self.details:
            data["details"] = self.details
        return data


@dataclass
class ToolContext:
    """Thông tin công cụ được dùng khi chạy trong một câu hỏi."""

    db: Session
    module: str
    run_id: int
    conversation_id: str
    tz: tzinfo = timezone.utc  # múi giờ hiển thị giờ trong kết quả công cụ (APP_TIMEZONE)
    # Những gì các công cụ đã đọc trong câu hỏi này, vd phiên bản sơ đồ dịch vụ.
    # Công cụ thuật toán so với dữ liệu mới nhất để biết dữ liệu có đổi giữa chừng không.
    seen: dict = field(default_factory=dict)


def with_kind(tool: BaseTool, kind: ToolKind) -> BaseTool:
    """
    Gắn loại cho công cụ.

    Args:
        tool (BaseTool): Công cụ tạo bằng @tool.
        kind (ToolKind): read, algorithm hoặc action.

    Raises:
        ValueError: Công cụ chưa khai báo args_schema kế thừa ToolArgs.

    Returns:
        BaseTool: Chính công cụ đó.
    """
    schema = tool.args_schema
    if not (isinstance(schema, type) and issubclass(schema, ToolArgs)):
        raise ValueError(f"Công cụ {tool.name} phải khai báo args_schema kế thừa ToolArgs")
    tool.metadata = {**(tool.metadata or {}), "kind": kind}
    return tool


def kind_of(tool: BaseTool) -> str:
    """Loại của công cụ, mặc định read."""
    return (tool.metadata or {}).get("kind", "read")
