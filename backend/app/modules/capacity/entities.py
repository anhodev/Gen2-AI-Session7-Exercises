"""Bài 02 - Bảng dây chuyền, ca, lô hàng, máy (dữ liệu giả).

Đề nói ba loại dữ liệu nằm ở ba nơi khác nhau (hệ thống sản xuất, lịch ca, danh sách máy).
Ở đây chúng là ba bảng riêng, mỗi công cụ đọc một bảng.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.entities import now_utc


class ProductionLine(Base):
    __tablename__ = "production_lines"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # L-1
    name: Mapped[str] = mapped_column(String(100))


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # CA-1
    line_id: Mapped[str] = mapped_column(ForeignKey("production_lines.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))  # "Ca chiều 13:00-21:00"
    hours_left: Mapped[int] = mapped_column(Integer)  # số giờ còn dùng được


class ProductionBatch(Base):
    __tablename__ = "production_batches"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # B-101
    line_id: Mapped[str] = mapped_column(ForeignKey("production_lines.id"), index=True)
    product: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer)  # số sản phẩm còn phải làm
    status: Mapped[str] = mapped_column(String(20), default="open")  # open, done


class Machine(Base):
    __tablename__ = "machines"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # M2
    line_id: Mapped[str] = mapped_column(ForeignKey("production_lines.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    rate_per_hour: Mapped[int] = mapped_column(Integer)  # sản phẩm/giờ
    status: Mapped[str] = mapped_column(String(20), default="available")  # available, busy, maintenance, reserved
    reserved_shift_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Tăng mỗi lần đổi tốc độ/trạng thái. Dùng để biết dữ liệu máy đã đổi sau khi AI đọc.
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
