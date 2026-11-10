"""Test luồng chat Bài 02 qua API: model giả lập + SQLite tạm, không cần mạng."""

import pytest
from fastapi.testclient import TestClient

from app.core.chat import ask
from app.core.config import Settings
from app.main import create_app
from app.modules.capacity.agent import SPEC
from app.modules.capacity.entities import Machine

READS = ["get_open_batches", "get_shift_hours", "get_available_machines"]


@pytest.fixture
def client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/api.db", mock_llm=True)
    with TestClient(create_app(settings)) as c:
        yield c


def chat(client, question, conversation_id=None):
    response = client.post("/chat", json={"module": "capacity", "question": question, "conversation_id": conversation_id})
    assert response.status_code == 200, response.text
    return response.json()


def tool_names(run):
    return [c["name"] for c in run["tool_calls"]]


def machine(client, machine_id):
    return next(m for m in client.get("/capacity/data").json()["machines"] if m["machine_id"] == machine_id)


# --- Ca trong đề ------------------------------------------------------------

def test_exercise_flow(client):
    run = chat(client, "Dây chuyền L-1, ca CA-1: máy nào xử lý xong các lô còn lại trước khi hết ca?")
    assert run["status"] == "answered"
    assert tool_names(run) == READS + ["calculate_min_required_rate"]
    # Ba công cụ đọc gọi cùng một lượt, công cụ tính ở lượt sau
    assert [c["round"] for c in run["tool_calls"]] == [1, 1, 1, 2]
    assert run["tool_calls"][3]["kind"] == "algorithm"
    assert run["tool_calls"][3]["result"]["min_rate"] == 11

    answer = run["answer"]
    assert "Tốc độ tối thiểu: 11 sản phẩm/giờ" in answer
    assert "3 + 1 + 3 + 1 = 8 giờ" in answer and "3 + 2 + 3 + 1 = 9 giờ" in answer
    assert "Máy đề xuất: M2" in answer
    assert "Quá chậm: M1 (8)" in answer
    assert run["proposals"] == []


# --- Đặt máy: chỉ tạo đề xuất ----------------------------------------------------

def test_booking_only_creates_proposal(client):
    run = chat(client, "Dây chuyền L-1 ca CA-1 cần máy nào? Đặt máy luôn giúp tôi")
    assert tool_names(run)[-1] == "propose_machine_booking"
    [proposal] = run["proposals"]
    assert proposal["status"] == "pending_approval" and proposal["payload"]["machine_id"] == "M2"
    assert "CHƯA bị khóa" in run["answer"]
    assert machine(client, "M2")["status"] == "available"


def test_booking_named_machine(client):
    run = chat(client, "L-1 ca CA-1, đặt máy M3 cho tôi")
    assert run["proposals"][0]["payload"]["machine_id"] == "M3"
    assert "thuật toán chọn M2" in run["answer"]


def test_booking_too_slow_machine_is_refused(client):
    run = chat(client, "L-1 ca CA-1, đặt máy M1")
    assert run["tool_calls"][-1]["error"]["code"] == "machine_too_slow"
    assert run["proposals"] == []
    assert "Không tạo được đề xuất" in run["answer"]


def test_approve_reserves_machine(client):
    proposal = chat(client, "L-1 ca CA-1, đặt máy luôn")["proposals"][0]
    response = client.post(f"/proposals/{proposal['id']}/approve", json={"reviewer": "Trưởng ca"})
    assert response.status_code == 200, response.text
    assert response.json()["decision_result"] == {
        "machine_id": "M2", "machine_status": "reserved", "shift_id": "CA-1", "min_rate": 11,
    }
    m2 = machine(client, "M2")
    assert m2["status"] == "reserved" and m2["reserved_shift_id"] == "CA-1"

    # M2 đã được đặt, không còn rảnh: lần hỏi sau chọn M3
    again = chat(client, "L-1 ca CA-1 cần máy nào?")
    assert "Máy đề xuất: M3" in again["answer"]


def test_machine_changed_after_proposal_blocks_approval(client):
    """Dữ liệu máy đổi sau khi AI đọc và tạo đề xuất: không duyệt được, đề xuất vẫn chờ."""
    proposal = chat(client, "L-1 ca CA-1, đặt máy luôn")["proposals"][0]
    assert client.patch("/capacity/machines/M2", json={"rate_per_hour": 13}).json()["version"] == 2

    response = client.post(f"/proposals/{proposal['id']}/approve", json={"reviewer": "Trưởng ca"})
    assert response.status_code == 409
    assert "phiên bản 1 → 2" in response.json()["detail"]
    assert machine(client, "M2")["status"] == "available"
    pending = client.get("/proposals?module=capacity&status=pending_approval").json()
    assert [p["id"] for p in pending] == [proposal["id"]]


def test_machine_too_slow_after_change_blocks_approval(client):
    proposal = chat(client, "L-1 ca CA-1, đặt máy luôn")["proposals"][0]
    client.patch("/capacity/machines/M2", json={"rate_per_hour": 10})
    response = client.post(f"/proposals/{proposal['id']}/approve", json={"reviewer": "Trưởng ca"})
    assert response.status_code == 409
    assert "cần ít nhất 11" in response.json()["detail"]


def test_reject_changes_nothing(client):
    proposal = chat(client, "L-1 ca CA-1, đặt máy luôn")["proposals"][0]
    response = client.post(f"/proposals/{proposal['id']}/reject", json={"reviewer": "Trưởng ca", "note": "Để M2 cho ca sau"})
    assert response.json()["status"] == "rejected"
    assert machine(client, "M2")["status"] == "available"


# --- Dữ liệu đổi giữa một lần chat ---------------------------------------------------

def test_machine_changes_during_chat_is_reported(client):
    """AI đọc danh sách máy, ngay sau đó M2 chậm lại; công cụ tính dùng dữ liệu mới và báo đã đổi."""
    factory = client.app.state.session_factory

    def slow_down_m2(record):
        if record.name == "get_available_machines":
            with factory() as other:
                m2 = other.get(Machine, "M2")
                m2.rate_per_hour, m2.version = 10, m2.version + 1
                other.commit()

    with factory() as db:
        run = ask(db, SPEC, "L-1 ca CA-1 cần máy nào?", client.app.state.settings, on_tool_done=slow_down_m2)
        answer = run.answer

    assert "Máy đề xuất: M3" in answer
    assert "dữ liệu máy đã đổi sau khi tôi đọc (M2: 12 sp/giờ, rảnh → 10 sp/giờ, rảnh)" in answer


# --- Ca lỗi / biên ---------------------------------------------------------------

@pytest.mark.parametrize("question, expected", [
    ("Dây chuyền L-2 ca CA-3 cần máy nhanh cỡ nào?", "Không còn lô nào cần làm"),
    ("Dây chuyền L-3 ca CA-4 cần tốc độ tối thiểu bao nhiêu?", "Bỏ qua lô 0 sản phẩm: B-301"),
    ("Dây chuyền L-3 ca CA-4 cần tốc độ tối thiểu bao nhiêu?", "2 + 2 = 4 giờ, không vượt 4 giờ"),
    ("Dây chuyền L-4 ca CA-5 dùng máy nào cho kịp?", "Thiếu công suất"),
    ("Dây chuyền L-4 ca CA-5 dùng máy nào cho kịp?", "CHƯA khả thi"),
    ("Dây chuyền L-5 ca CA-6 có kịp không?", "Không thể kịp theo quy tắc"),
    ("Dây chuyền L-1 ca CA-2 cần máy nào?", "Ca còn 0 giờ"),
    ("Dây chuyền L-1 ca CA-3 cần máy nào?", "Ca CA-3 thuộc dây chuyền L-2"),
    ("Dây chuyền L-9 ca CA-1 cần máy nào?", "Không có dây chuyền L-9"),
])
def test_edge_cases(client, question, expected):
    assert expected in chat(client, question)["answer"]


def test_no_machine_does_not_book(client):
    run = chat(client, "Dây chuyền L-4 ca CA-5, đặt máy luôn")
    assert "propose_machine_booking" not in tool_names(run)
    assert "không tạo đề xuất" in run["answer"]


def test_ask_back_when_shift_missing(client):
    first = chat(client, "Dây chuyền L-1 cần máy nhanh cỡ nào?")
    assert first["tool_calls"] == []
    assert "mã ca" in first["answer"] and "mã dây chuyền" not in first["answer"]

    second = chat(client, "Ca CA-1", conversation_id=first["conversation_id"])
    assert tool_names(second) == READS + ["calculate_min_required_rate"]
    assert second["tool_calls"][0]["args"] == {"line_id": "L-1"}


def test_ask_back_when_both_missing(client):
    run = chat(client, "Máy nào kịp ca?")
    assert run["tool_calls"] == [] and "mã dây chuyền và mã ca" in run["answer"]


# --- API phụ ----------------------------------------------------------------------

def test_samples_and_data(client):
    questions = client.get("/capacity/samples").json()
    assert questions[0]["label"] == "Đề bài: L-1 ca CA-1"
    data = client.get("/capacity/data").json()
    assert len(data["lines"]) == 5
    assert machine(client, "M4")["status"] == "maintenance"


@pytest.mark.parametrize("body, status", [
    ({}, 400),
    ({"rate_per_hour": 0}, 422),
    ({"status": "reserved"}, 422),
    ({"rate_per_hour": 9, "hack": True}, 422),
])
def test_change_machine_validation(client, body, status):
    assert client.patch("/capacity/machines/M2", json=body).status_code == status


def test_change_unknown_machine(client):
    assert client.patch("/capacity/machines/M404", json={"rate_per_hour": 5}).status_code == 404


def test_reset_restores_data_and_closes_pending(client):
    proposal = chat(client, "L-1 ca CA-1, đặt máy luôn")["proposals"][0]
    client.patch("/capacity/machines/M1", json={"rate_per_hour": 50})
    assert client.post("/capacity/reset").json()["closed_proposals"] == 1
    assert machine(client, "M1")["rate_per_hour"] == 8
    response = client.post(f"/proposals/{proposal['id']}/approve", json={"reviewer": "A"})
    assert response.status_code == 409  # đã bị đóng
