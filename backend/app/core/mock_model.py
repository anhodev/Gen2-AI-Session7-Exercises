"""Model giả lập để chạy app không cần API key.

MockChatModel không gọi OpenAI. Mỗi bài viết một "planner": đọc các tin nhắn hiện có
(câu hỏi, kết quả công cụ đã trả) rồi quyết định gọi công cụ nào tiếp theo, hoặc trả lời.
Model giả lập đi qua đúng vòng lặp bind_tools -> tool_calls -> ToolMessage như model thật.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

Planner = Callable[[list[BaseMessage]], AIMessage]


class MockChatModel(BaseChatModel):
    """Chat model chạy theo planner, dùng cho chế độ mock và test."""

    planner: Planner

    @property
    def _llm_type(self) -> str:
        return "mock"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        message = self.planner(list(messages))
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Sequence[Any], **kwargs) -> "MockChatModel":
        # Planner tự biết tên công cụ của bài, không cần schema
        return self


def scripted(*replies: AIMessage) -> Planner:
    """
    Planner trả lần lượt các câu trả lời viết sẵn. Dùng trong test.

    Raises:
        AssertionError: Model bị gọi nhiều lần hơn số câu trả lời đã viết.
    """
    queue = list(replies)

    def planner(messages: list[BaseMessage]) -> AIMessage:
        assert queue, "Model bị gọi nhiều hơn kịch bản"
        return queue.pop(0)

    return planner


# --- Tạo tin nhắn -----------------------------------------------------------

def call(name: str, **args) -> dict:
    """Một lần gọi công cụ, id ngẫu nhiên giống id OpenAI sinh ra."""
    return {"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:12]}", "type": "tool_call"}


def ask_tools(*calls: dict, content: str = "") -> AIMessage:
    """Model yêu cầu gọi một hoặc nhiều công cụ."""
    return AIMessage(content=content, tool_calls=list(calls))


def answer(text: str) -> AIMessage:
    """Model trả lời, không gọi công cụ nữa."""
    return AIMessage(content=text)


# --- Đọc tin nhắn -----------------------------------------------------------

@dataclass
class ToolOutput:
    """Kết quả một công cụ, đã ghép với lời gọi tương ứng qua tool_call_id."""

    name: str
    args: dict
    ok: bool
    result: Any
    error: dict | None


def current_question(messages: list[BaseMessage]) -> str:
    """Câu hỏi mới nhất của người dùng."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def user_text(messages: list[BaseMessage]) -> str:
    """Toàn bộ câu người dùng đã nói trong hội thoại, để tìm ID nói ở câu trước."""
    return "\n".join(str(m.content) for m in messages if isinstance(m, HumanMessage))


def tool_outputs(messages: list[BaseMessage]) -> list[ToolOutput]:
    """
    Kết quả công cụ trong câu hỏi hiện tại (sau HumanMessage cuối), theo thứ tự trả về.

    Args:
        messages (list[BaseMessage]): Tin nhắn model nhận được.

    Returns:
        list[ToolOutput]: Mỗi ToolMessage ghép với tên và tham số của lời gọi có cùng id.
    """
    start = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
    calls: dict[str, dict] = {}
    outputs: list[ToolOutput] = []
    for message in messages[start + 1:]:
        if isinstance(message, AIMessage):
            calls.update({c["id"]: c for c in message.tool_calls})
        elif isinstance(message, ToolMessage):
            matched = calls.get(message.tool_call_id, {})
            body = json.loads(message.content)
            outputs.append(ToolOutput(
                name=matched.get("name", ""),
                args=matched.get("args", {}),
                ok=body.get("ok", False),
                result=body.get("result"),
                error=body.get("error"),
            ))
    return outputs


def last_output(messages: list[BaseMessage], name: str) -> ToolOutput | None:
    """Kết quả gần nhất của một công cụ trong câu hỏi hiện tại."""
    for output in reversed(tool_outputs(messages)):
        if output.name == name:
            return output
    return None
