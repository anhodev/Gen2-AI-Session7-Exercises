"""Bài 04 - Công cụ cho model gọi.

  get_incident(incident_id)                    read       Dịch vụ bị lỗi, thời điểm, trạng thái sự cố
  get_service_graph(system_id)                 read       Các quan hệ phụ thuộc và phiên bản sơ đồ
  get_customer_facing_services(system_id)      read       Những dịch vụ người dùng trực tiếp thấy
  trace_impact(incident_id)                    algorithm  Tự đọc lại sự cố + sơ đồ + danh mục; BFS; kiểm tra dữ liệu thiếu/cũ
  propose_impact_note(incident_id)             action     Đề xuất ghi chú "có thể bị ảnh hưởng" vào sự cố, chờ người trực duyệt

Chỉ phân tích: không có công cụ khởi động lại hay sửa dịch vụ. Model không truyền cạnh hay danh sách dịch vụ;
trace_impact chỉ nhận mã sự cố để không dùng dữ liệu cũ hoặc cạnh do model bịa.
"""

from __future__ import annotations

from datetime import timedelta, tzinfo

from langchain_core.tools import BaseTool, tool
from pydantic import Field
from sqlalchemy.orm import Session

from app.core.database import as_utc
from app.core.proposals import create_proposal, proposal_view
from app.core.tools import ToolArgs, ToolContext, ToolError, with_kind

from . import algo
from .entities import Incident, ServiceSystem
from .store import graph_of, services_of

INCIDENT_ID = r"^INC-\d{1,10}$"
SYSTEM_ID = r"^[A-Z][A-Z0-9_-]{1,19}$"

PROPOSAL_KIND = "impact_note"
STALE_AFTER = timedelta(days=30)  # sơ đồ chụp trước lúc sự cố bắt đầu quá 30 ngày thì coi là quá cũ
INCIDENT_STATUS = {"investigating": "đang điều tra", "monitoring": "đang theo dõi", "resolved": "đã xử lý xong"}
POSSIBLE = (
    "Đây là các phần CÓ THỂ bị ảnh hưởng theo sơ đồ phụ thuộc, chưa xác nhận đã thực sự hỏng. "
    "Cần kiểm tra từng dịch vụ (cảnh báo, log, chỉ số) trước khi kết luận."
)
RULE = (
    "Cạnh A -> B nghĩa là B phụ thuộc A. BFS từ dịch vụ lỗi theo chiều mũi tên, đi từng lớp; ghi nhớ điểm đã đi qua "
    "nên không lặp khi có vòng; cạnh trùng tính một lần; lưu điểm trước đó để dựng đường đi ít cạnh nhất. "
    "Kết quả xếp theo số cạnh rồi mã dịch vụ. Dịch vụ không có đường đi từ điểm lỗi không nằm trong danh sách."
)
# Cảnh báo làm kết quả không chắc đầy đủ -> status incomplete_data
INCOMPLETE = {"failed_service_not_in_graph", "unknown_service_in_graph", "customer_facing_missing_from_graph", "graph_stale"}


class IncidentArgs(ToolArgs):
    incident_id: str = Field(pattern=INCIDENT_ID, description="Mã sự cố người dùng nói, vd INC-9")


class SystemArgs(ToolArgs):
    system_id: str = Field(pattern=SYSTEM_ID, description="Mã hệ thống lấy từ get_incident, vd SHOP")


# --- Đọc và kiểm tra --------------------------------------------------------

def local_iso(value, tz: tzinfo) -> str:
    return as_utc(value).astimezone(tz).isoformat()


def load_incident(db: Session, incident_id: str) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise ToolError("incident_not_found", f"Không có sự cố {incident_id} trong hệ thống")
    return incident


def load_system(db: Session, system_id: str) -> ServiceSystem:
    system = db.get(ServiceSystem, system_id)
    if system is None:
        raise ToolError("system_not_found", f"Không có hệ thống {system_id}")
    return system


def load_graph(db: Session, system: ServiceSystem):
    meta, edges = graph_of(db, system.id, system.current_version)
    if meta is None:
        raise ToolError("graph_not_found", f"Hệ thống {system.id} chưa có sơ đồ phiên bản v{system.current_version}")
    return meta, edges


def incident_view(db: Session, incident: Incident, tz: tzinfo) -> dict:
    names = {s.id: s.name for s in services_of(db, incident.system_id)}
    return {
        "incident_id": incident.id,
        "system_id": incident.system_id,
        "service_id": incident.service_id,
        "service_name": names.get(incident.service_id),
        "title": incident.title,
        "status": incident.status,
        "status_label": INCIDENT_STATUS.get(incident.status, incident.status),
        "started_at": local_iso(incident.started_at, tz),
    }


def path_text(path: list[str]) -> str:
    return " → ".join(path)


def run_trace(db: Session, incident_id: str, tz: tzinfo, seen_version: int | None = None) -> dict:
    """Đọc lại sự cố, sơ đồ đang dùng, danh mục dịch vụ; kiểm tra dữ liệu thiếu/cũ; chạy BFS."""
    incident = load_incident(db, incident_id)
    system = load_system(db, incident.system_id)
    meta, edge_rows = load_graph(db, system)
    catalog = {s.id: s for s in services_of(db, system.id)}
    customer_facing = {s.id for s in catalog.values() if s.customer_facing}
    edges = [(e.source, e.target) for e in edge_rows]
    nodes = {x for e in edges for x in e}
    failed = incident.service_id

    warnings: list[dict] = []
    if failed not in nodes:
        warnings.append({"code": "failed_service_not_in_graph",
                         "message": f"Dịch vụ lỗi {failed} không có trong sơ đồ v{meta.version}, không duyệt được"})
    unknown = sorted(nodes - set(catalog))
    if unknown:
        warnings.append({"code": "unknown_service_in_graph",
                         "message": f"Sơ đồ có dịch vụ không có trong danh mục: {', '.join(unknown)}"})
    missing = sorted(customer_facing - nodes)
    if missing:
        warnings.append({"code": "customer_facing_missing_from_graph",
                         "message": f"Dịch vụ người dùng thấy không có trong sơ đồ: {', '.join(missing)}; chưa biết chúng phụ thuộc gì"})
    age = as_utc(incident.started_at) - as_utc(meta.captured_at)
    if age > STALE_AFTER:
        warnings.append({"code": "graph_stale",
                         "message": f"Sơ đồ v{meta.version} chụp từ {local_iso(meta.captured_at, tz)[:10]}, "
                                    f"cũ hơn {age.days} ngày so với lúc sự cố bắt đầu"})
    graph_changed = None
    if seen_version is not None and seen_version != meta.version:
        graph_changed = {"before": seen_version, "now": meta.version}
        warnings.append({"code": "graph_version_changed",
                         "message": f"Sơ đồ đã đổi từ v{seen_version} sang v{meta.version} trong lúc xử lý; kết quả theo v{meta.version}"})

    result = algo.trace(edges, failed)
    rows = result.impacted()
    impacted = [
        {"service_id": s, "name": catalog[s].name if s in catalog else None, "distance": d, "path": p, "path_text": path_text(p)}
        for s, d, p in rows if s in customer_facing
    ]
    reached = {s for s, _, _ in rows}
    status = "incomplete_data" if any(w["code"] in INCOMPLETE for w in warnings) else "ok"
    if failed not in nodes:
        impacted, rows = [], []

    return {
        "incident_id": incident.id,
        "incident_status": incident.status,
        "incident_status_label": INCIDENT_STATUS.get(incident.status, incident.status),
        "system_id": system.id,
        "failed_service": failed,
        "graph_version": meta.version,
        "graph_captured_at": local_iso(meta.captured_at, tz),
        "status": status,
        "impacted": impacted,
        "all_reached": [{"service_id": s, "distance": d, "path_text": path_text(p)} for s, d, p in rows],
        "not_reached": [
            {"service_id": s, "reason": f"Không có đường đi từ {failed} theo sơ đồ v{meta.version}"}
            for s in sorted(customer_facing - reached - set(missing))
        ] if failed in nodes else [],
        "layers": result.layers() if failed in nodes else [],
        "bfs_steps": [
            {"service": v.service, "distance": v.distance, "discovered": v.discovered, "already_seen": v.already_seen}
            for v in result.visits
        ] if failed in nodes else [],
        "duplicate_edges": [{"from": a, "to": b} for a, b in result.duplicate_edges],
        "counts": {"services": len(nodes), "edges": len(edges), "unique_edges": len(set(edges))},
        "warnings": warnings,
        "graph_changed": graph_changed,
        "note": POSSIBLE,
        "rule": RULE,
    }


def note_payload(calc: dict) -> dict:
    """Phần lưu vào đề xuất, để lúc duyệt so với kết quả tính lại."""
    return {
        "incident_id": calc["incident_id"],
        "graph_version": calc["graph_version"],
        "status": calc["status"],
        "impacted": [{"service_id": r["service_id"], "distance": r["distance"], "path": r["path"]} for r in calc["impacted"]],
        "warnings": [w["code"] for w in calc["warnings"]],
    }


# --- Công cụ --------------------------------------------------------------------

def build_tools(ctx: ToolContext) -> list[BaseTool]:
    """Tạo công cụ gắn với database session và run hiện tại."""

    @tool(args_schema=IncidentArgs)
    def get_incident(incident_id: str) -> dict:
        """Đọc thông tin sự cố: hệ thống, dịch vụ bị lỗi, thời điểm bắt đầu, trạng thái."""
        return incident_view(ctx.db, load_incident(ctx.db, incident_id), ctx.tz)

    @tool(args_schema=SystemArgs)
    def get_service_graph(system_id: str) -> dict:
        """Đọc sơ đồ phụ thuộc đang dùng của hệ thống: các cạnh A -> B (B phụ thuộc A) và phiên bản sơ đồ."""
        system = load_system(ctx.db, system_id)
        meta, rows = load_graph(ctx.db, system)
        ctx.seen.setdefault("graph", {})[system_id] = meta.version
        edges = [(e.source, e.target) for e in rows]
        return {
            "system_id": system_id,
            "version": meta.version,
            "captured_at": local_iso(meta.captured_at, ctx.tz),
            "note": meta.note,
            "edges": [{"from": a, "to": b} for a, b in edges],
            "edge_count": len(edges),
            "unique_edge_count": len(set(edges)),
            "services": sorted({x for e in edges for x in e}),
        }

    @tool(args_schema=SystemArgs)
    def get_customer_facing_services(system_id: str) -> dict:
        """Đọc danh sách dịch vụ người dùng trực tiếp thấy (từ danh mục dịch vụ)."""
        load_system(ctx.db, system_id)
        rows = [s for s in services_of(ctx.db, system_id) if s.customer_facing]
        return {"system_id": system_id, "services": [{"service_id": s.id, "name": s.name} for s in rows]}

    @tool(args_schema=IncidentArgs)
    def trace_impact(incident_id: str) -> dict:
        """Chạy BFS từ dịch vụ lỗi của sự cố trên sơ đồ phụ thuộc mới nhất. Công cụ tự đọc lại sự cố, sơ đồ và danh mục.
        Trả dịch vụ người dùng thấy có thể bị ảnh hưởng, đường đi ngắn nhất và số cạnh tới từng dịch vụ,
        cảnh báo khi sơ đồ thiếu/cũ (status incomplete_data) hoặc đã đổi phiên bản so với lúc đọc."""
        incident = load_incident(ctx.db, incident_id)
        seen = ctx.seen.get("graph", {}).get(incident.system_id)
        return run_trace(ctx.db, incident_id, ctx.tz, seen)

    @tool(args_schema=IncidentArgs)
    def propose_impact_note(incident_id: str) -> dict:
        """Tạo đề xuất ghi chú "có thể bị ảnh hưởng" vào sự cố, chờ người trực duyệt. KHÔNG khởi động lại hay sửa dịch vụ.
        Chỉ gọi khi người dùng muốn ghi nhận kết quả vào sự cố."""
        calc = run_trace(ctx.db, incident_id, ctx.tz)
        if calc["incident_status"] == "resolved":
            raise ToolError("incident_resolved", f"Sự cố {incident_id} đã xử lý xong, không ghi thêm đánh giá ảnh hưởng")
        services = ", ".join(r["service_id"] for r in calc["impacted"]) or "không có dịch vụ người dùng thấy"
        proposal, created = create_proposal(
            ctx,
            kind=PROPOSAL_KIND,
            target_id=incident_id,
            payload=note_payload(calc),
            summary=(
                f"Ghi vào {incident_id}: có thể bị ảnh hưởng theo sơ đồ v{calc['graph_version']}: {services}"
                + (" (dữ liệu sơ đồ CHƯA đầy đủ)" if calc["status"] == "incomplete_data" else "")
            ),
        )
        return proposal_view(proposal, created)

    return [
        with_kind(get_incident, "read"),
        with_kind(get_service_graph, "read"),
        with_kind(get_customer_facing_services, "read"),
        with_kind(trace_impact, "algorithm"),
        with_kind(propose_impact_note, "action"),
    ]
