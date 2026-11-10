"""Bài 04 - API phụ cho trang tác động sự cố. Hỏi đáp đi qua POST /chat với module "incidents".

  GET   /incidents/samples                       Câu hỏi mẫu, gồm cả ca lỗi/biên.
  GET   /incidents/data                          Hệ thống, dịch vụ, sơ đồ các phiên bản, sự cố, ghi chú đã duyệt.
  POST  /incidents/reset                         Khôi phục dữ liệu mẫu.
  POST  /incidents/systems/{system_id}/publish   Công bố phiên bản sơ đồ kế tiếp (vd SHOP v7 -> v8).
  PATCH /incidents/{incident_id}                 Đổi trạng thái sự cố.

Hai API cuối là thao tác của người dùng trên UI để thử dữ liệu đổi, không phải công cụ của AI.
Không có API khởi động lại hay sửa dịch vụ.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.entities import Proposal, now_utc
from app.core.proposals import PENDING, REJECTED

from .entities import GraphEdge, GraphVersion, ImpactNote, Incident, Service, ServiceSystem
from .store import load_sample_file, next_version, seed_incidents

router = APIRouter(prefix="/incidents", tags=["Bài 04 - Tác động sự cố"])


class IncidentChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["investigating", "monitoring", "resolved"]


@router.get("/samples")
def samples():
    """Câu hỏi mẫu để chạy thử."""
    return load_sample_file()["questions"]


@router.get("/data")
def data(db: Session = Depends(get_db)):
    """Hệ thống, dịch vụ, sơ đồ, sự cố hiện có (dữ liệu giả). Thời gian trả theo UTC."""
    edges: dict[tuple[str, int], list] = {}
    for e in db.scalars(select(GraphEdge).order_by(GraphEdge.id)):
        edges.setdefault((e.system_id, e.version), []).append({"from": e.source, "to": e.target})
    return {
        "systems": [
            {"system_id": s.id, "name": s.name, "current_version": s.current_version,
             "next_version": next_version(db, s.id, s.current_version)}
            for s in db.scalars(select(ServiceSystem).order_by(ServiceSystem.id))
        ],
        "services": [
            {"system_id": s.system_id, "service_id": s.id, "name": s.name, "customer_facing": s.customer_facing}
            for s in db.scalars(select(Service).order_by(Service.system_id, Service.id))
        ],
        "graphs": [
            {"system_id": g.system_id, "version": g.version, "captured_at": g.captured_at, "note": g.note,
             "edges": edges.get((g.system_id, g.version), [])}
            for g in db.scalars(select(GraphVersion).order_by(GraphVersion.system_id, GraphVersion.version))
        ],
        "incidents": [
            {"incident_id": i.id, "system_id": i.system_id, "service_id": i.service_id, "title": i.title,
             "status": i.status, "started_at": i.started_at}
            for i in db.scalars(select(Incident).order_by(Incident.id))
        ],
        "notes": [
            {"note_id": n.id, "incident_id": n.incident_id, "graph_version": n.graph_version, "status": n.status,
             "impacted": n.impacted, "created_at": n.created_at}
            for n in db.scalars(select(ImpactNote).order_by(ImpactNote.id))
        ],
    }


@router.post("/reset")
def reset(db: Session = Depends(get_db)):
    """Nạp lại dữ liệu mẫu. Đề xuất đang chờ của bài này bị từ chối tự động vì tạo trên dữ liệu cũ."""
    seed_incidents(db, force=True)
    closed = db.execute(
        update(Proposal)
        .where(Proposal.module == "incidents", Proposal.status == PENDING)
        .values(status=REJECTED, reviewer="system", note="Dữ liệu mẫu đã được khôi phục", decided_at=now_utc())
    ).rowcount
    db.commit()
    return {"status": "ok", "closed_proposals": closed}


@router.post("/systems/{system_id}/publish")
def publish_next_graph(system_id: str, db: Session = Depends(get_db)):
    """
    Công bố phiên bản sơ đồ kế tiếp. Đề xuất ghi chú tạo trên phiên bản cũ sẽ bị chặn khi duyệt.

    Raises:
        HTTPException: 404 không có hệ thống; 409 không còn phiên bản mới hơn.
    """
    system = db.get(ServiceSystem, system_id)
    if system is None:
        raise HTTPException(status_code=404, detail=f"Không có hệ thống {system_id}")
    nxt = next_version(db, system_id, system.current_version)
    if nxt is None:
        raise HTTPException(status_code=409, detail=f"Hệ thống {system_id} không có sơ đồ mới hơn v{system.current_version}")
    before = system.current_version
    system.current_version = nxt
    db.commit()
    return {"system_id": system_id, "before": before, "current_version": nxt}


@router.patch("/{incident_id}")
def change_incident(incident_id: str, change: IncidentChange, db: Session = Depends(get_db)):
    """
    Đổi trạng thái sự cố.

    Raises:
        HTTPException: 404 không có sự cố.
    """
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"Không có sự cố {incident_id}")
    incident.status = change.status
    db.commit()
    return {"incident_id": incident.id, "status": incident.status}
