"""Test luồng chat Bài 01 qua API: model giả lập + SQLite tạm, không cần mạng."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/api.db", mock_llm=True)
    with TestClient(create_app(settings)) as c:
        yield c


def chat(client, question, conversation_id=None):
    response = client.post("/chat", json={"module": "invoices", "question": question, "conversation_id": conversation_id})
    assert response.status_code == 200, response.text
    return response.json()


def tool_names(run):
    return [c["name"] for c in run["tool_calls"]]


def transfer(client, transfer_id):
    return next(t for t in client.get("/invoices/data").json()["transfers"] if t["transfer_id"] == transfer_id)


def invoice(client, invoice_id):
    return next(i for i in client.get("/invoices/data").json()["invoices"] if i["invoice_id"] == invoice_id)


# --- Ca trong đề ------------------------------------------------------------

def test_exercise_flow(client):
    run = chat(client, "Kiểm tra hóa đơn I-77")
    assert run["status"] == "answered"
    assert tool_names(run) == ["get_open_invoice", "list_unmatched_transfers", "find_two_transfer_match"]
    assert run["tool_calls"][1]["args"] == {"customer_id": "C-12", "currency": "VND"}

    match = run["tool_calls"][2]
    assert match["kind"] == "algorithm"
    assert [p["transfer_id"] for p in match["result"]["pair"]] == ["P1", "P2"]

    answer = run["answer"]
    assert "P1 (900.000 VND, nhận lúc 09:00) + P2 (600.000 VND, nhận lúc 09:05) = 1.500.000 VND" in answer
    assert "P4 vì khác khách hàng" in answer and "P5 vì khác loại tiền" in answer
    assert "P1 + P3 cũng đủ tiền" in answer
    assert run["proposals"] == []


def test_times_are_shown_in_app_timezone(client):
    run = chat(client, "Kiểm tra hóa đơn I-77")
    assert run["tool_calls"][1]["result"]["transfers"][0]["received_at"] == "2026-11-03T09:00:00+07:00"


# --- "Ghi nhận luôn": chỉ tạo đề xuất ----------------------------------------------

def test_record_request_only_creates_proposal(client):
    run = chat(client, "Kiểm tra hóa đơn I-77 và ghi nhận luôn giúp tôi")
    assert tool_names(run)[-1] == "propose_invoice_match"
    [proposal] = run["proposals"]
    assert proposal["status"] == "pending_approval"
    assert proposal["payload"]["transfer_ids"] == ["P1", "P2"]
    assert f"#{proposal['id']}" in run["answer"] and "CHƯA" in run["answer"]

    assert invoice(client, "I-77")["status"] == "open"
    assert transfer(client, "P1")["status"] == "unmatched"


def test_approve_records_payment(client):
    proposal = chat(client, "Kiểm tra I-77, ghi nhận luôn")["proposals"][0]
    response = client.post(f"/proposals/{proposal['id']}/approve", json={"reviewer": "Kế toán trưởng"})
    assert response.status_code == 200, response.text
    assert response.json()["decision_result"] == {
        "invoice_id": "I-77", "invoice_status": "paid", "matched_transfer_ids": ["P1", "P2"],
    }
    assert invoice(client, "I-77")["status"] == "paid"
    assert transfer(client, "P2")["matched_invoice_id"] == "I-77"

    again = chat(client, "Kiểm tra hóa đơn I-77")
    assert again["tool_calls"][0]["error"]["code"] == "invoice_not_open"
    assert "đã thanh toán" in again["answer"]


def test_reset_closes_pending_proposals(client):
    run = chat(client, "Kiểm tra I-77, ghi nhận luôn")
    first = run["proposals"][0]
    assert client.post("/invoices/reset").json()["closed_proposals"] == 1
    closed = client.get(f"/runs/{run['id']}").json()["proposals"][0]
    assert closed["status"] == "rejected" and closed["reviewer"] == "system"

    # Hỏi lại sau khi khôi phục: tạo đề xuất mới, không dùng lại đề xuất đã đóng
    again = chat(client, "Kiểm tra I-77, ghi nhận luôn")["proposals"][0]
    assert again["id"] != first["id"]


def test_two_proposals_for_same_transfer_only_one_can_be_approved(client):
    first = chat(client, "Kiểm tra I-77, ghi nhận luôn")["proposals"][0]
    # Kế toán khác tạo đề xuất P1 + P3 (cũng đủ tiền) trong một hội thoại khác
    from app.core.tools import ToolContext
    from app.modules.invoices.tools import build_tools

    with client.app.state.session_factory() as db:
        ctx = ToolContext(db=db, module="invoices", run_id=None, conversation_id="x")
        propose = {t.name: t for t in build_tools(ctx)}["propose_invoice_match"]
        second_id = propose.invoke({"invoice_id": "I-77", "transfer_ids": ["P1", "P3"]})["proposal_id"]

    assert client.post(f"/proposals/{first['id']}/approve", json={"reviewer": "A"}).status_code == 200
    response = client.post(f"/proposals/{second_id}/approve", json={"reviewer": "B"})
    assert response.status_code == 409
    assert "đã thanh toán" in response.json()["detail"]
    assert transfer(client, "P3")["status"] == "unmatched"


def test_approve_conflict_keeps_proposal_pending(client):
    proposal = chat(client, "Kiểm tra I-77, ghi nhận luôn")["proposals"][0]
    # Có người ghi nhận P2 cho hóa đơn khác trước khi duyệt (mô phỏng bằng cách sửa thẳng database)
    from app.modules.invoices.entities import BankTransfer

    with client.app.state.session_factory() as db:
        db.get(BankTransfer, "P2").status = "matched"
        db.commit()

    response = client.post(f"/proposals/{proposal['id']}/approve", json={"reviewer": "Kế toán trưởng"})
    assert response.status_code == 409
    assert "P2 đã ghép" in response.json()["detail"]
    assert invoice(client, "I-77")["status"] == "open"
    assert transfer(client, "P1")["status"] == "unmatched"
    pending = client.get("/proposals?module=invoices&status=pending_approval").json()
    assert [p["id"] for p in pending] == [proposal["id"]]


# --- Ca lỗi / biên ---------------------------------------------------------------

def test_missing_invoice(client):
    run = chat(client, "Kiểm tra hóa đơn I-99")
    assert tool_names(run) == ["get_open_invoice"]
    assert run["tool_calls"][0]["error"]["code"] == "invoice_not_found"
    assert "Không có hóa đơn I-99" in run["answer"]


def test_paid_invoice(client):
    run = chat(client, "Hai khoản nào trả đủ hóa đơn I-78?")
    assert tool_names(run) == ["get_open_invoice"]
    assert "đã thanh toán" in run["answer"]


def test_no_match_is_said_clearly(client):
    run = chat(client, "Kiểm tra hóa đơn I-79 rồi ghi nhận luôn")
    assert run["tool_calls"][-1]["result"]["status"] == "no_match"
    assert "Không tìm được hai giao dịch" in run["answer"]
    assert "không chọn cặp gần đúng" in run["answer"]
    assert "không tạo đề xuất" in run["answer"]
    assert run["proposals"] == []


@pytest.mark.parametrize("invoice_id, expected", [
    ("I-80", "P30 (500.000 VND"),
    ("I-81", "P41 (100.00 USD"),
])
def test_edge_pairs(client, invoice_id, expected):
    run = chat(client, f"Kiểm tra hóa đơn {invoice_id}")
    assert expected in run["answer"]


def test_single_transfer_does_not_pair_with_itself(client):
    run = chat(client, "Kiểm tra hóa đơn I-82")
    assert "Chỉ có 1 giao dịch hợp lệ" in run["answer"]


def test_ask_back_when_invoice_id_missing(client):
    first = chat(client, "Khách vừa chuyển tiền hai lần, kiểm tra giúp tôi")
    assert first["tool_calls"] == []
    assert "mã hóa đơn" in first["answer"]

    second = chat(client, "Hóa đơn I-77", conversation_id=first["conversation_id"])
    assert tool_names(second) == ["get_open_invoice", "list_unmatched_transfers", "find_two_transfer_match"]


# --- API phụ ----------------------------------------------------------------------

def test_samples_and_data(client):
    questions = client.get("/invoices/samples").json()
    assert questions[0] == {"label": "Đề bài: I-77", "question": "Kiểm tra hóa đơn I-77"}
    data = client.get("/invoices/data").json()
    assert len(data["invoices"]) == 7
    assert data["transfers"][0]["transfer_id"] == "P40"  # sớm nhất


def test_reset_restores_sample_data(client):
    proposal = chat(client, "Kiểm tra I-77, ghi nhận luôn")["proposals"][0]
    client.post(f"/proposals/{proposal['id']}/approve", json={"reviewer": "A"})
    assert invoice(client, "I-77")["status"] == "paid"
    assert client.post("/invoices/reset").json()["status"] == "ok"
    assert invoice(client, "I-77")["status"] == "open"
    assert transfer(client, "P1")["status"] == "unmatched"


def test_run_history_keeps_tool_calls(client):
    run = chat(client, "Kiểm tra hóa đơn I-77")
    listed = client.get("/runs?module=invoices").json()[0]
    assert listed["id"] == run["id"] and listed["tool_count"] == 3
    detail = client.get(f"/runs/{run['id']}").json()
    assert [c["tool_call_id"] for c in detail["tool_calls"]] == [c["tool_call_id"] for c in run["tool_calls"]]
