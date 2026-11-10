"""Test công cụ Bài 02, gọi thẳng như backend chạy tool_call. Không gọi model. SQLite tạm."""

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.database import create_tables, make_session_factory
from app.core.entities import Proposal
from app.core.tools import ToolContext, ToolError, kind_of
from app.modules.capacity.entities import Machine, ProductionBatch, Shift
from app.modules.capacity.store import seed_capacity
from app.modules.capacity.tools import build_tools


@pytest.fixture
def db(tmp_path):
    engine, session_factory = make_session_factory(f"sqlite:///{tmp_path}/tools.db")
    create_tables(engine)
    with session_factory() as session:
        seed_capacity(session)
        yield session
    engine.dispose()


@pytest.fixture
def tools(db):
    ctx = ToolContext(db=db, module="capacity", run_id=None, conversation_id="test")
    return {t.name: t for t in build_tools(ctx)}


def calc(tools, line_id="L-1", shift_id="CA-1"):
    return tools["calculate_min_required_rate"].invoke({"line_id": line_id, "shift_id": shift_id})


def ids(machines):
    return [m["machine_id"] for m in machines]


def test_tool_kinds(tools):
    assert {n: kind_of(t) for n, t in tools.items()} == {
        "get_open_batches": "read",
        "get_shift_hours": "read",
        "get_available_machines": "read",
        "calculate_min_required_rate": "algorithm",
        "propose_machine_booking": "action",
    }


# --- Công cụ đọc ----------------------------------------------------------------

def test_get_open_batches_skips_done(tools):
    result = tools["get_open_batches"].invoke({"line_id": "L-1"})
    assert [b["quantity"] for b in result["batches"]] == [30, 11, 23, 4]  # B-100 đã xong, không có
    assert result["total_quantity"] == 68


def test_get_shift_hours(tools):
    assert tools["get_shift_hours"].invoke({"line_id": "L-1", "shift_id": "CA-1"})["hours_left"] == 8


def test_get_available_machines_skips_maintenance(tools):
    result = tools["get_available_machines"].invoke({"line_id": "L-1"})
    assert ids(result["machines"]) == ["M1", "M2", "M3"]  # M4 đang bảo trì
    assert [m["rate_per_hour"] for m in result["machines"]] == [8, 12, 16]


@pytest.mark.parametrize("name, args, code", [
    ("get_open_batches", {"line_id": "L-9"}, "line_not_found"),
    ("get_available_machines", {"line_id": "L-9"}, "line_not_found"),
    ("get_shift_hours", {"line_id": "L-1", "shift_id": "CA-99"}, "shift_not_found"),
    ("get_shift_hours", {"line_id": "L-1", "shift_id": "CA-3"}, "shift_not_on_line"),
    ("calculate_min_required_rate", {"line_id": "L-1", "shift_id": "CA-3"}, "shift_not_on_line"),
])
def test_read_errors(tools, name, args, code):
    with pytest.raises(ToolError) as exc:
        tools[name].invoke(args)
    assert exc.value.code == code


@pytest.mark.parametrize("args", [
    {"line_id": "1"},
    {"line_id": "L-1; DROP TABLE machines"},
    {"line_id": "L-1", "extra": 1},
])
def test_bad_args_rejected(tools, args):
    with pytest.raises(ValidationError):
        tools["get_open_batches"].invoke(args)


def test_model_cannot_pass_quantities_or_rates(tools):
    with pytest.raises(ValidationError):
        tools["calculate_min_required_rate"].invoke({"line_id": "L-1", "shift_id": "CA-1", "hours_left": 100})


# --- calculate_min_required_rate ---------------------------------------------------

def test_calculate_exercise_sample(tools):
    result = calc(tools)
    assert result["status"] == "ok"
    assert result["min_rate"] == 11
    assert result["check_at_min"]["calculation"] == "3 + 1 + 3 + 1 = 8 giờ"
    assert result["check_below_min"]["calculation"] == "3 + 2 + 3 + 1 = 9 giờ"
    assert result["check_below_min"]["fits"] is False
    assert result["chosen_machine"]["machine_id"] == "M2"
    assert result["chosen_machine"]["hours_needed"] == 7  # 3 + 1 + 2 + 1 ở tốc độ 12
    assert ids(result["fast_enough"]) == ["M2", "M3"]
    assert ids(result["too_slow"]) == ["M1"]
    assert result["search_steps"] and result["data_changed"] == []


def test_calculate_no_open_batches(tools):
    result = calc(tools, "L-2", "CA-3")
    assert result["status"] == "no_open_batches" and result["chosen_machine"] is None


def test_calculate_zero_quantity_and_exact_deadline(tools):
    result = calc(tools, "L-3", "CA-4")
    assert [b["batch_id"] for b in result["zero_batches"]] == ["B-301"]
    assert result["min_rate"] == 10
    assert result["check_at_min"]["total_hours"] == result["hours_left"] == 4  # vừa đúng hạn ca
    assert result["chosen_machine"]["machine_id"] == "M6"  # đúng bằng 10 vẫn đạt


def test_calculate_no_machine_fast_enough(tools):
    result = calc(tools, "L-4", "CA-5")
    assert result["status"] == "no_machine_fast_enough"
    assert result["min_rate"] == 80
    assert result["chosen_machine"] is None
    assert "thiếu công suất" in result["reason"]


@pytest.mark.parametrize("line_id, shift_id", [("L-5", "CA-6"), ("L-1", "CA-2")])
def test_calculate_impossible_under_rules(tools, line_id, shift_id):
    result = calc(tools, line_id, shift_id)
    assert result["status"] == "impossible_under_rules"
    assert result["min_rate"] is None and result["chosen_machine"] is None


def test_no_available_machine_at_all(tools, db: Session):
    for m in db.query(Machine).filter(Machine.line_id == "L-1"):
        m.status = "busy"
    db.commit()
    result = calc(tools)
    assert result["status"] == "no_machine_fast_enough"
    assert "không có máy nào đang rảnh" in result["reason"]


def test_calculate_rereads_database(tools, db: Session):
    """Dữ liệu đổi sau khi AI đã đọc: thuật toán dùng dữ liệu mới và báo rõ là đã đổi."""
    tools["get_available_machines"].invoke({"line_id": "L-1"})
    db.get(Machine, "M2").rate_per_hour = 10
    db.get(Machine, "M2").version += 1
    db.commit()

    result = calc(tools)
    assert result["chosen_machine"]["machine_id"] == "M3"
    assert result["data_changed"] == [{"machine_id": "M2", "before": "12 sp/giờ, rảnh", "now": "10 sp/giờ, rảnh"}]


def test_machine_back_from_maintenance_is_reported(tools, db: Session):
    tools["get_available_machines"].invoke({"line_id": "L-1"})
    m4 = db.get(Machine, "M4")
    m4.status, m4.version = "available", m4.version + 1
    db.commit()
    changes = calc(tools)["data_changed"]
    assert changes[0]["machine_id"] == "M4" and "chưa có" in changes[0]["before"]


def test_batch_and_shift_changes_are_used(tools, db: Session):
    db.get(ProductionBatch, "B-104").status = "done"
    db.get(Shift, "CA-1").hours_left = 7
    db.commit()
    result = calc(tools)  # còn 30, 11, 23 trong 7 giờ
    assert result["min_rate"] == 11  # 3 + 1 + 3 = 7


# --- propose_machine_booking ----------------------------------------------------------

def test_propose_creates_pending_draft_only(tools, db: Session):
    result = tools["propose_machine_booking"].invoke({"line_id": "L-1", "shift_id": "CA-1", "machine_id": "M2"})
    assert result["status"] == "pending_approval"
    assert result["is_algorithm_choice"] is True

    proposal = db.get(Proposal, result["proposal_id"])
    assert proposal.kind == "machine_booking"
    assert proposal.payload == {
        "line_id": "L-1", "shift_id": "CA-1", "machine_id": "M2", "machine_version": 1,
        "rate_per_hour": 12, "min_rate": 11, "hours_needed": 7, "hours_left": 8,
    }
    assert db.get(Machine, "M2").status == "available"  # không khóa máy


def test_propose_faster_machine_is_flagged(tools):
    result = tools["propose_machine_booking"].invoke({"line_id": "L-1", "shift_id": "CA-1", "machine_id": "M3"})
    assert result["is_algorithm_choice"] is False and result["algorithm_choice"] == "M2"


@pytest.mark.parametrize("line_id, shift_id, machine_id, code", [
    ("L-1", "CA-1", "M1", "machine_too_slow"),
    ("L-1", "CA-1", "M4", "machine_not_available"),
    ("L-1", "CA-1", "M7", "machine_not_on_line"),
    ("L-1", "CA-1", "M99", "machine_not_found"),
    ("L-5", "CA-6", "M10", "no_feasible_rate"),
    ("L-2", "CA-3", "M5", "no_feasible_rate"),
])
def test_propose_rejects(tools, line_id, shift_id, machine_id, code):
    with pytest.raises(ToolError) as exc:
        tools["propose_machine_booking"].invoke({"line_id": line_id, "shift_id": shift_id, "machine_id": machine_id})
    assert exc.value.code == code
