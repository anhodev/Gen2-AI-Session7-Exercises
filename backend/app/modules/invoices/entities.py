"""Bài 01 - Bảng hóa đơn và giao dịch chuyển tiền (dữ liệu giả)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # I-77
    customer_id: Mapped[str] = mapped_column(String(20), index=True)  # C-12
    currency: Mapped[str] = mapped_column(String(3))
    amount_total_minor: Mapped[int] = mapped_column(BigInteger)  # tổng hóa đơn, đơn vị nhỏ nhất
    amount_due_minor: Mapped[int] = mapped_column(BigInteger)  # còn thiếu
    status: Mapped[str] = mapped_column(String(20), default="open")  # open, paid, cancelled
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BankTransfer(Base):
    __tablename__ = "bank_transfers"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # P1
    customer_id: Mapped[str] = mapped_column(String(20), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    amount_minor: Mapped[int] = mapped_column(BigInteger)  # âm là khoản hoàn tiền
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    memo: Mapped[str] = mapped_column(Text, default="")  # nội dung chuyển khoản, thường không ghi mã hóa đơn
    status: Mapped[str] = mapped_column(String(20), default="unmatched")  # unmatched, matched
    matched_invoice_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
