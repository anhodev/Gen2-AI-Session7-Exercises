"""Vòng lặp tool calling dùng chung cho cả 4 bài.

    model.bind_tools(tools)
    lặp tối đa max_rounds vòng:
        model trả lời có tool_calls?
          - không: đó là câu trả lời cuối, dừng.
          - có: với mỗi lời gọi, backend kiểm tra tên + tham số, tự chạy công cụ,
                rồi gửi kết quả về model bằng ToolMessage có đúng tool_call_id.

Model chỉ được chọn công cụ và tham số. Backend quyết định có chạy hay không.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from pydantic import ValidationError
from sqlalchemy.orm import Session

from .config import Settings
from .mock_model import MockChatModel, Planner
from .tools import ToolContext, ToolError, kind_of

ApprovalHandler = Callable[..., dict]


@dataclass(frozen=True)
class AgentSpec:
    """Khai báo một bài: prompt, danh sách công cụ, planner cho chế độ mock."""

    module: str
    system_prompt: str
    build_tools: Callable[[ToolContext], list[BaseTool]]
    mock_planner: Planner
    # Hàm chạy khi người duyệt bấm "Duyệt" một đề xuất, theo loại đề xuất.
    # Hàm kiểm tra lại dữ liệu mới nhất rồi mới thay đổi; lỗi thì raise ProposalConflict.
    approval_handlers: dict[str, ApprovalHandler] = field(default_factory=dict)
    # Nạp dữ liệu mẫu của bài nếu database còn trống, chạy lúc app khởi động
    seed: Callable[[Session], None] | None = None
    # Regex mã mà câu hỏi phải có để tra cứu (vd mã hóa đơn). Câu hỏi có đủ các mã này thì vòng đầu
    # bắt model gọi công cụ: model nhỏ hay hỏi lại "xác nhận mã" dù người dùng đã nói rõ.
    id_patterns: tuple[str, ...] = ()


def mentions_ids(text: str, patterns: Sequence[str]) -> bool:
    """Câu hỏi có đủ mỗi loại mã trong patterns (vd "L-1" và "CA-1") hay không."""
    if not patterns:
        return False
    return all(re.search(rf"(?<![\w-]){p.strip('^$')}(?![\w-])", text) for p in patterns)


@dataclass
class ToolCallRecord:
    """Một lần gọi công cụ, để lưu vào bảng tool_calls."""

    round: int
    tool_call_id: str
    name: str
    kind: str
    args: Any
    ok: bool
    result: Any = None
    error: dict | None = None
    latency_ms: int = 0


@dataclass
class AgentOutcome:
    status: str  # answered, max_steps, error
    answer: str | None
    error: str | None
    rounds: int
    calls: list[ToolCallRecord]
    messages: list[BaseMessage]


def make_model(spec: AgentSpec, settings: Settings) -> tuple[BaseChatModel, str]:
    """
    Chọn model: giả lập nếu chưa có key hoặc MOCK_LLM=true, ngược lại gọi OpenAI.

    Returns:
        tuple[BaseChatModel, str]: Model và tên để ghi vào lịch sử.
    """
    if settings.use_mock:
        return MockChatModel(planner=spec.mock_planner), "mock"

    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
        timeout=30,
        max_retries=1,
    )
    return model, settings.openai_model


def run_agent(
    model: BaseChatModel,
    tools: list[BaseTool],
    system_prompt: str,
    question: str,
    history: Sequence[BaseMessage] = (),
    max_rounds: int = 6,
    on_tool_done: Callable[[ToolCallRecord], None] | None = None,
    require_tool_first: bool = False,
) -> AgentOutcome:
    """
    Cho model gọi công cụ cho tới khi có câu trả lời, tối đa max_rounds vòng.

    Args:
        model (BaseChatModel): Model thật hoặc giả lập.
        tools (list[BaseTool]): Công cụ được phép của bài này.
        system_prompt (str): Hướng dẫn cho model.
        question (str): Câu hỏi mới của người dùng.
        history (Sequence[BaseMessage], optional): Các câu hỏi/trả lời trước trong hội thoại.
        max_rounds (int, optional): Số lần gọi model tối đa. Defaults to 6.
        on_tool_done (Callable | None, optional): Gọi sau mỗi lần chạy công cụ. Test dùng để
            đổi dữ liệu giữa hai lần gọi. Defaults to None.
        require_tool_first (bool, optional): Vòng đầu bắt model gọi ít nhất một công cụ
            (tool_choice="required"), model vẫn tự chọn công cụ nào. Defaults to False.

    Returns:
        AgentOutcome: Trạng thái, câu trả lời, các lần gọi công cụ.
    """
    tools_by_name = {t.name: t for t in tools}
    bound = model.bind_tools(tools)
    first = model.bind_tools(tools, tool_choice="required") if require_tool_first else bound
    messages: list[BaseMessage] = [SystemMessage(content=system_prompt), *history, HumanMessage(content=question)]
    calls: list[ToolCallRecord] = []

    for round_no in range(1, max_rounds + 1):
        try:
            reply = (first if round_no == 1 else bound).invoke(messages)
        except Exception as exc:  # mất mạng, sai key, hết quota...
            error = f"Gọi model thất bại ({type(exc).__name__}): {exc}"
            return AgentOutcome("error", None, error, round_no, calls, messages)
        messages.append(reply)

        pending = list(reply.tool_calls)
        broken = list(getattr(reply, "invalid_tool_calls", []) or [])
        if not pending and not broken:
            text = message_text(reply)
            if not text:
                return AgentOutcome("error", None, "Model không trả lời và cũng không gọi công cụ", round_no, calls, messages)
            return AgentOutcome("answered", text, None, round_no, calls, messages)

        for tool_call in pending:
            record, tool_message = execute_tool_call(tool_call, tools_by_name, round_no)
            calls.append(record)
            messages.append(tool_message)
            if on_tool_done:
                on_tool_done(record)

        # Model gửi tham số không phải JSON: vẫn phải trả ToolMessage cho đúng id,
        # nếu không lần gọi model sau sẽ bị OpenAI từ chối.
        for bad in broken:
            record = ToolCallRecord(
                round=round_no,
                tool_call_id=bad.get("id") or "",
                name=bad.get("name") or "",
                kind="unknown",
                args=bad.get("args"),
                ok=False,
                error={"code": "invalid_args", "message": "Tham số không phải JSON hợp lệ"},
            )
            calls.append(record)
            messages.append(to_tool_message(record))

    error = f"Đã gọi công cụ {max_rounds} vòng mà chưa có câu trả lời. Dừng lại để tránh lặp vô hạn."
    return AgentOutcome("max_steps", None, error, max_rounds, calls, messages)


def execute_tool_call(tool_call: dict, tools_by_name: dict[str, BaseTool], round_no: int) -> tuple[ToolCallRecord, ToolMessage]:
    """
    Kiểm tra và chạy một lời gọi công cụ.

    - Tên không có trong danh sách: không chạy, báo tool_not_allowed.
    - Tham số sai kiểu, sai định dạng, thiếu hoặc thừa ô: không chạy, báo invalid_args.
    - Công cụ báo lỗi nghiệp vụ (ToolError): trả mã lỗi cho model.
    - Lỗi khác trong code: báo tool_failed, không gửi chi tiết lỗi nội bộ cho model.

    Args:
        tool_call (dict): {"name", "args", "id"} lấy từ AIMessage.tool_calls.
        tools_by_name (dict[str, BaseTool]): Công cụ được phép.
        round_no (int): Vòng hiện tại.

    Returns:
        tuple[ToolCallRecord, ToolMessage]: Bản ghi để lưu và tin nhắn gửi lại cho model.
    """
    name = tool_call.get("name") or ""
    args = tool_call.get("args")
    record = ToolCallRecord(round=round_no, tool_call_id=tool_call.get("id") or "", name=name, kind="unknown", args=args, ok=False)

    tool = tools_by_name.get(name)
    if tool is None:
        allowed = ", ".join(sorted(tools_by_name))
        record.error = {"code": "tool_not_allowed", "message": f"Không có công cụ '{name}'. Chỉ được dùng: {allowed}"}
        return record, to_tool_message(record)

    record.kind = kind_of(tool)
    if not isinstance(args, dict):
        record.error = {"code": "invalid_args", "message": "Tham số phải là object JSON"}
        return record, to_tool_message(record)

    start = time.perf_counter()
    try:
        record.result = tool.invoke(args)
        record.ok = True
    except ValidationError as exc:
        record.error = {"code": "invalid_args", "message": describe_validation_error(exc)}
    except ToolError as exc:
        record.error = exc.to_dict()
    except Exception as exc:  # lỗi code hoặc database: ghi tên lỗi, không lộ chi tiết
        record.error = {"code": "tool_failed", "message": f"Công cụ gặp lỗi ({type(exc).__name__}), không có kết quả"}
    record.latency_ms = int((time.perf_counter() - start) * 1000)
    return record, to_tool_message(record)


def to_tool_message(record: ToolCallRecord) -> ToolMessage:
    """Gói kết quả thành ToolMessage, dạng {"ok": true, "result": ...} hoặc {"ok": false, "error": ...}."""
    body = {"ok": True, "result": record.result} if record.ok else {"ok": False, "error": record.error}
    return ToolMessage(
        content=json.dumps(body, ensure_ascii=False, default=str),
        tool_call_id=record.tool_call_id,
        name=record.name,
        status="success" if record.ok else "error",
    )


def describe_validation_error(exc: ValidationError) -> str:
    """'invoice_id: String should match pattern ...; amount: Extra inputs are not permitted'"""
    parts = []
    for err in exc.errors():
        field_name = ".".join(str(p) for p in err["loc"]) or "(tham số)"
        parts.append(f"{field_name}: {err['msg']}")
    return "; ".join(parts)


def message_text(message: AIMessage) -> str:
    """Lấy phần chữ trong câu trả lời (content có thể là chuỗi hoặc danh sách khối)."""
    content = message.content
    if isinstance(content, str):
        return content.strip()
    texts = [b.get("text", "") if isinstance(b, dict) else str(b) for b in content]
    return "".join(texts).strip()
