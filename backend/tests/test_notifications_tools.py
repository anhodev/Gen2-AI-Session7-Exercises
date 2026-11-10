"""Test công cụ Bài 03, gọi thẳng như backend chạy tool_call. Không gọi model. SQLite tạm."""

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.database import create_tables, make_session_factory
from app.core.entities import Proposal
from app.core.tools import ToolContext, ToolError, kind_of
from app.modules.notifications.entities import Campaign, ConsentSource, Customer, Notification
from app.modules.notifications.store import seed_notifications
from app.modules.notifications.tools import build_tools


@pytest.fixture
def db(tmp_path):
    engine, session_factory = make_session_factory(f"sqlite:///{tmp_path}/tools.db")
    create_tables(engine)
    with session_factory() as session:
        seed_notifications(session)
        yield session
    engine.dispose()


@pytest.fixture
def tools(db):
    ctx = ToolContext(db=db, module="notifications", run_id=None, conversation_id="test")
    return {t.name: t for t in build_tools(ctx)}


def schedule(tools, campaign_id="CP-1"):
    return tools["build_send_schedule"].invoke({"campaign_id": campaign_id})


def row(result):
    return [s["message_id"] if s["state"] == "send" else s["state"] for s in result["slots"]]


def test_tool_kinds(tools):
    assert {n: kind_of(t) for n, t in tools.items()} == {
        "get_pending_messages": "read",
        "get_contact_policy": "read",
        "get_opt_in_status": "read",
        "build_send_schedule": "algorithm",
        "propose_send_schedule": "action",
    }


# --- Công cụ đọc ----------------------------------------------------------------

def test_get_pending_messages(tools):
    result = tools["get_pending_messages"].invoke({"campaign_id": "CP-1"})
    assert [m["message_id"] for m in result["messages"]] == ["A1", "A2", "A3", "B1", "B2", "B3"]
    assert result["customer_ids"] == ["A", "B"]


def test_get_contact_policy(tools):
    result = tools["get_contact_policy"].invoke({"campaign_id": "CP-1"})
    assert [s["start"] for s in result["slots"]] == ["09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00"]
    assert result["gap"] == 2 and result["max_per_slot"] == 1
    assert "i+3" in result["rule"]


def test_get_opt_in_status(tools):
    result = tools["get_opt_in_status"].invoke({"customer_ids": ["D", "C", "R", "ZZ", "C"]})
    assert [(s["customer_id"], s["opt_in"]) for s in result["statuses"]] == [
        ("C", "yes"), ("D", "no"), ("R", "unknown"), ("ZZ", "not_found"),
    ]
    assert result["allowed"] == ["C"]


def test_opt_in_source_down_is_error(tools):
    with pytest.raises(ToolError) as exc:
        tools["get_opt_in_status"].invoke({"customer_ids": ["B", "Q"]})
    assert exc.value.code == "consent_source_unavailable"
    assert exc.value.details == {"sources": {"crm-legacy": ["Q"]}}


@pytest.mark.parametrize("name, args", [
    ("get_pending_messages", {"campaign_id": "CP-99"}),
    ("get_contact_policy", {"campaign_id": "CP-99"}),
    ("build_send_schedule", {"campaign_id": "CP-99"}),
])
def test_unknown_campaign(tools, name, args):
    with pytest.raises(ToolError) as exc:
        tools[name].invoke(args)
    assert exc.value.code == "campaign_not_found"


@pytest.mark.parametrize("name, args", [
    ("get_pending_messages", {"campaign_id": "1"}),
    ("get_pending_messages", {"campaign_id": "CP-1; DROP TABLE notifications"}),
    ("get_pending_messages", {"campaign_id": "CP-1", "extra": 1}),
    ("get_opt_in_status", {"customer_ids": []}),
    ("get_opt_in_status", {"customer_ids": ["a lowercase"]}),
    ("get_opt_in_status", {"customer_ids": ["A"] * 201}),
])
def test_bad_args_rejected(tools, name, args):
    with pytest.raises(ValidationError):
        tools[name].invoke(args)


def test_model_cannot_pass_customers_or_slots(tools):
    for extra in ({"customer_ids": ["A"]}, {"gap": 0}, {"slot_count": 99}):
        with pytest.raises(ValidationError):
            tools["build_send_schedule"].invoke({"campaign_id": "CP-1", **extra})


# --- build_send_schedule -------------------------------------------------------------

def test_schedule_exercise_sample(tools):
    result = schedule(tools)
    assert result["status"] == "ok"
    assert row(result) == ["A1", "B1", "idle", "A2", "B2", "idle", "A3", "B3"]
    assert [s["start"] for s in result["slots"]][:2] == ["09:00", "10:00"]
    assert result["scheduled_count"] == 6 and result["idle_count"] == 2 and result["last_send_time"] == "16:00"
    assert {c["customer_id"]: c["slots"] for c in result["customers"]} == {"A": [0, 3, 6], "B": [1, 4, 7]}
    assert result["violations"] == [] and result["data_changed"] == []
    assert result["trace"][2] == {
        "slot": 2, "start": "11:00", "ready": [],
        "waiting": [{"customer_id": "A", "ready_at": 3, "ready_time": "12:00"},
                    {"customer_id": "B", "ready_at": 4, "ready_time": "13:00"}],
        "picked": None,
    }


def test_schedule_excludes_not_opted_in(tools):
    result = schedule(tools, "CP-2")
    assert [(m["message_id"], m["reason_code"]) for m in result["excluded"]] == [
        ("D1", "opted_out"), ("D2", "opted_out"), ("R1", "no_consent_record"),
    ]
    assert row(result) == ["C1", "idle", "idle", "C2", "unused", "unused"]


@pytest.mark.parametrize("campaign_id, expected", [
    ("CP-3", ["F1", "idle", "idle", "F2", "idle", "idle", "F3", "unused"]),  # chỉ một khách
    ("CP-4", ["G1", "G2", "H1", "unused"]),  # gap = 0
    ("CP-5", ["K1", "L1", "M1", "K2", "L2", "M2"]),  # cùng số tin -> alphabet
])
def test_schedule_edge_cases(tools, campaign_id, expected):
    assert row(schedule(tools, campaign_id)) == expected


def test_schedule_out_of_slots(tools):
    result = schedule(tools, "CP-6")
    assert result["status"] == "partial"
    assert [m["message_id"] for m in result["unscheduled"]] == ["N3", "N4"]
    assert "không tự đẩy sang ngày khác" in result["unscheduled"][0]["reason"]


def test_schedule_all_excluded(tools):
    result = schedule(tools, "CP-8")
    assert result["status"] == "no_messages" and result["scheduled_count"] == 0
    assert [m["message_id"] for m in result["excluded"]] == ["D3"]


def test_schedule_refuses_when_consent_source_down(tools):
    with pytest.raises(ToolError) as exc:
        schedule(tools, "CP-7")
    assert exc.value.code == "consent_source_unavailable"


def test_schedule_works_after_source_back(tools, db: Session):
    db.get(ConsentSource, "crm-legacy").available = True
    db.commit()
    assert row(schedule(tools, "CP-7")) == ["Q1", "B4", "Q2", "unused"]


def test_schedule_rechecks_consent(tools, db: Session):
    """AI đã đọc A đồng ý, sau đó A từ chối: lịch dùng dữ liệu mới và báo đã đổi."""
    tools["get_opt_in_status"].invoke({"customer_ids": ["A", "B"]})
    a = db.get(Customer, "A")
    a.opt_in, a.version = False, a.version + 1
    db.commit()

    result = schedule(tools)
    assert row(result) == ["B1", "idle", "idle", "B2", "idle", "idle", "B3", "unused"]
    assert result["data_changed"] == [{"customer_id": "A", "before": "đã đồng ý", "now": "đã từ chối"}]


def test_schedule_ignores_already_scheduled(tools, db: Session):
    db.get(Notification, "A1").status = "scheduled"
    db.commit()
    assert row(schedule(tools))[:3] == ["B1", "A2", "idle"]  # B còn 3 tin, ưu tiên hơn A còn 2


def test_unsupported_policy(tools, db: Session):
    db.get(Campaign, "CP-1").max_per_slot = 2
    db.commit()
    with pytest.raises(ToolError) as exc:
        schedule(tools)
    assert exc.value.code == "unsupported_policy"


# --- propose_send_schedule ------------------------------------------------------------

def test_propose_creates_pending_draft_only(tools, db: Session):
    result = tools["propose_send_schedule"].invoke({"campaign_id": "CP-1"})
    assert result["status"] == "pending_approval" and result["sent"] == 0

    proposal = db.get(Proposal, result["proposal_id"])
    assert proposal.kind == "send_schedule" and proposal.target_id == "CP-1"
    assert [s["message_id"] for s in proposal.payload["schedule"]] == ["A1", "B1", "A2", "B2", "A3", "B3"]
    assert proposal.payload["customer_versions"] == {"A": 1, "B": 1}
    assert db.get(Notification, "A1").status == "pending"  # không đổi tin


def test_propose_same_schedule_is_reused(tools):
    first = tools["propose_send_schedule"].invoke({"campaign_id": "CP-1"})
    second = tools["propose_send_schedule"].invoke({"campaign_id": "CP-1"})
    assert second["proposal_id"] == first["proposal_id"] and second["created"] is False


@pytest.mark.parametrize("campaign_id, code", [
    ("CP-8", "nothing_to_schedule"),
    ("CP-7", "consent_source_unavailable"),
    ("CP-99", "campaign_not_found"),
])
def test_propose_rejects(tools, campaign_id, code):
    with pytest.raises(ToolError) as exc:
        tools["propose_send_schedule"].invoke({"campaign_id": campaign_id})
    assert exc.value.code == code
