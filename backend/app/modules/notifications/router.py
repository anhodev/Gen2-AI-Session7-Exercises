"""Bài 03 - API phụ cho trang lịch gửi thông báo. Hỏi đáp đi qua POST /chat với module "notifications".

  GET   /notifications/samples                    Câu hỏi mẫu, gồm cả ca lỗi/biên.
  GET   /notifications/data                       Chiến dịch, nguồn đồng ý, khách, tin, để người dùng tự đối chiếu.
  POST  /notifications/reset                      Khôi phục dữ liệu mẫu.
  PATCH /notifications/customers/{customer_id}    Đổi trạng thái đồng ý của khách (người dùng bấm trên UI).
  PATCH /notifications/sources/{source_id}        Bật/tắt nguồn dữ liệu đồng ý để thử ca công cụ đọc bị lỗi.

Hai API PATCH không phải công cụ của AI. Không có API gửi tin.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.entities import Proposal, now_utc
from app.core.proposals import PENDING, REJECTED

from .entities import ConsentSource, Customer
from .store import all_data, load_sample_file, seed_notifications
from .tools import opt_in_code

router = APIRouter(prefix="/notifications", tags=["Bài 03 - Lịch gửi thông báo"])


class ConsentChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opt_in: bool | None  # True đồng ý, False từ chối, None xóa bản ghi đồng ý


class SourceChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool


@router.get("/samples")
def samples():
    """Câu hỏi mẫu để chạy thử."""
    return load_sample_file()["questions"]


@router.get("/data")
def data(db: Session = Depends(get_db)):
    """Chiến dịch, nguồn đồng ý, khách, tin hiện có (dữ liệu giả)."""
    rows = all_data(db)
    return {
        "campaigns": [
            {"campaign_id": c.id, "name": c.name, "send_date": c.send_date, "first_slot": c.first_slot,
             "slot_minutes": c.slot_minutes, "slot_count": c.slot_count, "max_per_slot": c.max_per_slot, "gap": c.gap}
            for c in rows["campaigns"]
        ],
        "sources": [{"source_id": s.id, "name": s.name, "available": s.available} for s in rows["sources"]],
        "customers": [
            {"customer_id": c.id, "name": c.name, "source_id": c.source_id, "opt_in": opt_in_code(c), "version": c.version}
            for c in rows["customers"]
        ],
        "messages": [
            {"message_id": m.id, "campaign_id": m.campaign_id, "customer_id": m.customer_id, "title": m.title,
             "status": m.status, "scheduled_at": m.scheduled_at}
            for m in rows["messages"]
        ],
    }


@router.post("/reset")
def reset(db: Session = Depends(get_db)):
    """Nạp lại dữ liệu mẫu. Đề xuất đang chờ của bài này bị từ chối tự động vì tạo trên dữ liệu cũ."""
    seed_notifications(db, force=True)
    closed = db.execute(
        update(Proposal)
        .where(Proposal.module == "notifications", Proposal.status == PENDING)
        .values(status=REJECTED, reviewer="system", note="Dữ liệu mẫu đã được khôi phục", decided_at=now_utc())
    ).rowcount
    db.commit()
    return {"status": "ok", "closed_proposals": closed}


@router.patch("/customers/{customer_id}")
def change_consent(customer_id: str, change: ConsentChange, db: Session = Depends(get_db)):
    """
    Đổi trạng thái đồng ý nhận tin của khách, tăng phiên bản.
    Đề xuất chốt lịch tạo trước đó sẽ bị chặn khi duyệt.

    Raises:
        HTTPException: 404 không có khách.
    """
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"Không có khách {customer_id}")
    customer.opt_in = change.opt_in
    customer.version += 1
    customer.updated_at = now_utc()
    db.commit()
    return {"customer_id": customer.id, "opt_in": opt_in_code(customer), "version": customer.version}


@router.patch("/sources/{source_id}")
def change_source(source_id: str, change: SourceChange, db: Session = Depends(get_db)):
    """
    Bật/tắt một nguồn dữ liệu đồng ý (giả lập nguồn không phản hồi).

    Raises:
        HTTPException: 404 không có nguồn.
    """
    source = db.get(ConsentSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Không có nguồn {source_id}")
    source.available = change.available
    db.commit()
    return {"source_id": source.id, "available": source.available}
