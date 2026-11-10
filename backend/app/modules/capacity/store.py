"""Bài 02 - Đọc/ghi dây chuyền, ca, lô, máy. Công cụ chỉ đọc; chỉ hàm duyệt và API demo mới ghi."""

from __future__ import annotations

import json

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import SAMPLES_DIR
from app.core.entities import now_utc

from .entities import Machine, ProductionBatch, ProductionLine, Shift

SAMPLE_FILE = SAMPLES_DIR / "capacity.json"
AVAILABLE = "available"


def load_sample_file() -> dict:
    return json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))


def seed_capacity(db: Session, force: bool = False) -> None:
    """
    Nạp dữ liệu mẫu nếu bảng còn trống.

    Args:
        db (Session): Database session.
        force (bool, optional): Xóa dữ liệu cũ rồi nạp lại (nút "Khôi phục dữ liệu mẫu").
    """
    if not force and db.scalar(select(ProductionLine.id).limit(1)) is not None:
        return
    if force:
        for table in (Machine, ProductionBatch, Shift, ProductionLine):
            db.execute(delete(table))
        db.flush()

    data = load_sample_file()
    db.add_all(ProductionLine(id=r["id"], name=r["name"]) for r in data["lines"])
    db.flush()  # dây chuyền phải có trước (khóa ngoại trên PostgreSQL)
    db.add_all(Shift(id=r["id"], line_id=r["line_id"], name=r["name"], hours_left=r["hours_left"]) for r in data["shifts"])
    db.add_all(
        ProductionBatch(id=r["id"], line_id=r["line_id"], product=r["product"], quantity=r["quantity"],
                        status=r.get("status", "open"))
        for r in data["batches"]
    )
    db.add_all(
        Machine(id=r["id"], line_id=r["line_id"], name=r["name"], rate_per_hour=r["rate_per_hour"],
                status=r.get("status", AVAILABLE), version=1, updated_at=now_utc())
        for r in data["machines"]
    )
    db.commit()


def open_batches(db: Session, line_id: str) -> list[ProductionBatch]:
    """Lô chưa làm của dây chuyền, theo mã."""
    return list(db.scalars(
        select(ProductionBatch)
        .where(ProductionBatch.line_id == line_id, ProductionBatch.status == "open")
        .order_by(ProductionBatch.id)
    ))


def available_machines(db: Session, line_id: str) -> list[Machine]:
    """Máy đang rảnh của dây chuyền, theo tốc độ rồi mã."""
    rows = db.scalars(select(Machine).where(Machine.line_id == line_id, Machine.status == AVAILABLE))
    return sorted(rows, key=lambda m: (m.rate_per_hour, m.id))


def all_data(db: Session) -> dict:
    return {
        "lines": db.scalars(select(ProductionLine).order_by(ProductionLine.id)).all(),
        "shifts": db.scalars(select(Shift).order_by(Shift.id)).all(),
        "batches": db.scalars(select(ProductionBatch).order_by(ProductionBatch.id)).all(),
        "machines": sorted(db.scalars(select(Machine)), key=lambda m: (m.line_id, m.rate_per_hour, m.id)),
    }
