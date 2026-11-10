"""Bài 02 - API phụ cho trang công suất máy. Hỏi đáp đi qua POST /chat với module "capacity".

  GET   /capacity/samples               Câu hỏi mẫu, gồm cả ca lỗi/biên.
  GET   /capacity/data                  Dây chuyền, ca, lô, máy hiện có, để người dùng tự đối chiếu.
  POST  /capacity/reset                 Khôi phục dữ liệu mẫu.
  PATCH /capacity/machines/{machine_id} Đổi tốc độ/trạng thái máy (người dùng bấm trên UI, không phải công cụ của AI).
                                        Dùng để thử ca "dữ liệu máy đã đổi sau khi AI đọc".
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.entities import Proposal, now_utc
from app.core.proposals import PENDING, REJECTED

from .entities import Machine
from .store import all_data, load_sample_file, seed_capacity

router = APIRouter(prefix="/capacity", tags=["Bài 02 - Công suất máy"])


class MachineChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate_per_hour: int | None = Field(default=None, ge=1, le=100_000, description="Tốc độ mới, sản phẩm/giờ")
    status: Literal["available", "busy", "maintenance"] | None = None


@router.get("/samples")
def samples():
    """Câu hỏi mẫu để chạy thử."""
    return load_sample_file()["questions"]


@router.get("/data")
def data(db: Session = Depends(get_db)):
    """Dây chuyền, ca, lô, máy hiện có (dữ liệu giả)."""
    rows = all_data(db)
    return {
        "lines": [{"line_id": r.id, "name": r.name} for r in rows["lines"]],
        "shifts": [{"shift_id": r.id, "line_id": r.line_id, "name": r.name, "hours_left": r.hours_left} for r in rows["shifts"]],
        "batches": [
            {"batch_id": r.id, "line_id": r.line_id, "product": r.product, "quantity": r.quantity, "status": r.status}
            for r in rows["batches"]
        ],
        "machines": [
            {"machine_id": r.id, "line_id": r.line_id, "name": r.name, "rate_per_hour": r.rate_per_hour,
             "status": r.status, "reserved_shift_id": r.reserved_shift_id, "version": r.version}
            for r in rows["machines"]
        ],
    }


@router.post("/reset")
def reset(db: Session = Depends(get_db)):
    """Nạp lại dữ liệu mẫu. Đề xuất đang chờ của bài này bị từ chối tự động vì tạo trên dữ liệu cũ."""
    seed_capacity(db, force=True)
    closed = db.execute(
        update(Proposal)
        .where(Proposal.module == "capacity", Proposal.status == PENDING)
        .values(status=REJECTED, reviewer="system", note="Dữ liệu mẫu đã được khôi phục", decided_at=now_utc())
    ).rowcount
    db.commit()
    return {"status": "ok", "closed_proposals": closed}


@router.patch("/machines/{machine_id}")
def change_machine(machine_id: str, change: MachineChange, db: Session = Depends(get_db)):
    """
    Đổi tốc độ hoặc trạng thái máy, tăng phiên bản.
    Đề xuất đặt máy tạo trước đó sẽ bị chặn khi duyệt vì phiên bản không khớp.

    Raises:
        HTTPException: 404 không có máy; 400 không có gì để đổi.
    """
    machine = db.get(Machine, machine_id)
    if machine is None:
        raise HTTPException(status_code=404, detail=f"Không có máy {machine_id}")
    if change.rate_per_hour is None and change.status is None:
        raise HTTPException(status_code=400, detail="Cần rate_per_hour hoặc status")
    if change.rate_per_hour is not None:
        machine.rate_per_hour = change.rate_per_hour
    if change.status is not None:
        machine.status = change.status
        machine.reserved_shift_id = None
    machine.version += 1
    machine.updated_at = now_utc()
    db.commit()
    return {"machine_id": machine.id, "rate_per_hour": machine.rate_per_hour, "status": machine.status, "version": machine.version}
