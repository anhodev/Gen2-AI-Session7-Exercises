"""Bài 04 - Bảng hệ thống, danh mục dịch vụ, sơ đồ phụ thuộc theo phiên bản, sự cố, ghi chú ảnh hưởng (dữ liệu giả).

Sơ đồ lưu theo phiên bản: mỗi hệ thống có phiên bản đang dùng (current_version) và có thể có phiên bản mới hơn
chờ công bố. Công bố phiên bản mới giữa lúc AI đang xử lý là ca "sơ đồ đã đổi phiên bản trong lúc xử lý".
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.entities import now_utc


class ServiceSystem(Base):
    __tablename__ = "service_systems"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # SHOP
    name: Mapped[str] = mapped_column(String(100))
    current_version: Mapped[int] = mapped_column(Integer)  # phiên bản sơ đồ đang dùng


class Service(Base):
    """Danh mục dịch vụ của hệ thống (nguồn riêng, không phải sơ đồ)."""

    __tablename__ = "services"

    system_id: Mapped[str] = mapped_column(ForeignKey("service_systems.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # DB, WebStore
    name: Mapped[str] = mapped_column(String(100))
    customer_facing: Mapped[bool] = mapped_column(Boolean, default=False)  # người dùng trực tiếp thấy


class GraphVersion(Base):
    __tablename__ = "graph_versions"

    system_id: Mapped[str] = mapped_column(ForeignKey("service_systems.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # lúc chụp sơ đồ
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class GraphEdge(Base):
    """Cạnh source -> target: target phụ thuộc source. Có thể trùng (dữ liệu bẩn)."""

    __tablename__ = "graph_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    system_id: Mapped[str] = mapped_column(String(20), index=True)
    version: Mapped[int] = mapped_column(Integer, index=True)
    source: Mapped[str] = mapped_column(String(40))
    target: Mapped[str] = mapped_column(String(40))


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # INC-9
    system_id: Mapped[str] = mapped_column(ForeignKey("service_systems.id"))
    service_id: Mapped[str] = mapped_column(String(40))  # dịch vụ bị lỗi
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))  # investigating, monitoring, resolved
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ImpactNote(Base):
    """Ghi chú "có thể bị ảnh hưởng" gắn vào sự cố, chỉ tạo khi người trực duyệt đề xuất."""

    __tablename__ = "impact_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    graph_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))  # ok, incomplete_data
    impacted: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
