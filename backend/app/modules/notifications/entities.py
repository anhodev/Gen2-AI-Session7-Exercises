"""Bài 03 - Bảng chiến dịch, quy tắc liên hệ, khách, nguồn dữ liệu đồng ý nhận tin, tin chờ gửi (dữ liệu giả).

Trạng thái đồng ý nhận tin nằm ở một nguồn riêng (vd CRM). Một nguồn có thể đang lỗi để thử ca
"công cụ đọc dữ liệu bị lỗi": khi đó không xếp lịch được vì không kiểm tra được quyền nhận tin.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.entities import now_utc


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # CP-1
    name: Mapped[str] = mapped_column(String(100))
    # Quy tắc liên hệ của chiến dịch
    send_date: Mapped[str] = mapped_column(String(10))  # 2026-11-10, giờ địa phương (APP_TIMEZONE)
    first_slot: Mapped[str] = mapped_column(String(5))  # "09:00"
    slot_minutes: Mapped[int] = mapped_column(Integer, default=60)
    slot_count: Mapped[int] = mapped_column(Integer)
    max_per_slot: Mapped[int] = mapped_column(Integer, default=1)
    gap: Mapped[int] = mapped_column(Integer)  # số ô phải cách giữa hai tin cho cùng khách


class ConsentSource(Base):
    __tablename__ = "consent_sources"

    id: Mapped[str] = mapped_column(String(30), primary_key=True)  # crm
    name: Mapped[str] = mapped_column(String(100))
    available: Mapped[bool] = mapped_column(Boolean, default=True)  # False: nguồn không phản hồi


class Customer(Base):
    __tablename__ = "notify_customers"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # A
    name: Mapped[str] = mapped_column(String(100))
    source_id: Mapped[str] = mapped_column(ForeignKey("consent_sources.id"))
    # True: đồng ý; False: từ chối; None: chưa có bản ghi đồng ý (coi như chưa đồng ý)
    opt_in: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Tăng mỗi lần đổi trạng thái đồng ý. Dùng để biết dữ liệu đã đổi sau khi AI đọc hoặc sau khi tạo đề xuất.
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # A1
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("notify_customers.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, scheduled
    scheduled_at: Mapped[str | None] = mapped_column(String(16), nullable=True)  # "2026-11-10 09:00" sau khi duyệt
