"""Một bài giả để test phần dùng chung (vòng lặp, lưu lịch sử, đề xuất) trước khi có 4 bài thật.

Dữ liệu: vài số N-1, N-2... Công cụ đọc số, cộng hai số (thuật toán), đề xuất ghép cặp.
"""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import tool
from pydantic import Field

from app.core.agent import AgentSpec
from app.core.mock_model import answer, ask_tools, call, current_question, last_output, tool_outputs, user_text
from app.core.proposals import ProposalConflict, create_proposal, proposal_view
from app.core.tools import ToolArgs, ToolContext, ToolError, with_kind

NUMBERS = {"N-1": 10, "N-2": 32, "N-3": 7}

ID = r"^N-\d+$"


class ItemArgs(ToolArgs):
    item_id: str = Field(pattern=ID, description="Mã số, vd N-1")


class PairArgs(ToolArgs):
    a_id: str = Field(pattern=ID)
    b_id: str = Field(pattern=ID)


def read_number(item_id: str) -> int:
    if item_id not in NUMBERS:
        raise ToolError("not_found", f"Không có {item_id}")
    return NUMBERS[item_id]


def build_tools(ctx: ToolContext):
    @tool(args_schema=ItemArgs)
    def get_item(item_id: str) -> dict:
        """Đọc một số theo mã."""
        return {"item_id": item_id, "value": read_number(item_id)}

    @tool(args_schema=PairArgs)
    def sum_items(a_id: str, b_id: str) -> dict:
        """Cộng hai số, đọc lại từ dữ liệu."""
        return {"total": read_number(a_id) + read_number(b_id)}

    @tool(args_schema=PairArgs)
    def propose_pair(a_id: str, b_id: str) -> dict:
        """Tạo đề xuất ghép hai số, chờ duyệt."""
        read_number(a_id), read_number(b_id)
        proposal, created = create_proposal(ctx, "demo_pair", a_id, {"ids": [a_id, b_id]}, f"Ghép {a_id} với {b_id}")
        return proposal_view(proposal, created)

    @tool(args_schema=ItemArgs)
    def broken_tool(item_id: str) -> dict:
        """Công cụ luôn lỗi trong code."""
        raise RuntimeError("secret connection string leaked")

    return [
        with_kind(get_item, "read"),
        with_kind(sum_items, "algorithm"),
        with_kind(propose_pair, "action"),
        with_kind(broken_tool, "read"),
    ]


def planner(messages: list[BaseMessage]) -> AIMessage:
    """Planner giả lập: đọc mã trong hội thoại, gọi công cụ theo thứ tự rồi trả lời."""
    question = current_question(messages)
    if "lỗi model" in question:
        raise RuntimeError("model down")
    if "lặp mãi" in question:
        return ask_tools(call("get_item", item_id="N-1"))
    if "hỏng" in question:
        if last_output(messages, "broken_tool") is None:
            return ask_tools(call("broken_tool", item_id="N-1"))
        return answer("Công cụ bị lỗi, chưa có kết quả.")

    ids = re.findall(r"N-\d+", user_text(messages))[-2:]
    if len(ids) < 2:
        return answer("Bạn muốn cộng hai số nào? Hãy cho tôi hai mã, vd N-1 và N-2.")

    done = {o.name for o in tool_outputs(messages)}
    if "get_item" not in done:
        return ask_tools(*(call("get_item", item_id=i) for i in ids))
    if "sum_items" not in done:
        return ask_tools(call("sum_items", a_id=ids[0], b_id=ids[1]))
    if "đề xuất" in question and "propose_pair" not in done:
        return ask_tools(call("propose_pair", a_id=ids[0], b_id=ids[1]))

    total = last_output(messages, "sum_items")
    if not total.ok:
        return answer(f"Không tính được: {total.error['message']}")
    return answer(f"Tổng {ids[0]} + {ids[1]} = {total.result['total']}")


def approve_pair(db, proposal) -> dict:
    missing = [i for i in proposal.payload["ids"] if i not in NUMBERS]
    if missing:
        raise ProposalConflict(f"Dữ liệu đã đổi, không còn {', '.join(missing)}")
    return {"paired": proposal.payload["ids"]}


def make_spec(module: str = "demo") -> AgentSpec:
    return AgentSpec(
        module=module,
        system_prompt="Bạn là trợ lý cộng số. Chỉ dùng số do công cụ trả về.",
        build_tools=build_tools,
        mock_planner=planner,
        approval_handlers={"demo_pair": approve_pair},
    )
