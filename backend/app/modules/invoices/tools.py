"""Bài 01 - Công cụ cho model gọi.

  get_open_invoice(invoice_id)                     read       Hóa đơn còn mở: khách, loại tiền, số còn thiếu
  list_unmatched_transfers(customer_id, currency)  read       Giao dịch chưa ghép của khách đó, loại tiền đó
  find_two_transfer_match(invoice_id)              algorithm  Tự đọc lại hóa đơn + giao dịch, chạy hash map
  propose_invoice_match(invoice_id, transfer_ids)  action     Tạo đề xuất chờ kế toán duyệt, không đổi sổ sách

Model chỉ truyền mã. Số tiền luôn đọc từ database, không nhận từ model.
"""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Annotated

from langchain_core.tools import BaseTool, tool
from pydantic import Field
from sqlalchemy.orm import Session

from app.core.database import as_utc
from app.core.proposals import create_proposal, proposal_view
from app.core.tools import ToolArgs, ToolContext, ToolError, with_kind

from .algo import EXCLUDE_REASONS, MATCHED, UNMATCHED, format_amount, match_two_transfers
from .entities import BankTransfer, Invoice
from .store import candidate_transfers, to_algo, unmatched_transfers

INVOICE_ID = r"^I-\d{1,10}$"
CUSTOMER_ID = r"^C-\d{1,10}$"
TRANSFER_ID = r"^P\d{1,10}$"
CURRENCY = r"^[A-Z]{3}$"

PROPOSAL_KIND = "invoice_match"


class InvoiceArgs(ToolArgs):
    invoice_id: str = Field(pattern=INVOICE_ID, description="Mã hóa đơn người dùng hỏi, vd I-77")


class TransferListArgs(ToolArgs):
    customer_id: str = Field(pattern=CUSTOMER_ID, description="Mã khách lấy từ kết quả get_open_invoice, vd C-12")
    currency: str = Field(pattern=CURRENCY, description="Loại tiền lấy từ kết quả get_open_invoice, vd VND")


class ProposeArgs(ToolArgs):
    invoice_id: str = Field(pattern=INVOICE_ID, description="Mã hóa đơn")
    transfer_ids: list[Annotated[str, Field(pattern=TRANSFER_ID)]] = Field(
        min_length=2, max_length=2, description="Hai mã giao dịch do find_two_transfer_match trả về, vd [\"P1\", \"P2\"]"
    )


# --- Đọc và kiểm tra --------------------------------------------------------

def load_open_invoice(db: Session, invoice_id: str, tz: tzinfo) -> Invoice:
    """
    Đọc hóa đơn còn mở.

    Raises:
        ToolError: invoice_not_found; invoice_not_open (đã thanh toán, đã hủy, không còn thiếu tiền).
    """
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise ToolError("invoice_not_found", f"Không có hóa đơn {invoice_id} trong hệ thống")
    if invoice.status != "open" or invoice.amount_due_minor <= 0:
        status_text = {"paid": "đã thanh toán", "cancelled": "đã hủy"}.get(invoice.status, f"ở trạng thái {invoice.status}")
        raise ToolError(
            "invoice_not_open",
            f"Hóa đơn {invoice_id} {status_text}, không còn tiền cần đối soát",
            details=invoice_view(invoice, tz),
        )
    return invoice


def validate_match(db: Session, invoice_id: str, transfer_ids: list[str], tz: tzinfo) -> tuple[Invoice, list[BankTransfer]]:
    """
    Kiểm tra một cặp giao dịch có trả đủ hóa đơn không, trên dữ liệu mới nhất.

    Dùng cho cả công cụ tạo đề xuất và bước người duyệt bấm "Duyệt".

    Raises:
        ToolError: Hóa đơn không còn mở, hoặc invalid_match kèm danh sách vấn đề.

    Returns:
        tuple[Invoice, list[BankTransfer]]: Hóa đơn và hai giao dịch.
    """
    invoice = load_open_invoice(db, invoice_id, tz)
    problems = []
    if len(set(transfer_ids)) != len(transfer_ids):
        problems.append("Một giao dịch không được ghép với chính nó")

    rows = []
    for tid in dict.fromkeys(transfer_ids):
        row = db.get(BankTransfer, tid)
        if row is None:
            problems.append(f"Không có giao dịch {tid}")
            continue
        rows.append(row)
        if row.customer_id != invoice.customer_id:
            problems.append(f"{tid} của khách {row.customer_id}, hóa đơn của khách {invoice.customer_id}")
        if row.currency != invoice.currency:
            problems.append(f"{tid} bằng {row.currency}, hóa đơn bằng {invoice.currency}")
        if row.status != UNMATCHED:
            problems.append(f"{tid} đã ghép với hóa đơn {row.matched_invoice_id or 'khác'}")
        if row.amount_minor <= 0:
            problems.append(f"{tid} có số tiền không dương")

    if not problems:
        total = sum(r.amount_minor for r in rows)
        if total != invoice.amount_due_minor:
            problems.append(
                f"Tổng {format_amount(total, invoice.currency)} khác số còn thiếu "
                f"{format_amount(invoice.amount_due_minor, invoice.currency)}"
            )
    if problems:
        raise ToolError("invalid_match", "Cặp giao dịch không trả đủ hóa đơn", details={"problems": problems})
    return invoice, rows


# --- Hiển thị -----------------------------------------------------------------

def local_iso(value: datetime, tz: tzinfo) -> str:
    return as_utc(value).astimezone(tz).isoformat()


def invoice_view(invoice: Invoice, tz: tzinfo) -> dict:
    return {
        "invoice_id": invoice.id,
        "customer_id": invoice.customer_id,
        "currency": invoice.currency,
        "amount_total_minor": invoice.amount_total_minor,
        "amount_due_minor": invoice.amount_due_minor,
        "amount_due": format_amount(invoice.amount_due_minor, invoice.currency),
        "status": invoice.status,
        "issued_at": local_iso(invoice.issued_at, tz),
    }


def transfer_view(row: BankTransfer, tz: tzinfo) -> dict:
    return {
        "transfer_id": row.id,
        "customer_id": row.customer_id,
        "currency": row.currency,
        "amount_minor": row.amount_minor,
        "amount": format_amount(row.amount_minor, row.currency),
        "received_at": local_iso(row.received_at, tz),
        "status": row.status,
        "memo": row.memo,
    }


def run_match(db: Session, invoice_id: str, tz: tzinfo) -> dict:
    """Đọc lại hóa đơn và giao dịch từ database, chạy thuật toán, trả kết quả cho model."""
    invoice = load_open_invoice(db, invoice_id, tz)
    rows = {r.id: r for r in candidate_transfers(db, invoice.customer_id, invoice.currency, invoice.amount_due_minor)}
    result = match_two_transfers([to_algo(r) for r in rows.values()], invoice.customer_id, invoice.currency, invoice.amount_due_minor)

    pair = [transfer_view(rows[t.id], tz) for t in result.pair] if result.pair else None
    return {
        "invoice_id": invoice.id,
        "customer_id": invoice.customer_id,
        "currency": invoice.currency,
        "amount_due_minor": invoice.amount_due_minor,
        "amount_due": format_amount(invoice.amount_due_minor, invoice.currency),
        "status": result.status,
        "pair": pair,
        "total": format_amount(sum(p["amount_minor"] for p in pair), invoice.currency) if pair else None,
        "reason": result.reason,
        "scan_order": [transfer_view(rows[t.id], tz) for t in result.eligible],
        "excluded": [
            {**transfer_view(rows[t.id], tz), "reason_code": code, "reason": EXCLUDE_REASONS[code]}
            for t, code in result.excluded
        ],
        "other_pairs": [
            {"transfer_ids": list(p), "note": "Cũng đủ tiền nhưng hoàn tất muộn hơn khi quét theo giờ nhận"}
            for p in result.other_pairs
        ],
        "rule": "Chỉ xét giao dịch unmatched, cùng khách, cùng loại tiền, số tiền dương; quét theo giờ nhận rồi mã; chọn cặp hoàn tất sớm nhất.",
    }


# --- Công cụ --------------------------------------------------------------------

def build_tools(ctx: ToolContext) -> list[BaseTool]:
    """Tạo công cụ gắn với database session và run hiện tại."""

    @tool(args_schema=InvoiceArgs)
    def get_open_invoice(invoice_id: str) -> dict:
        """Đọc hóa đơn chưa thanh toán: mã khách, loại tiền, số tiền còn thiếu, trạng thái.
        Gọi đầu tiên với đúng mã hóa đơn người dùng hỏi."""
        invoice = load_open_invoice(ctx.db, invoice_id, ctx.tz)
        ctx.seen["invoice"] = {"invoice_id": invoice.id, "customer_id": invoice.customer_id, "currency": invoice.currency}
        return invoice_view(invoice, ctx.tz)

    @tool(args_schema=TransferListArgs)
    def list_unmatched_transfers(customer_id: str, currency: str) -> dict:
        """Liệt kê các khoản chuyển tiền chưa ghép với hóa đơn nào của một khách, một loại tiền.
        customer_id và currency phải lấy từ kết quả get_open_invoice."""
        seen = ctx.seen.get("invoice")
        if seen is None:
            raise ToolError("invoice_not_read", "Hãy gọi get_open_invoice trước để biết khách và loại tiền của hóa đơn")
        if (customer_id, currency) != (seen["customer_id"], seen["currency"]):
            raise ToolError(
                "filter_mismatch",
                f"Hóa đơn {seen['invoice_id']} của khách {seen['customer_id']}, loại tiền {seen['currency']}. "
                f"Không lấy giao dịch của {customer_id}/{currency}.",
            )
        rows = unmatched_transfers(ctx.db, customer_id, currency)
        return {"customer_id": customer_id, "currency": currency, "count": len(rows),
                "transfers": [transfer_view(r, ctx.tz) for r in rows]}

    @tool(args_schema=InvoiceArgs)
    def find_two_transfer_match(invoice_id: str) -> dict:
        """Chạy thuật toán tìm hai khoản chuyển tiền cộng lại vừa đủ số tiền còn thiếu của hóa đơn.
        Công cụ tự đọc lại hóa đơn và giao dịch từ hệ thống. Trả cặp giao dịch, hoặc no_match kèm lý do."""
        result = run_match(ctx.db, invoice_id, ctx.tz)
        ctx.seen["match"] = result
        return result

    @tool(args_schema=ProposeArgs)
    def propose_invoice_match(invoice_id: str, transfer_ids: list[str]) -> dict:
        """Tạo bản nháp đối soát (hóa đơn + hai giao dịch) chờ kế toán có quyền duyệt.
        KHÔNG ghi nhận thanh toán, KHÔNG thay đổi sổ sách. Chỉ gọi khi người dùng yêu cầu ghi nhận/đối soát."""
        invoice, rows = validate_match(ctx.db, invoice_id, transfer_ids, ctx.tz)
        total = format_amount(sum(r.amount_minor for r in rows), invoice.currency)
        proposal, created = create_proposal(
            ctx,
            kind=PROPOSAL_KIND,
            target_id=invoice.id,
            payload={
                "invoice_id": invoice.id,
                "customer_id": invoice.customer_id,
                "currency": invoice.currency,
                "amount_due_minor": invoice.amount_due_minor,
                "transfer_ids": list(transfer_ids),
            },
            summary=f"Ghi nhận {' + '.join(transfer_ids)} = {total} cho hóa đơn {invoice.id} (khách {invoice.customer_id})",
        )
        algo_pair = run_match(ctx.db, invoice_id, ctx.tz)["pair"] or []
        return {
            **proposal_view(proposal, created),
            "matches_algorithm": [p["transfer_id"] for p in algo_pair] == list(transfer_ids),
        }

    return [
        with_kind(get_open_invoice, "read"),
        with_kind(list_unmatched_transfers, "read"),
        with_kind(find_two_transfer_match, "algorithm"),
        with_kind(propose_invoice_match, "action"),
    ]
