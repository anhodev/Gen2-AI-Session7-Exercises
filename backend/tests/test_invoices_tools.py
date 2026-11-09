"""Test công cụ Bài 01, gọi thẳng như backend chạy tool_call. Không gọi model. SQLite tạm."""

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.database import create_tables, make_session_factory
from app.core.entities import Proposal
from app.core.tools import ToolContext, ToolError, kind_of
from app.modules.invoices.entities import BankTransfer, Invoice
from app.modules.invoices.store import seed_invoices
from app.modules.invoices.tools import build_tools


@pytest.fixture
def db(tmp_path):
    engine, session_factory = make_session_factory(f"sqlite:///{tmp_path}/tools.db")
    create_tables(engine)
    with session_factory() as session:
        seed_invoices(session)
        yield session
    engine.dispose()


@pytest.fixture
def tools(db):
    ctx = ToolContext(db=db, module="invoices", run_id=None, conversation_id="test")
    return {t.name: t for t in build_tools(ctx)}


def ids(items):
    return [i["transfer_id"] for i in items]


def test_tool_kinds(tools):
    assert {n: kind_of(t) for n, t in tools.items()} == {
        "get_open_invoice": "read",
        "list_unmatched_transfers": "read",
        "find_two_transfer_match": "algorithm",
        "propose_invoice_match": "action",
    }


# --- get_open_invoice ----------------------------------------------------------

def test_get_open_invoice(tools):
    invoice = tools["get_open_invoice"].invoke({"invoice_id": "I-77"})
    assert invoice["customer_id"] == "C-12"
    assert invoice["currency"] == "VND"
    assert invoice["amount_due_minor"] == 1_500_000
    assert invoice["amount_due"] == "1.500.000 VND"


def test_missing_invoice(tools):
    with pytest.raises(ToolError) as exc:
        tools["get_open_invoice"].invoke({"invoice_id": "I-99"})
    assert exc.value.code == "invoice_not_found"


@pytest.mark.parametrize("invoice_id, word", [("I-78", "đã thanh toán"), ("I-83", "đã hủy")])
def test_closed_invoice(tools, invoice_id, word):
    with pytest.raises(ToolError) as exc:
        tools["get_open_invoice"].invoke({"invoice_id": invoice_id})
    assert exc.value.code == "invoice_not_open"
    assert word in exc.value.message


# --- list_unmatched_transfers ----------------------------------------------------

def test_list_needs_invoice_read_first(tools):
    with pytest.raises(ToolError) as exc:
        tools["list_unmatched_transfers"].invoke({"customer_id": "C-12", "currency": "VND"})
    assert exc.value.code == "invoice_not_read"


def test_list_only_customer_and_currency_of_invoice(tools):
    tools["get_open_invoice"].invoke({"invoice_id": "I-77"})
    result = tools["list_unmatched_transfers"].invoke({"customer_id": "C-12", "currency": "VND"})
    assert ids(result["transfers"]) == ["P1", "P2", "P3"]
    assert result["transfers"][0]["received_at"] == "2026-11-03T02:00:00+00:00"

    for other in ({"customer_id": "C-99", "currency": "VND"}, {"customer_id": "C-12", "currency": "USD"}):
        with pytest.raises(ToolError) as exc:
            tools["list_unmatched_transfers"].invoke(other)
        assert exc.value.code == "filter_mismatch"


# --- find_two_transfer_match ---------------------------------------------------------

def test_match_exercise_sample(tools):
    result = tools["find_two_transfer_match"].invoke({"invoice_id": "I-77"})
    assert result["status"] == "matched"
    assert ids(result["pair"]) == ["P1", "P2"]
    assert result["total"] == "1.500.000 VND"
    assert [(e["transfer_id"], e["reason_code"]) for e in result["excluded"]] == [
        ("P4", "wrong_customer"), ("P5", "wrong_currency"),
    ]
    assert result["other_pairs"][0]["transfer_ids"] == ["P1", "P3"]


@pytest.mark.parametrize("invoice_id, status, pair", [
    ("I-79", "no_match", None),
    ("I-80", "matched", ["P30", "P31"]),
    ("I-81", "matched", ["P41", "P42"]),
    ("I-82", "no_match", None),
])
def test_match_edge_cases(tools, invoice_id, status, pair):
    result = tools["find_two_transfer_match"].invoke({"invoice_id": invoice_id})
    assert result["status"] == status
    assert (ids(result["pair"]) if result["pair"] else None) == pair


def test_match_skips_refund_and_already_matched(tools):
    no_match = tools["find_two_transfer_match"].invoke({"invoice_id": "I-79"})
    assert ("P23", "non_positive_amount") in [(e["transfer_id"], e["reason_code"]) for e in no_match["excluded"]]
    usd = tools["find_two_transfer_match"].invoke({"invoice_id": "I-81"})
    assert ("P40", "already_matched") in [(e["transfer_id"], e["reason_code"]) for e in usd["excluded"]]
    assert usd["total"] == "250.00 USD"


def test_match_rereads_database(tools, db: Session):
    """Dữ liệu đổi sau khi model đã đọc: thuật toán dùng dữ liệu mới, không dùng bản model thấy."""
    tools["get_open_invoice"].invoke({"invoice_id": "I-77"})
    tools["list_unmatched_transfers"].invoke({"customer_id": "C-12", "currency": "VND"})
    db.get(BankTransfer, "P2").status = "matched"
    db.commit()
    result = tools["find_two_transfer_match"].invoke({"invoice_id": "I-77"})
    assert ids(result["pair"]) == ["P1", "P3"]


def test_match_on_closed_invoice_is_error(tools):
    with pytest.raises(ToolError) as exc:
        tools["find_two_transfer_match"].invoke({"invoice_id": "I-78"})
    assert exc.value.code == "invoice_not_open"


def test_model_cannot_pass_amounts(tools):
    with pytest.raises(ValidationError):
        tools["find_two_transfer_match"].invoke({"invoice_id": "I-77", "amounts": [900000, 600000]})


# --- propose_invoice_match -----------------------------------------------------

def test_propose_creates_pending_draft_only(tools, db: Session):
    result = tools["propose_invoice_match"].invoke({"invoice_id": "I-77", "transfer_ids": ["P1", "P2"]})
    assert result["status"] == "pending_approval"
    assert result["matches_algorithm"] is True

    proposal = db.get(Proposal, result["proposal_id"])
    assert proposal.kind == "invoice_match"
    assert proposal.payload["transfer_ids"] == ["P1", "P2"]
    # Sổ sách không đổi
    assert db.get(Invoice, "I-77").status == "open"
    assert db.get(BankTransfer, "P1").status == "unmatched"


def test_propose_other_valid_pair_is_flagged(tools):
    result = tools["propose_invoice_match"].invoke({"invoice_id": "I-77", "transfer_ids": ["P1", "P3"]})
    assert result["matches_algorithm"] is False


@pytest.mark.parametrize("transfer_ids, problem", [
    (["P1", "P4"], "khách C-99"),
    (["P1", "P5"], "bằng USD"),
    (["P2", "P3"], "khác số còn thiếu"),
    (["P1", "P1"], "chính nó"),
    (["P1", "P404"], "Không có giao dịch P404"),
])
def test_propose_rejects_invalid_pair(tools, transfer_ids, problem):
    with pytest.raises(ToolError) as exc:
        tools["propose_invoice_match"].invoke({"invoice_id": "I-77", "transfer_ids": transfer_ids})
    assert exc.value.code == "invalid_match"
    assert any(problem in p for p in exc.value.details["problems"])


@pytest.mark.parametrize("transfer_ids", [["P1"], ["P1", "P2", "P3"], ["P1", "abc"]])
def test_propose_args_shape(tools, transfer_ids):
    with pytest.raises(ValidationError):
        tools["propose_invoice_match"].invoke({"invoice_id": "I-77", "transfer_ids": transfer_ids})
