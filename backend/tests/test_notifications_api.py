"""Test luồng chat Bài 03 qua API: model giả lập + SQLite tạm, không cần mạng."""

import pytest
from fastapi.testclient import TestClient

from app.core.chat import ask
from app.core.config import Settings
from app.main import create_app
from app.modules.notifications.agent import SPEC
from app.modules.notifications.entities import Customer

FLOW = ["get_pending_messages", "get_contact_policy", "get_opt_in_status", "build_send_schedule"]


@pytest.fixture
def client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/api.db", mock_llm=True)
    with TestClient(create_app(settings)) as c:
        yield c


def chat(client, question, conversation_id=None):
    response = client.post("/chat", json={"module": "notifications", "question": question, "conversation_id": conversation_id})
    assert response.status_code == 200, response.text
    return response.json()


def tool_names(run):
    return [c["name"] for c in run["tool_calls"]]


def messages(client, campaign_id):
    return {m["message_id"]: m for m in client.get("/notifications/data").json()["messages"] if m["campaign_id"] == campaign_id}


def approve(client, proposal_id):
    return client.post(f"/proposals/{proposal_id}/approve", json={"reviewer": "Trưởng nhóm marketing"})


# --- Ca trong đề ------------------------------------------------------------

def test_exercise_flow(client):
    run = chat(client, "Chiến dịch CP-1 hôm nay nên xếp các tin vào khung giờ nào?")
    assert run["status"] == "answered"
    assert tool_names(run) == FLOW
    # Tin và quy tắc đọc cùng lượt; quyền nhận tin cần mã khách từ lượt trước
    assert [c["round"] for c in run["tool_calls"]] == [1, 1, 2, 3]
    assert run["tool_calls"][2]["args"] == {"customer_ids": ["A", "B"]}
    assert run["tool_calls"][3]["kind"] == "algorithm"

    answer = run["answer"]
    assert "09:00 A1 | 10:00 B1 | 11:00 idle | 12:00 A2 | 13:00 B2 | 14:00 idle | 15:00 A3 | 16:00 B3" in answer
    assert "A ở ô 0, 3, 6; B ở ô 1, 4, 7" in answer
    assert "lịch đề xuất, chưa phải lịch đã gửi" in answer
    assert run["proposals"] == []


# --- Gửi ngay: chỉ tạo đề xuất ----------------------------------------------------

def test_send_now_only_creates_proposal(client):
    run = chat(client, "Gửi ngay các tin của chiến dịch CP-1 giúp tôi")
    assert tool_names(run) == FLOW + ["propose_send_schedule"]
    [proposal] = run["proposals"]
    assert proposal["status"] == "pending_approval"
    assert "không có công cụ gửi tin" in run["answer"] and "Chưa tin nào được gửi" in run["answer"]
    assert all(m["status"] == "pending" for m in messages(client, "CP-1").values())


def test_approve_sets_send_times(client):
    proposal = chat(client, "Chốt lịch CP-1")["proposals"][0]
    response = approve(client, proposal["id"])
    assert response.status_code == 200, response.text
    assert response.json()["decision_result"]["scheduled"] == 6
    assert response.json()["decision_result"]["sent"] == 0

    rows = messages(client, "CP-1")
    assert rows["A1"]["status"] == "scheduled" and rows["A1"]["scheduled_at"] == "2026-11-10 09:00"
    assert rows["B3"]["scheduled_at"] == "2026-11-10 16:00"

    # Đã chốt hết: lần hỏi sau không còn tin để xếp
    assert "Không còn tin nào để xếp" in chat(client, "Xếp lịch CP-1")["answer"]


def test_consent_changed_after_proposal_blocks_approval(client):
    proposal = chat(client, "Chốt lịch CP-1")["proposals"][0]
    assert client.patch("/notifications/customers/B", json={"opt_in": False}).json()["version"] == 2

    response = approve(client, proposal["id"])
    assert response.status_code == 409
    assert "khách B đã đổi" in response.json()["detail"]
    assert messages(client, "CP-1")["A1"]["status"] == "pending"
    pending = client.get("/proposals?module=notifications&status=pending_approval").json()
    assert [p["id"] for p in pending] == [proposal["id"]]


def test_source_down_after_proposal_blocks_approval(client):
    client.patch("/notifications/sources/crm-legacy", json={"available": True})
    proposal = chat(client, "Chốt lịch CP-7")["proposals"][0]
    client.patch("/notifications/sources/crm-legacy", json={"available": False})
    response = approve(client, proposal["id"])
    assert response.status_code == 409 and "không phản hồi" in response.json()["detail"]


def test_reject_changes_nothing(client):
    proposal = chat(client, "Chốt lịch CP-1")["proposals"][0]
    response = client.post(f"/proposals/{proposal['id']}/reject", json={"reviewer": "A", "note": "Để mai"})
    assert response.json()["status"] == "rejected"
    assert all(m["status"] == "pending" for m in messages(client, "CP-1").values())


# --- Dữ liệu đổi giữa một lần chat ---------------------------------------------------

def test_consent_changes_during_chat_is_reported(client):
    """AI đọc quyền nhận tin, ngay sau đó A từ chối; công cụ xếp lịch dùng dữ liệu mới và báo đã đổi."""
    factory = client.app.state.session_factory

    def a_opts_out(record):
        if record.name == "get_opt_in_status":
            with factory() as other:
                a = other.get(Customer, "A")
                a.opt_in, a.version = False, a.version + 1
                other.commit()

    with factory() as db:
        run = ask(db, SPEC, "Xếp lịch CP-1", client.app.state.settings, on_tool_done=a_opts_out)
        answer = run.answer

    assert "A1, A2, A3 của khách A (khách đã từ chối nhận tin)" in answer
    assert "trạng thái đồng ý đã đổi sau khi tôi đọc (A: đã đồng ý → đã từ chối)" in answer


# --- Ca lỗi / biên ---------------------------------------------------------------

@pytest.mark.parametrize("question, expected", [
    ("Xếp lịch gửi cho chiến dịch CP-2", "D1, D2 của khách D (khách đã từ chối nhận tin)"),
    ("Xếp lịch gửi cho chiến dịch CP-2", "R1 của khách R (chưa có bản ghi đồng ý"),
    ("Chiến dịch CP-3 gửi vào giờ nào?", "09:00 F1 | 10:00 idle | 11:00 idle | 12:00 F2"),
    ("Lên lịch gửi CP-4", "13:00 G1 | 13:30 G2 | 14:00 H1"),
    ("Xếp lịch CP-5 giúp tôi", "K ở ô 0, 3; L ở ô 1, 4; M ở ô 2, 5"),
    ("Chiến dịch CP-6 hôm nay gửi kịp hết không?", "Chưa xếp được: N3, N4"),
    ("Chiến dịch CP-6 hôm nay gửi kịp hết không?", "không tự đẩy sang ngày khác"),
    ("Xếp lịch CP-8", "Không còn tin nào để xếp lịch sau khi loại khách chưa đồng ý"),
    ("Xếp lịch gửi CP-99", "Không có chiến dịch CP-99"),
])
def test_edge_cases(client, question, expected):
    assert expected in chat(client, question)["answer"]


def test_read_tool_error_stops_before_schedule(client):
    run = chat(client, "Xếp lịch gửi chiến dịch CP-7")
    assert tool_names(run) == FLOW[:3]
    assert run["tool_calls"][-1]["error"]["code"] == "consent_source_unavailable"
    assert "không thể tự giả định khách đã đồng ý" in run["answer"]


def test_send_now_with_nothing_to_send(client):
    run = chat(client, "Gửi ngay CP-8")
    assert "propose_send_schedule" not in tool_names(run)
    assert "không tạo đề xuất" in run["answer"]


def test_ask_back_when_campaign_missing(client):
    first = chat(client, "Hôm nay nên gửi thông báo lúc nào?")
    assert first["tool_calls"] == [] and "mã chiến dịch" in first["answer"]

    second = chat(client, "CP-1", conversation_id=first["conversation_id"])
    assert tool_names(second) == FLOW


# --- API phụ ----------------------------------------------------------------------

def test_samples_and_data(client):
    assert client.get("/notifications/samples").json()[0]["label"] == "Đề bài: CP-1"
    data = client.get("/notifications/data").json()
    assert len(data["campaigns"]) == 8
    assert {s["source_id"]: s["available"] for s in data["sources"]} == {"crm": True, "crm-legacy": False}
    assert {c["customer_id"]: c["opt_in"] for c in data["customers"]}["R"] == "unknown"


@pytest.mark.parametrize("path, body, status", [
    ("/notifications/customers/A", {}, 422),
    ("/notifications/customers/A", {"opt_in": "maybe"}, 422),
    ("/notifications/customers/A", {"opt_in": True, "hack": 1}, 422),
    ("/notifications/customers/ZZ", {"opt_in": True}, 404),
    ("/notifications/sources/none", {"available": True}, 404),
    ("/notifications/customers/R", {"opt_in": None}, 200),
])
def test_change_validation(client, path, body, status):
    assert client.patch(path, json=body).status_code == status


def test_no_send_endpoint(client):
    paths = {r.path for r in client.app.routes}
    assert not any("send" in p for p in paths if p.startswith("/notifications"))


def test_reset_restores_data_and_closes_pending(client):
    proposal = chat(client, "Chốt lịch CP-1")["proposals"][0]
    client.patch("/notifications/customers/A", json={"opt_in": False})
    assert client.post("/notifications/reset").json()["closed_proposals"] == 1
    assert {c["customer_id"]: c["opt_in"] for c in client.get("/notifications/data").json()["customers"]}["A"] == "yes"
    assert approve(client, proposal["id"]).status_code == 409  # đã bị đóng
