"""Test công cụ Bài 04, gọi thẳng như backend chạy tool_call. Không gọi model. SQLite tạm."""

from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.database import create_tables, make_session_factory
from app.core.entities import Proposal
from app.core.tools import ToolContext, ToolError, kind_of
from app.modules.incidents.entities import GraphEdge, ImpactNote, Incident, ServiceSystem
from app.modules.incidents.store import seed_incidents
from app.modules.incidents.tools import build_tools


@pytest.fixture
def db(tmp_path):
    engine, session_factory = make_session_factory(f"sqlite:///{tmp_path}/tools.db")
    create_tables(engine)
    with session_factory() as session:
        seed_incidents(session)
        yield session
    engine.dispose()


@pytest.fixture
def tools(db):
    ctx = ToolContext(db=db, module="incidents", run_id=None, conversation_id="test", tz=ZoneInfo("Asia/Ho_Chi_Minh"))
    return {t.name: t for t in build_tools(ctx)}


def trace(tools, incident_id="INC-9"):
    return tools["trace_impact"].invoke({"incident_id": incident_id})


def paths(result):
    return [(r["service_id"], r["path_text"], r["distance"]) for r in result["impacted"]]


def codes(result):
    return [w["code"] for w in result["warnings"]]


def test_tool_kinds(tools):
    assert {n: kind_of(t) for n, t in tools.items()} == {
        "get_incident": "read",
        "get_service_graph": "read",
        "get_customer_facing_services": "read",
        "trace_impact": "algorithm",
        "propose_impact_note": "action",
    }


# --- Công cụ đọc ----------------------------------------------------------------

def test_get_incident(tools):
    result = tools["get_incident"].invoke({"incident_id": "INC-9"})
    assert result["system_id"] == "SHOP" and result["service_id"] == "DB"
    assert result["status"] == "investigating"
    assert result["started_at"] == "2026-11-10T08:15:00+07:00"


def test_get_service_graph(tools):
    result = tools["get_service_graph"].invoke({"system_id": "SHOP"})
    assert result["version"] == 7 and result["edge_count"] == 5
    assert {"from": "Checkout", "to": "WebStore"} in result["edges"]
    assert "Cache" not in result["services"]  # Cache chỉ có ở v8 chưa công bố


def test_get_customer_facing_services(tools):
    result = tools["get_customer_facing_services"].invoke({"system_id": "SHOP"})
    assert [s["service_id"] for s in result["services"]] == ["MobileApp", "Reports", "WebStore"]


@pytest.mark.parametrize("name, args, code", [
    ("get_incident", {"incident_id": "INC-404"}, "incident_not_found"),
    ("trace_impact", {"incident_id": "INC-404"}, "incident_not_found"),
    ("get_service_graph", {"system_id": "NOPE"}, "system_not_found"),
    ("get_customer_facing_services", {"system_id": "NOPE"}, "system_not_found"),
])
def test_not_found(tools, name, args, code):
    with pytest.raises(ToolError) as exc:
        tools[name].invoke(args)
    assert exc.value.code == code


@pytest.mark.parametrize("name, args", [
    ("get_incident", {"incident_id": "9"}),
    ("get_incident", {"incident_id": "INC-9' OR 1=1"}),
    ("get_service_graph", {"system_id": "shop"}),
    ("get_service_graph", {"system_id": "https://evil.example"}),
    ("trace_impact", {"incident_id": "INC-9", "edges": [["DB", "WebStore"]]}),
    ("trace_impact", {"incident_id": "INC-9", "start": "Auth"}),
])
def test_bad_args_rejected(tools, name, args):
    with pytest.raises(ValidationError):
        tools[name].invoke(args)


# --- trace_impact -------------------------------------------------------------------

def test_trace_exercise_sample(tools):
    result = trace(tools)
    assert result["status"] == "ok" and result["warnings"] == []
    assert result["graph_version"] == 7 and result["failed_service"] == "DB"
    assert paths(result) == [
        ("Reports", "DB → Reports", 1),
        ("MobileApp", "DB → Auth → MobileApp", 2),
        ("WebStore", "DB → Auth → Checkout → WebStore", 3),
    ]
    assert result["layers"] == [["DB"], ["Auth", "Reports"], ["Checkout", "MobileApp"], ["WebStore"]]
    assert [r["service_id"] for r in result["all_reached"]] == ["Auth", "Reports", "Checkout", "MobileApp", "WebStore"]
    assert "CÓ THỂ" in result["note"]


def test_trace_duplicates_cycle_unreachable(tools):
    result = trace(tools, "INC-21")
    assert result["status"] == "ok"
    assert paths(result) == [
        ("MerchantApp", "Gateway → Ledger → Payout → MerchantApp", 3),
        ("MerchantPortal", "Gateway → Ledger → Statement → MerchantPortal", 3),
    ]
    assert result["duplicate_edges"] == [{"from": "Gateway", "to": "Ledger"}]
    assert [s for s in result["bfs_steps"] if s["already_seen"]] == [
        {"service": "Payout", "distance": 2, "discovered": ["MerchantApp"], "already_seen": ["Ledger"]},
    ]
    assert result["not_reached"] == [{"service_id": "PublicStatus", "reason": "Không có đường đi từ Gateway theo sơ đồ v3"}]
    assert result["counts"] == {"services": 8, "edges": 8, "unique_edges": 7}


def test_trace_missing_node_is_incomplete(tools):
    result = trace(tools, "INC-31")
    assert result["status"] == "incomplete_data"
    assert codes(result) == ["unknown_service_in_graph", "customer_facing_missing_from_graph"]
    assert paths(result) == [("Portal", "API → Portal", 1)]
    assert result["not_reached"] == []  # MobileCRM thiếu trong sơ đồ, không được coi là "không bị ảnh hưởng"


def test_trace_failed_service_not_in_graph(tools):
    result = trace(tools, "INC-32")
    assert result["status"] == "incomplete_data"
    assert codes(result)[0] == "failed_service_not_in_graph"
    assert result["impacted"] == [] and result["bfs_steps"] == [] and result["not_reached"] == []


def test_trace_stale_graph(tools):
    result = trace(tools, "INC-41")
    assert result["status"] == "incomplete_data" and codes(result) == ["graph_stale"]
    assert paths(result) == [("Branch", "Mainframe → Batch → Branch", 2)]


def test_trace_resolved_incident(tools):
    result = trace(tools, "INC-12")
    assert result["incident_status"] == "resolved"
    assert paths(result) == [("WebStore", "Checkout → WebStore", 1)]


def test_trace_reports_graph_changed_after_read(tools, db: Session):
    """AI đọc sơ đồ v7, sau đó v8 được công bố: kết quả theo v8 và báo đã đổi."""
    tools["get_service_graph"].invoke({"system_id": "SHOP"})
    db.get(ServiceSystem, "SHOP").current_version = 8
    db.commit()

    result = trace(tools)
    assert result["graph_version"] == 8
    assert result["graph_changed"] == {"before": 7, "now": 8}
    assert "graph_version_changed" in codes(result) and result["status"] == "ok"
    assert paths(result)[:2] == [("MobileApp", "DB → Auth → MobileApp", 2), ("Reports", "DB → Cache → Reports", 2)]


def test_trace_rereads_edges(tools, db: Session):
    db.add(GraphEdge(system_id="SHOP", version=7, source="DB", target="WebStore"))
    db.commit()
    assert paths(trace(tools))[:2] == [("Reports", "DB → Reports", 1), ("WebStore", "DB → WebStore", 1)]


# --- propose_impact_note ------------------------------------------------------------

def test_propose_creates_pending_draft_only(tools, db: Session):
    result = tools["propose_impact_note"].invoke({"incident_id": "INC-9"})
    assert result["status"] == "pending_approval"
    proposal = db.get(Proposal, result["proposal_id"])
    assert proposal.kind == "impact_note" and proposal.target_id == "INC-9"
    assert proposal.payload["graph_version"] == 7
    assert [r["service_id"] for r in proposal.payload["impacted"]] == ["Reports", "MobileApp", "WebStore"]
    assert db.query(ImpactNote).count() == 0


def test_propose_incomplete_is_flagged(tools, db: Session):
    result = tools["propose_impact_note"].invoke({"incident_id": "INC-31"})
    assert "CHƯA đầy đủ" in result["summary"]


def test_propose_resolved_refused(tools, db: Session):
    with pytest.raises(ToolError) as exc:
        tools["propose_impact_note"].invoke({"incident_id": "INC-12"})
    assert exc.value.code == "incident_resolved"
    db.get(Incident, "INC-12").status = "monitoring"
    db.commit()
    assert tools["propose_impact_note"].invoke({"incident_id": "INC-12"})["status"] == "pending_approval"
