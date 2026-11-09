"""Bài 01 - API phụ cho trang đối soát. Hỏi đáp đi qua POST /chat với module "invoices".

  GET  /invoices/samples   Câu hỏi mẫu, gồm cả ca lỗi/biên.
  GET  /invoices/data      Hóa đơn và giao dịch hiện có, để người dùng tự đối chiếu.
  POST /invoices/reset     Khôi phục dữ liệu mẫu (sau khi đã duyệt thử vài đề xuất).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_display_tz
from app.core.entities import Proposal, now_utc
from app.core.proposals import PENDING, REJECTED

from .store import all_data, load_sample_file, seed_invoices
from .tools import invoice_view, transfer_view

router = APIRouter(prefix="/invoices", tags=["Bài 01 - Đối soát hóa đơn"])


@router.get("/samples")
def samples():
    """Câu hỏi mẫu để chạy thử."""
    return load_sample_file()["questions"]


@router.get("/data")
def data(db: Session = Depends(get_db), tz: ZoneInfo = Depends(get_display_tz)):
    """Hóa đơn và giao dịch hiện có trong hệ thống (dữ liệu giả)."""
    invoices, transfers = all_data(db)
    return {
        "invoices": [invoice_view(i, tz) for i in invoices],
        "transfers": [{**transfer_view(t, tz), "matched_invoice_id": t.matched_invoice_id} for t in transfers],
    }


@router.post("/reset")
def reset(db: Session = Depends(get_db)):
    """
    Nạp lại dữ liệu mẫu. Đề xuất đang chờ của bài này bị từ chối tự động,
    vì chúng được tạo trên dữ liệu cũ.
    """
    seed_invoices(db, force=True)
    closed = db.execute(
        update(Proposal)
        .where(Proposal.module == "invoices", Proposal.status == PENDING)
        .values(status=REJECTED, reviewer="system", note="Dữ liệu mẫu đã được khôi phục", decided_at=now_utc())
    ).rowcount
    db.commit()
    return {"status": "ok", "closed_proposals": closed}
