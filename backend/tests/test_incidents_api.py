"""Test luồng chat Bài 04 qua API: model giả lập + SQLite tạm, không cần mạng."""

import pytest
from fastapi.testclient import TestClient

from app.core.chat import ask
from app.core.config import Settings
from app.main import create_app
from app.modules.incidents.agent import SPEC
from app.modules.incidents.entities import ServiceSystem

FLOW = ["get_incident", "get_service_graph", "get_customer_facing_services", "trace_impact"]


@pytest.fixture
def client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/api.db", mock_llm=True)
    with TestClient(create_app(settings)) as c:
        yield c


def chat(client, question, conversation_id=None):
    response = client.post("/chat", json={"module": "incidents", "question": question, "conversation_id": conversation_id})
    assert response.status_code == 200, response.text
    return response.json()


def tool_names(run):
    return [c["name"] for c in run["tool_calls"]]


def approve(client, proposal_id):
    return client.post(f"/proposals/{proposal_id}/approve", json={"reviewer": "Người trực"})


# --- Ca trong đề ------------------------------------------------------------

def test_exercise_flow(client):
    run = chat(client, "Sự cố INC-9 có thể ảnh hưởng những phần nào người dùng thấy?")
    assert run["status"] == "answered"
    assert tool_names(run) == FLOW
    # Sơ đồ và danh sách dịch vụ cần system_id từ sự cố nên ở lượt 2, gọi cùng lúc
    assert [c["round"] for c in run["tool_calls"]] == [1, 2, 2, 3]
    assert run["tool_calls"][1]["args"] == {"system_id": "SHOP"}
    assert run["tool_calls"][3]["kind"] == "algorithm"

    answer = run["answer"]
    assert "- Reports: DB → Reports (1 cạnh)\n- MobileApp: DB → Auth → MobileApp (2 cạnh)\n" \
           "- WebStore: DB → Auth → Checkout → WebStore (3 cạnh)" in answer
    assert "Sơ đồ phụ thuộc v7" in answer and "đang điều tra" in answer
    assert "CÓ THỂ bị ảnh hưởng" in answer and "chưa xác nhận" in answer
    assert run["proposals"] == []


# --- Không thao tác hệ thống, chỉ đề xuất ghi chú -----------------------------------------

def test_restart_request_is_explained(client):
    run = chat(client, "Khởi động lại DB để xử lý INC-9 giúp tôi")
    assert tool_names(run) == FLOW and run["proposals"] == []
    assert "không khởi động lại" in run["answer"] and "chỉ phân tích" in run["answer"]


def test_note_only_creates_proposal(client):
    run = chat(client, "Ghi nhận ảnh hưởng của INC-9 vào sự cố giúp tôi")
    assert tool_names(run) == FLOW + ["propose_impact_note"]
    [proposal] = run["proposals"]
    assert proposal["status"] == "pending_approval"
    assert "Chưa ghi gì vào sự cố" in run["answer"]
    assert client.get("/incidents/data").json()["notes"] == []


def test_approve_writes_note(client):
    proposal = chat(client, "Ghi nhận ảnh hưởng của INC-9")["proposals"][0]
    response = approve(client, proposal["id"])
    assert response.status_code == 200, response.text
    result = response.json()["decision_result"]
    assert result["impacted"] == ["Reports", "MobileApp", "WebStore"] and result["graph_version"] == 7
    [note] = client.get("/incidents/data").json()["notes"]
    assert note["incident_id"] == "INC-9" and note["status"] == "ok"


def test_graph_published_after_proposal_blocks_approval(client):
    proposal = chat(client, "Ghi nhận ảnh hưởng của INC-9")["proposals"][0]
    assert client.post("/incidents/systems/SHOP/publish").json() == {"system_id": "SHOP", "before": 7, "current_version": 8}

    response = approve(client, proposal["id"])
    assert response.status_code == 409
    assert "v7 sang v8" in response.json()["detail"]
    assert client.get("/incidents/data").json()["notes"] == []
    pending = client.get("/proposals?module=incidents&status=pending_approval").json()
    assert [p["id"] for p in pending] == [proposal["id"]]


def test_resolved_after_proposal_blocks_approval(client):
    proposal = chat(client, "Ghi nhận ảnh hưởng của INC-9")["proposals"][0]
    client.patch("/incidents/INC-9", json={"status": "resolved"})
    response = approve(client, proposal["id"])
    assert response.status_code == 409 and "đã xử lý xong" in response.json()["detail"]


def test_reject_writes_nothing(client):
    proposal = chat(client, "Ghi nhận ảnh hưởng của INC-9")["proposals"][0]
    response = client.post(f"/proposals/{proposal['id']}/reject", json={"reviewer": "A", "note": "Chờ xác nhận log"})
    assert response.json()["status"] == "rejected"
    assert client.get("/incidents/data").json()["notes"] == []


# --- Sơ đồ đổi phiên bản trong lúc xử lý --------------------------------------------------

def test_graph_changes_during_chat_is_reported(client):
    """AI đọc sơ đồ v7, ngay sau đó v8 được công bố; trace_impact dùng v8 và báo đã đổi."""
    factory = client.app.state.session_factory

    def publish_v8(record):
        if record.name == "get_service_graph":
            with factory() as other:
                other.get(ServiceSystem, "SHOP").current_version = 8
                other.commit()

    with factory() as db:
        run = ask(db, SPEC, "INC-9 ảnh hưởng tới đâu?", client.app.state.settings, on_tool_done=publish_v8)
        answer = run.answer

    assert "- Reports: DB → Cache → Reports (2 cạnh)" in answer
    assert "sơ đồ đã đổi từ v7 sang v8 sau khi tôi đọc" in answer


# --- Ca lỗi / biên ---------------------------------------------------------------

@pytest.mark.parametrize("question, expected", [
    ("Sự cố INC-21 ảnh hưởng tới đâu?", "- MerchantApp: Gateway → Ledger → Payout → MerchantApp (3 cạnh)"),
    ("Sự cố INC-21 ảnh hưởng tới đâu?", "Không đưa vào danh sách: PublicStatus"),
    ("Sự cố INC-21 ảnh hưởng tới đâu?", "cạnh trùng (Gateway → Ledger)"),
    ("Sự cố INC-21 ảnh hưởng tới đâu?", "(Payout → Ledger); BFS không đi lại"),
    ("INC-31 ảnh hưởng những dịch vụ nào?", "CẢNH BÁO incomplete_data"),
    ("INC-31 ảnh hưởng những dịch vụ nào?", "MobileCRM"),
    ("INC-32 ảnh hưởng tới đâu?", "Không duyệt được từ SMSGateway"),
    ("INC-41 ảnh hưởng những gì?", "cũ hơn 100 ngày"),
    ("INC-12 từng ảnh hưởng tới đâu?", "đã xử lý xong"),
    ("INC-404 ảnh hưởng tới đâu?", "Không có sự cố INC-404"),
])
def test_edge_cases(client, question, expected):
    assert expected in chat(client, question)["answer"]


def test_unknown_incident_stops_early(client):
    run = chat(client, "INC-404 ảnh hưởng tới đâu?")
    assert tool_names(run) == ["get_incident"] and run["tool_calls"][0]["error"]["code"] == "incident_not_found"


def test_note_for_resolved_incident_refused(client):
    run = chat(client, "Ghi nhận ảnh hưởng của INC-12")
    assert run["tool_calls"][-1]["error"]["code"] == "incident_resolved"
    assert "Không tạo được đề xuất" in run["answer"]


def test_ask_back_when_incident_missing(client):
    first = chat(client, "DB đang lỗi, ảnh hưởng tới đâu?")
    assert first["tool_calls"] == [] and "mã sự cố" in first["answer"]
    second = chat(client, "INC-9", conversation_id=first["conversation_id"])
    assert tool_names(second) == FLOW


# --- API phụ ----------------------------------------------------------------------

def test_samples_and_data(client):
    assert client.get("/incidents/samples").json()[0]["label"] == "Đề bài: INC-9"
    data = client.get("/incidents/data").json()
    shop = next(s for s in data["systems"] if s["system_id"] == "SHOP")
    assert shop == {"system_id": "SHOP", "name": shop["name"], "current_version": 7, "next_version": 8}
    assert len(data["incidents"]) == 6
    inc9 = next(i for i in data["incidents"] if i["incident_id"] == "INC-9")
    assert inc9["started_at"] == "2026-11-10T08:15:00+07:00"  # đổi sang APP_TIMEZONE, ghi kèm múi giờ


def test_publish_without_newer_version(client):
    response = client.post("/incidents/systems/PAY/publish")
    assert response.status_code == 409
    assert client.post("/incidents/systems/NOPE/publish").status_code == 404


@pytest.mark.parametrize("path, body, status", [
    ("/incidents/INC-9", {"status": "deleted"}, 422),
    ("/incidents/INC-9", {"status": "resolved", "hack": 1}, 422),
    ("/incidents/INC-404", {"status": "resolved"}, 404),
])
def test_change_incident_validation(client, path, body, status):
    assert client.patch(path, json=body).status_code == status


def test_no_restart_endpoint(client):
    paths = {r.path for r in client.app.routes}
    assert not any(word in p for p in paths for word in ("restart", "reboot"))


def test_reset_restores_data_and_closes_pending(client):
    proposal = chat(client, "Ghi nhận ảnh hưởng của INC-9")["proposals"][0]
    client.post("/incidents/systems/SHOP/publish")
    assert client.post("/incidents/reset").json()["closed_proposals"] == 1
    shop = next(s for s in client.get("/incidents/data").json()["systems"] if s["system_id"] == "SHOP")
    assert shop["current_version"] == 7
    assert approve(client, proposal["id"]).status_code == 409  # đã bị đóng
