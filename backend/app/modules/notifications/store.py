"""Bài 03 - Đọc/ghi chiến dịch, khách, tin chờ gửi. Công cụ chỉ đọc; chỉ hàm duyệt và API demo mới ghi."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import SAMPLES_DIR
from app.core.entities import now_utc

from .entities import Campaign, ConsentSource, Customer, Notification

SAMPLE_FILE = SAMPLES_DIR / "notifications.json"
PENDING = "pending"
SCHEDULED = "scheduled"


def load_sample_file() -> dict:
    return json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))


def seed_notifications(db: Session, force: bool = False) -> None:
    """
    Nạp dữ liệu mẫu nếu bảng còn trống.

    Args:
        db (Session): Database session.
        force (bool, optional): Xóa dữ liệu cũ rồi nạp lại (nút "Khôi phục dữ liệu mẫu").
    """
    if not force and db.scalar(select(Campaign.id).limit(1)) is not None:
        return
    if force:
        for table in (Notification, Customer, ConsentSource, Campaign):
            db.execute(delete(table))
        db.flush()

    data = load_sample_file()
    db.add_all(ConsentSource(**r) for r in data["consent_sources"])
    db.add_all(Campaign(**r) for r in data["campaigns"])
    db.flush()  # khóa ngoại trên PostgreSQL
    db.add_all(Customer(**r, version=1, updated_at=now_utc()) for r in data["customers"])
    db.flush()
    db.add_all(Notification(**r, status=PENDING) for r in data["messages"])
    db.commit()


def pending_messages(db: Session, campaign_id: str) -> list[Notification]:
    """Tin chưa xếp lịch của chiến dịch, theo mã tin."""
    return list(db.scalars(
        select(Notification)
        .where(Notification.campaign_id == campaign_id, Notification.status == PENDING)
        .order_by(Notification.id)
    ))


def slot_times(campaign: Campaign) -> list[tuple[str, str]]:
    """Giờ bắt đầu, kết thúc của từng ô, vd [("09:00", "10:00"), ...]."""
    start = datetime.strptime(f"{campaign.send_date} {campaign.first_slot}", "%Y-%m-%d %H:%M")
    step = timedelta(minutes=campaign.slot_minutes)
    return [
        ((start + step * i).strftime("%H:%M"), (start + step * (i + 1)).strftime("%H:%M"))
        for i in range(campaign.slot_count)
    ]


def all_data(db: Session) -> dict:
    return {
        "campaigns": db.scalars(select(Campaign).order_by(Campaign.id)).all(),
        "sources": db.scalars(select(ConsentSource).order_by(ConsentSource.id)).all(),
        "customers": db.scalars(select(Customer).order_by(Customer.id)).all(),
        "messages": db.scalars(select(Notification).order_by(Notification.campaign_id, Notification.id)).all(),
    }
