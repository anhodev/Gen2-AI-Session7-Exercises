"""Test API dùng chung (/chat, /runs, /proposals) với bài giả. Mock model + SQLite tạm."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

from . import demo_agent
from .demo_agent import make_spec


@pytest.fixture
def client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/api.db", mock_llm=True, max_tool_rounds=4)
    app = create_app(settings, agents=[make_spec("demo"), make_spec("other")])
    with TestClient(app) as c:
        yield c


def chat(client, question, module="demo", conversation_id=None, status=200):
    response = client.post("/chat", json={"module": module, "question": question, "conversation_id": conversation_id})
    assert response.status_code == status, response.text
    return response.json()


def decide(client, proposal_id, action, reviewer="Kế toán Lan", status=200):
    response = client.post(f"/proposals/{proposal_id}/{action}", json={"reviewer": reviewer, "note": "ok"})
    assert response.status_code == status, response.text
    return response.json()


# --- Chat ---------------------------------------------------------------------

def test_chat_runs_tools_and_answers(client):
    run = chat(client, "Cộng N-1 và N-2")
    assert run["status"] == "answered"
    assert run["answer"] == "Tổng N-1 + N-2 = 42"
    assert run["model"] == "mock"
    assert [(c["round"], c["name"], c["kind"]) for c in run["tool_calls"]] == [
        (1, "get_item", "read"), (1, "get_item", "read"), (2, "sum_items", "algorithm"),
    ]
    assert run["tool_calls"][2]["result"] == {"total": 42}
    assert run["tool_count"] == 3
    assert run["rounds"] == 3


def test_run_is_saved_and_can_be_read_again(client):
    run = chat(client, "Cộng N-1 và N-3")
    saved = client.get(f"/runs/{run['id']}").json()
    assert saved["question"] == "Cộng N-1 và N-3"
    assert saved["tool_calls"] == run["tool_calls"]
    assert saved["created_at"].endswith("Z") or saved["created_at"].endswith("+00:00")


def test_tool_error_is_saved_and_answer_says_so(client):
    run = chat(client, "Cộng N-1 và N-9")
    sum_call = run["tool_calls"][-1]
    assert sum_call["ok"] is False
    assert sum_call["error"]["code"] == "not_found"
    assert "Không có N-9" in run["answer"]


def test_broken_tool_does_not_break_the_run(client):
    run = chat(client, "Thử công cụ hỏng")
    assert run["status"] == "answered"
    assert run["tool_calls"][0]["error"]["code"] == "tool_failed"
    assert "secret" not in str(run)


def test_model_error_is_saved(client):
    run = chat(client, "lỗi model")
    assert run["status"] == "error"
    assert "RuntimeError" in run["error"]
    assert client.get(f"/runs/{run['id']}").json()["status"] == "error"


def test_max_rounds_from_settings(client):
    run = chat(client, "lặp mãi")
    assert run["status"] == "max_steps"
    assert run["answer"] is None
    assert len(run["tool_calls"]) == 4


# --- Hội thoại nhiều lượt -------------------------------------------------------

def test_ask_back_then_continue_same_conversation(client):
    first = chat(client, "Cộng giúp tôi N-1")
    assert first["tool_calls"] == []
    assert "hai mã" in first["answer"]

    second = chat(client, "với N-2", conversation_id=first["conversation_id"])
    assert second["conversation_id"] == first["conversation_id"]
    assert second["answer"] == "Tổng N-1 + N-2 = 42"


def test_unknown_conversation_is_404(client):
    chat(client, "Cộng N-1 và N-2", conversation_id="0123456789ab", status=404)


def test_conversation_of_another_module_is_rejected(client):
    first = chat(client, "Cộng N-1 và N-2", module="demo")
    chat(client, "tiếp", module="other", conversation_id=first["conversation_id"], status=400)


def test_unknown_module_is_404(client):
    chat(client, "hi", module="sql", status=404)


@pytest.mark.parametrize("question", ["", "   "])
def test_blank_question_is_rejected(client, question):
    chat(client, question, status=422)


# --- Lịch sử ---------------------------------------------------------------------

def test_list_runs_newest_first_with_tool_count(client):
    chat(client, "Cộng N-1 và N-2")
    chat(client, "Cộng giúp tôi N-1")
    chat(client, "Cộng N-1 và N-2", module="other")
    runs = client.get("/runs?module=demo").json()
    assert [r["question"] for r in runs] == ["Cộng giúp tôi N-1", "Cộng N-1 và N-2"]
    assert [r["tool_count"] for r in runs] == [0, 3]


def test_missing_run_is_404(client):
    assert client.get("/runs/999").status_code == 404


# --- Đề xuất chờ duyệt -----------------------------------------------------------

def test_action_tool_only_creates_pending_proposal(client):
    run = chat(client, "Cộng N-1 và N-2 rồi đề xuất ghép luôn")
    [proposal] = run["proposals"]
    assert proposal["status"] == "pending_approval"
    assert proposal["payload"] == {"ids": ["N-1", "N-2"]}
    assert proposal["run_id"] == run["id"]
    assert run["tool_calls"][-1]["kind"] == "action"
    assert run["tool_calls"][-1]["result"]["created"] is True

    pending = client.get("/proposals?module=demo&status=pending_approval").json()
    assert [p["id"] for p in pending] == [proposal["id"]]


def test_same_proposal_is_not_created_twice(client):
    first = chat(client, "Cộng N-1 và N-2 rồi đề xuất")["proposals"][0]
    second = chat(client, "Cộng N-1 và N-2 rồi đề xuất")
    assert second["proposals"] == []  # run thứ hai không tạo đề xuất mới
    assert second["tool_calls"][-1]["result"]["proposal_id"] == first["id"]
    assert second["tool_calls"][-1]["result"]["created"] is False


def test_approve_runs_module_handler(client):
    proposal = chat(client, "Cộng N-1 và N-2, đề xuất")["proposals"][0]
    approved = decide(client, proposal["id"], "approve")
    assert approved["status"] == "approved"
    assert approved["reviewer"] == "Kế toán Lan"
    assert approved["decision_result"] == {"paired": ["N-1", "N-2"]}
    assert approved["decided_at"] is not None


def test_reject_does_not_run_handler(client):
    proposal = chat(client, "Cộng N-1 và N-2, đề xuất")["proposals"][0]
    rejected = decide(client, proposal["id"], "reject")
    assert rejected["status"] == "rejected"
    assert rejected["decision_result"] == {}


def test_decided_proposal_cannot_be_decided_again(client):
    proposal = chat(client, "Cộng N-1 và N-2, đề xuất")["proposals"][0]
    decide(client, proposal["id"], "approve")
    decide(client, proposal["id"], "reject", status=409)
    decide(client, proposal["id"], "approve", status=409)


def test_approve_fails_when_data_changed(client, monkeypatch):
    proposal = chat(client, "Cộng N-1 và N-3, đề xuất")["proposals"][0]
    monkeypatch.delitem(demo_agent.NUMBERS, "N-3")  # dữ liệu đổi sau khi tạo đề xuất
    response = client.post(f"/proposals/{proposal['id']}/approve", json={"reviewer": "Lan"})
    assert response.status_code == 409
    assert "N-3" in response.json()["detail"]
    still = client.get("/proposals?status=pending_approval").json()
    assert [p["id"] for p in still] == [proposal["id"]]


def test_missing_proposal_is_404(client):
    decide(client, 999, "approve", status=404)


def test_reviewer_is_required(client):
    proposal = chat(client, "Cộng N-1 và N-2, đề xuất")["proposals"][0]
    decide(client, proposal["id"], "approve", reviewer="  ", status=422)
