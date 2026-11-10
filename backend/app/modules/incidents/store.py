"""Bài 04 - Đọc/ghi hệ thống, dịch vụ, sơ đồ, sự cố. Công cụ chỉ đọc; chỉ hàm duyệt và API demo mới ghi."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import SAMPLES_DIR
from app.core.database import to_utc

from .entities import GraphEdge, GraphVersion, ImpactNote, Incident, Service, ServiceSystem

SAMPLE_FILE = SAMPLES_DIR / "incidents.json"


def load_sample_file() -> dict:
    return json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))


def seed_incidents(db: Session, force: bool = False) -> None:
    """
    Nạp dữ liệu mẫu nếu bảng còn trống.

    Args:
        db (Session): Database session.
        force (bool, optional): Xóa dữ liệu cũ rồi nạp lại (nút "Khôi phục dữ liệu mẫu").
    """
    if not force and db.scalar(select(ServiceSystem.id).limit(1)) is not None:
        return
    if force:
        for table in (ImpactNote, Incident, GraphEdge, GraphVersion, Service, ServiceSystem):
            db.execute(delete(table))
        db.flush()

    data = load_sample_file()
    db.add_all(ServiceSystem(**r) for r in data["systems"])
    db.flush()  # khóa ngoại trên PostgreSQL
    db.add_all(Service(**r) for r in data["services"])
    for g in data["graphs"]:
        db.add(GraphVersion(system_id=g["system_id"], version=g["version"], note=g["note"],
                            captured_at=to_utc(datetime.fromisoformat(g["captured_at"]))))
        db.add_all(GraphEdge(system_id=g["system_id"], version=g["version"], source=a, target=b) for a, b in g["edges"])
    db.add_all(
        Incident(**{**r, "started_at": to_utc(datetime.fromisoformat(r["started_at"]))}) for r in data["incidents"]
    )
    db.commit()


def services_of(db: Session, system_id: str) -> list[Service]:
    return list(db.scalars(select(Service).where(Service.system_id == system_id).order_by(Service.id)))


def graph_of(db: Session, system_id: str, version: int) -> tuple[GraphVersion | None, list[GraphEdge]]:
    """Một phiên bản sơ đồ và các cạnh theo thứ tự nhập."""
    meta = db.get(GraphVersion, (system_id, version))
    edges = list(db.scalars(
        select(GraphEdge).where(GraphEdge.system_id == system_id, GraphEdge.version == version).order_by(GraphEdge.id)
    ))
    return meta, edges


def next_version(db: Session, system_id: str, current: int) -> int | None:
    """Phiên bản sơ đồ mới hơn đang chờ công bố, nếu có."""
    return db.scalar(
        select(GraphVersion.version)
        .where(GraphVersion.system_id == system_id, GraphVersion.version > current)
        .order_by(GraphVersion.version)
        .limit(1)
    )
