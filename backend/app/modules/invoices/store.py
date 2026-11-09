"""Bài 01 - Đọc/ghi hóa đơn và giao dịch. Công cụ chỉ đọc; chỉ hàm duyệt mới ghi."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import SAMPLES_DIR
from app.core.database import as_utc, to_utc

from .algo import UNMATCHED, Transfer
from .entities import BankTransfer, Invoice

SAMPLE_FILE = SAMPLES_DIR / "invoices.json"


def load_sample_file() -> dict:
    return json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))


def seed_invoices(db: Session, force: bool = False) -> None:
    """
    Nạp hóa đơn và giao dịch mẫu nếu bảng còn trống.

    Args:
        db (Session): Database session.
        force (bool, optional): Xóa dữ liệu cũ rồi nạp lại (nút "Khôi phục dữ liệu mẫu").
    """
    if not force and db.scalar(select(Invoice.id).limit(1)) is not None:
        return
    if force:
        db.execute(delete(BankTransfer))
        db.execute(delete(Invoice))

    data = load_sample_file()
    for row in data["invoices"]:
        db.add(Invoice(
            id=row["id"], customer_id=row["customer_id"], currency=row["currency"],
            amount_total_minor=row["amount_total_minor"], amount_due_minor=row["amount_due_minor"],
            status=row["status"], issued_at=to_utc(datetime.fromisoformat(row["issued_at"])),
        ))
    for row in data["transfers"]:
        db.add(BankTransfer(
            id=row["id"], customer_id=row["customer_id"], currency=row["currency"],
            amount_minor=row["amount_minor"], received_at=to_utc(datetime.fromisoformat(row["received_at"])),
            memo=row.get("memo", ""), status=row.get("status", UNMATCHED),
            matched_invoice_id=row.get("matched_invoice_id"),
        ))
    db.commit()


def by_time(rows) -> list[BankTransfer]:
    return sorted(rows, key=lambda r: (as_utc(r.received_at), r.id))


def unmatched_transfers(db: Session, customer_id: str, currency: str) -> list[BankTransfer]:
    """Giao dịch chưa ghép của một khách, một loại tiền, theo giờ nhận rồi mã."""
    return by_time(db.scalars(
        select(BankTransfer).where(
            BankTransfer.customer_id == customer_id,
            BankTransfer.currency == currency,
            BankTransfer.status == UNMATCHED,
        )
    ))


def candidate_transfers(db: Session, customer_id: str, currency: str, amount_due_minor: int) -> list[BankTransfer]:
    """
    Giao dịch đưa vào thuật toán.

    - Mọi giao dịch của khách này (mọi loại tiền, mọi trạng thái): để giải thích vì sao loại.
    - Giao dịch chưa ghép, cùng loại tiền, của khách KHÁC nhưng có số tiền "ghép nhầm" được
      (bằng phần còn thiếu sau một khoản của khách này). Vd P4 của C-99: 600.000 + P1 900.000
      vừa đủ 1.500.000, nên cần ghi rõ là bị loại vì sai khách.
    """
    own = list(db.scalars(select(BankTransfer).where(BankTransfer.customer_id == customer_id)))
    complements = {
        amount_due_minor - r.amount_minor
        for r in own
        if r.currency == currency and r.status == UNMATCHED and r.amount_minor > 0
    }
    lookalikes = []
    if complements:
        lookalikes = list(db.scalars(
            select(BankTransfer).where(
                BankTransfer.customer_id != customer_id,
                BankTransfer.currency == currency,
                BankTransfer.status == UNMATCHED,
                BankTransfer.amount_minor.in_(complements),
            )
        ))
    return by_time(own + lookalikes)


def to_algo(row: BankTransfer) -> Transfer:
    return Transfer(row.id, row.customer_id, row.currency, row.amount_minor, as_utc(row.received_at), row.status)


def all_data(db: Session) -> tuple[list[Invoice], list[BankTransfer]]:
    invoices = db.scalars(select(Invoice).order_by(Invoice.id)).all()
    return list(invoices), by_time(db.scalars(select(BankTransfer)))
