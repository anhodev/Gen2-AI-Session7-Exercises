"""Test vòng lặp tool calling (core/agent.py). Không gọi model thật, không cần database."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.core.agent import run_agent
from app.core.mock_model import MockChatModel, answer, ask_tools, call, scripted, tool_outputs
from app.core.tools import ToolArgs, ToolError, kind_of, with_kind


class InvoiceArgs(ToolArgs):
    invoice_id: str = Field(pattern=r"^I-\d+$")


@tool(args_schema=InvoiceArgs)
def get_invoice(invoice_id: str) -> dict:
    """Đọc hóa đơn."""
    if invoice_id == "I-0":
        raise ToolError("invoice_not_found", "Không có hóa đơn I-0")
    if invoice_id == "I-500":
        raise RuntimeError("password=abc")
    return {"invoice_id": invoice_id, "amount_due_minor": 1500000}


TOOLS = [with_kind(get_invoice, "read")]


class Recorder:
    """Model kịch bản, ghi lại tin nhắn nhận được ở mỗi lần gọi."""

    def __init__(self, *replies: AIMessage):
        self.seen: list[list] = []
        plan = scripted(*replies)

        def planner(messages):
            self.seen.append(messages)
            return plan(messages)

        self.model = MockChatModel(planner=planner)


def run(*replies: AIMessage, max_rounds: int = 6, **kwargs):
    recorder = Recorder(*replies)
    outcome = run_agent(recorder.model, TOOLS, "system", "Kiểm tra hóa đơn I-77", max_rounds=max_rounds, **kwargs)
    return outcome, recorder


def body(message: ToolMessage) -> dict:
    return json.loads(message.content)


# --- Ca thường --------------------------------------------------------------

def test_answer_without_tools():
    outcome, recorder = run(answer("Xin chào"))
    assert outcome.status == "answered"
    assert outcome.answer == "Xin chào"
    assert outcome.calls == []
    first = recorder.seen[0]
    assert isinstance(first[0], SystemMessage) and isinstance(first[-1], HumanMessage)


def test_tool_result_goes_back_with_same_tool_call_id():
    c = call("get_invoice", invoice_id="I-77")
    outcome, recorder = run(ask_tools(c), answer("Còn thiếu 1.500.000 VND"))

    assert outcome.status == "answered"
    assert outcome.rounds == 2
    [record] = outcome.calls
    assert record.ok and record.kind == "read" and record.round == 1
    assert record.result == {"invoice_id": "I-77", "amount_due_minor": 1500000}

    tool_message = recorder.seen[1][-1]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.tool_call_id == c["id"]
    assert body(tool_message) == {"ok": True, "result": record.result}


def test_two_calls_in_one_reply_keep_their_ids_in_order():
    a, b = call("get_invoice", invoice_id="I-1"), call("get_invoice", invoice_id="I-2")
    outcome, recorder = run(ask_tools(a, b), answer("xong"))
    tool_messages = [m for m in recorder.seen[1] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in tool_messages] == [a["id"], b["id"]]
    assert [o.args["invoice_id"] for o in tool_outputs(recorder.seen[1])] == ["I-1", "I-2"]


def test_history_is_sent_before_new_question():
    history = [HumanMessage(content="Hóa đơn nào?"), AIMessage(content="Bạn cho mã hóa đơn nhé")]
    _, recorder = run(answer("ok"), history=history)
    sent = recorder.seen[0]
    assert sent[1:3] == history
    assert sent[-1].content == "Kiểm tra hóa đơn I-77"


def test_on_tool_done_called_after_each_tool():
    seen = []
    run(ask_tools(call("get_invoice", invoice_id="I-1")), answer("ok"), on_tool_done=seen.append)
    assert [r.name for r in seen] == ["get_invoice"]


# --- Model gọi sai: backend không chạy, báo lỗi cho model ---------------------

def test_unknown_tool_is_not_run():
    outcome, recorder = run(ask_tools(call("run_sql", query="DELETE FROM invoices")), answer("Không làm được"))
    [record] = outcome.calls
    assert not record.ok and record.kind == "unknown"
    assert record.error["code"] == "tool_not_allowed"
    assert "get_invoice" in record.error["message"]
    assert body(recorder.seen[1][-1])["ok"] is False
    assert outcome.status == "answered"


@pytest.mark.parametrize("args", [
    {"invoice_id": "77"},                              # sai định dạng
    {"invoice_id": "I-77", "amount_due_minor": 1},     # model tự điền số liệu
    {},                                                # thiếu ô
    {"invoice_id": 77},                                # sai kiểu
])
def test_bad_args_are_rejected(args):
    outcome, _ = run(ask_tools(call("get_invoice", **args)), answer("ok"))
    [record] = outcome.calls
    assert not record.ok
    assert record.error["code"] == "invalid_args"
    assert record.args == args


def test_args_that_are_not_an_object_are_rejected():
    bad = {"name": "get_invoice", "args": "I-77", "id": "call_x", "type": "tool_call"}
    reply = AIMessage(content="", tool_calls=[])
    reply.tool_calls = [bad]
    outcome, _ = run(reply, answer("ok"))
    assert outcome.calls[0].error["code"] == "invalid_args"


def test_invalid_json_args_still_get_a_tool_message():
    reply = AIMessage(content="", invalid_tool_calls=[
        {"name": "get_invoice", "args": "{invoice_id: I-77", "id": "call_bad", "error": "bad json", "type": "invalid_tool_call"},
    ])
    outcome, recorder = run(reply, answer("ok"))
    [record] = outcome.calls
    assert record.error["code"] == "invalid_args"
    tool_message = recorder.seen[1][-1]
    assert tool_message.tool_call_id == "call_bad"


# --- Công cụ báo lỗi -----------------------------------------------------------

def test_business_error_is_passed_to_model():
    outcome, recorder = run(ask_tools(call("get_invoice", invoice_id="I-0")), answer("Không có hóa đơn"))
    [record] = outcome.calls
    assert record.error == {"code": "invoice_not_found", "message": "Không có hóa đơn I-0"}
    assert body(recorder.seen[1][-1])["error"]["code"] == "invoice_not_found"


def test_code_error_does_not_leak_details():
    outcome, recorder = run(ask_tools(call("get_invoice", invoice_id="I-500")), answer("Lỗi"))
    [record] = outcome.calls
    assert record.error["code"] == "tool_failed"
    assert "password" not in json.dumps(record.error)
    assert "password" not in recorder.seen[1][-1].content


# --- Dừng vòng lặp ----------------------------------------------------------

def test_stops_after_max_rounds():
    replies = [ask_tools(call("get_invoice", invoice_id="I-1")) for _ in range(3)]
    outcome, recorder = run(*replies, max_rounds=3)
    assert outcome.status == "max_steps"
    assert outcome.answer is None
    assert "3 vòng" in outcome.error
    assert len(recorder.seen) == 3
    assert len(outcome.calls) == 3


def test_model_error_is_reported():
    def planner(messages):
        raise ConnectionError("network down")

    outcome = run_agent(MockChatModel(planner=planner), TOOLS, "system", "hi")
    assert outcome.status == "error"
    assert "ConnectionError" in outcome.error
    assert outcome.answer is None


def test_empty_reply_is_an_error():
    outcome, _ = run(answer("   "))
    assert outcome.status == "error"


# --- Khai báo công cụ ----------------------------------------------------------

def test_tool_must_declare_strict_args_schema():
    class Loose(BaseModel):
        invoice_id: str

    @tool(args_schema=Loose)
    def loose(invoice_id: str) -> dict:
        """Không chặn ô lạ."""
        return {}

    with pytest.raises(ValueError):
        with_kind(loose, "read")


def test_kind_is_stored_on_tool():
    assert kind_of(get_invoice) == "read"


def test_tool_outputs_only_reads_current_question():
    old_call = call("get_invoice", invoice_id="I-1")
    messages = [
        HumanMessage(content="câu cũ"),
        ask_tools(old_call),
        ToolMessage(content='{"ok": true, "result": 1}', tool_call_id=old_call["id"]),
        HumanMessage(content="câu mới"),
    ]
    assert tool_outputs(messages) == []
