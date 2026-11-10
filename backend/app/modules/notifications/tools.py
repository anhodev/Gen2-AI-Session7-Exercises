"""Bài 03 - Công cụ cho model gọi.

  get_pending_messages(campaign_id)     read       Tin đang chờ gửi, mã tin và mã người nhận
  get_contact_policy(campaign_id)       read       Khung giờ, số tin tối đa mỗi ô, số ô phải cách giữa hai tin cùng khách
  get_opt_in_status(customer_ids)       read       Khách nào đã đồng ý nhận tin, khách nào chưa
  build_send_schedule(campaign_id)      algorithm  Tự đọc lại tin, quy tắc, quyền nhận tin; xếp lịch bằng max-heap + hàng đợi chờ
  propose_send_schedule(campaign_id)    action     Đề xuất chốt lịch, chờ người có quyền duyệt

Không có công cụ gửi tin thật. Công cụ xếp lịch không nhận danh sách khách từ model:
nó tự lấy khách từ tin chờ gửi và kiểm tra lại quyền nhận tin trước khi tính.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import BaseTool, tool
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.proposals import create_proposal, proposal_view
from app.core.tools import ToolArgs, ToolContext, ToolError, with_kind

from . import algo
from .entities import Campaign, ConsentSource, Customer
from .store import pending_messages, slot_times

CAMPAIGN_ID = r"^CP-\d{1,10}$"
CUSTOMER_ID = r"^[A-Z][A-Z0-9-]{0,19}$"

PROPOSAL_KIND = "send_schedule"
OPT_IN_LABEL = {"yes": "đã đồng ý", "no": "đã từ chối", "unknown": "chưa có bản ghi đồng ý", "not_found": "không có trong hệ thống"}
EXCLUDE_REASON = {
    "no": ("opted_out", "Khách đã từ chối nhận tin"),
    "unknown": ("no_consent_record", "Chưa có bản ghi đồng ý nhận tin, coi như chưa đồng ý"),
}
OUT_OF_SLOTS = "Hết khung giờ trong ngày; không tự đẩy sang ngày khác"


def rule_text(gap: int) -> str:
    return (
        f"Mỗi ô gửi tối đa 1 tin. Gửi cho một khách ở ô i thì khách đó nhận tiếp sớm nhất ở ô i+{gap + 1} "
        f"(cách ít nhất {gap} ô). Loại tin của khách chưa đồng ý trước khi xếp. "
        "Ưu tiên khách còn nhiều tin (max-heap); bằng nhau thì theo mã khách alphabet; trong một khách theo mã tin alphabet. "
        "Không khách nào đủ điều kiện thì để idle. Hết ô mà còn tin thì báo chưa xếp được."
    )


class CampaignArgs(ToolArgs):
    campaign_id: str = Field(pattern=CAMPAIGN_ID, description="Mã chiến dịch người dùng nói, vd CP-1")


class OptInArgs(ToolArgs):
    customer_ids: list[Annotated[str, Field(pattern=CUSTOMER_ID)]] = Field(
        min_length=1, max_length=200, description="Mã khách lấy từ get_pending_messages, vd [\"A\", \"B\"]",
    )


# --- Đọc và kiểm tra --------------------------------------------------------

def load_campaign(db: Session, campaign_id: str) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise ToolError("campaign_not_found", f"Không có chiến dịch {campaign_id} trong hệ thống")
    if campaign.max_per_slot != 1:
        raise ToolError(
            "unsupported_policy",
            f"Chiến dịch {campaign_id} cho {campaign.max_per_slot} tin mỗi ô; bài này chỉ hỗ trợ 1 tin mỗi ô",
        )
    return campaign


def opt_in_code(customer: Customer | None) -> str:
    if customer is None:
        return "not_found"
    return {True: "yes", False: "no", None: "unknown"}[customer.opt_in]


def read_consent(db: Session, customer_ids: list[str]) -> dict[str, Customer]:
    """
    Đọc trạng thái đồng ý của các khách từ nguồn dữ liệu của từng khách.

    Raises:
        ToolError: consent_source_unavailable khi nguồn của một khách đang không phản hồi.
            Không trả kết quả một phần: thiếu quyền nhận tin của một khách thì không xếp lịch được.
    """
    ids = sorted(set(customer_ids))
    customers = {c.id: c for c in db.scalars(select(Customer).where(Customer.id.in_(ids)))}
    sources = {s.id: s for s in db.scalars(select(ConsentSource))}
    down: dict[str, list[str]] = {}
    for c in customers.values():
        source = sources.get(c.source_id)
        if source is None or not source.available:
            down.setdefault(c.source_id, []).append(c.id)
    if down:
        names = ", ".join(f"{sources[s].name if s in sources else s} (khách {', '.join(who)})" for s, who in down.items())
        raise ToolError(
            "consent_source_unavailable",
            f"Không đọc được trạng thái đồng ý nhận tin: nguồn {names} đang không phản hồi",
            details={"sources": down},
        )
    return customers


def snapshot(customer: Customer | None) -> dict | None:
    return None if customer is None else {"version": customer.version, "opt_in": opt_in_code(customer)}


def consent_changes(db: Session, seen: dict[str, dict] | None) -> list[dict]:
    """So trạng thái đồng ý AI đã đọc (get_opt_in_status) với dữ liệu hiện tại."""
    if not seen:
        return []
    current = {c.id: c for c in db.scalars(select(Customer).where(Customer.id.in_(list(seen))))}
    changes = []
    for customer_id, before in sorted(seen.items()):
        row = current.get(customer_id)
        if before is None and row is None:
            continue
        if before is None or row is None or row.version != before["version"]:
            changes.append({
                "customer_id": customer_id,
                "before": OPT_IN_LABEL[before["opt_in"]] if before else OPT_IN_LABEL["not_found"],
                "now": OPT_IN_LABEL[opt_in_code(row)],
            })
    return changes


def run_schedule(db: Session, campaign_id: str, seen_opt_in: dict[str, dict] | None = None) -> dict:
    """Đọc lại tin chờ gửi, quy tắc và quyền nhận tin từ database; loại khách chưa đồng ý; xếp lịch."""
    campaign = load_campaign(db, campaign_id)
    rows = pending_messages(db, campaign_id)
    consent = read_consent(db, [m.customer_id for m in rows])
    times = slot_times(campaign)
    titles = {m.id: m.title for m in rows}

    allowed, excluded = [], []
    for m in rows:
        code = opt_in_code(consent.get(m.customer_id))
        if code == "yes":
            allowed.append(algo.Message(m.id, m.customer_id))
        else:
            reason_code, reason = EXCLUDE_REASON.get(code, ("customer_not_found", "Khách không có trong hệ thống"))
            excluded.append({"message_id": m.id, "customer_id": m.customer_id, "title": m.title,
                             "opt_in": code, "reason_code": reason_code, "reason": reason})

    result = algo.build_schedule(allowed, campaign.slot_count, campaign.gap)

    def at(index: int) -> str:
        return times[index][0] if index < len(times) else "sau giờ cuối"

    slots = [
        {"index": s.index, "start": times[s.index][0], "end": times[s.index][1], "state": s.state,
         "message_id": s.message_id, "customer_id": s.customer_id, "title": titles.get(s.message_id)}
        for s in result.slots
    ]
    per_customer: dict[str, list[int]] = {}
    for s in result.slots:
        if s.state == algo.SEND:
            per_customer.setdefault(s.customer_id, []).append(s.index)
    customer_ids = sorted({m.customer_id for m in rows})

    return {
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "send_date": campaign.send_date,
        "policy": {
            "slot_count": campaign.slot_count, "slot_minutes": campaign.slot_minutes, "gap": campaign.gap,
            "max_per_slot": campaign.max_per_slot,
            "window": f"{times[0][0]}-{times[-1][1]}" if times else None,
        },
        "status": result.status,
        "total_pending": len(rows),
        "scheduled_count": result.scheduled_count,
        "idle_count": result.idle_count,
        "unused_count": sum(1 for s in result.slots if s.state == algo.UNUSED),
        "last_send_time": times[result.finish_slot][0] if result.finish_slot is not None else None,
        "slots": slots,
        "unscheduled": [
            {"message_id": m.id, "customer_id": m.customer_id, "title": titles[m.id], "reason": OUT_OF_SLOTS}
            for m in result.unscheduled
        ],
        "excluded": excluded,
        "customers": [
            {"customer_id": c, "opt_in": opt_in_code(consent.get(c)), "slots": per_customer.get(c, []),
             "times": [times[i][0] for i in per_customer.get(c, [])]}
            for c in customer_ids
        ],
        "trace": [
            {"slot": t.slot, "start": at(t.slot),
             "ready": [{"customer_id": c, "remaining": n} for c, n in t.ready],
             "waiting": [{"customer_id": c, "ready_at": i, "ready_time": at(i)} for c, i in t.waiting],
             "picked": t.picked}
            for t in result.trace
        ],
        "violations": algo.check_schedule(result.slots, campaign.gap),
        "data_changed": consent_changes(db, seen_opt_in),
        "customer_versions": {c.id: c.version for c in consent.values()},
        "rule": rule_text(campaign.gap),
    }


def schedule_payload(calc: dict) -> dict:
    """Phần lịch lưu vào đề xuất, để lúc duyệt so với lịch tính lại."""
    return {
        "campaign_id": calc["campaign_id"],
        "send_date": calc["send_date"],
        "gap": calc["policy"]["gap"],
        "schedule": [
            {"slot": s["index"], "start": s["start"], "message_id": s["message_id"], "customer_id": s["customer_id"]}
            for s in calc["slots"] if s["state"] == algo.SEND
        ],
        "unscheduled": [m["message_id"] for m in calc["unscheduled"]],
        "excluded": [m["message_id"] for m in calc["excluded"]],
        "customer_versions": calc["customer_versions"],
    }


# --- Công cụ --------------------------------------------------------------------

def build_tools(ctx: ToolContext) -> list[BaseTool]:
    """Tạo công cụ gắn với database session và run hiện tại."""

    @tool(args_schema=CampaignArgs)
    def get_pending_messages(campaign_id: str) -> dict:
        """Đọc các tin đang chờ gửi của một chiến dịch: mã tin, mã người nhận, tiêu đề."""
        load_campaign(ctx.db, campaign_id)
        rows = pending_messages(ctx.db, campaign_id)
        return {
            "campaign_id": campaign_id,
            "count": len(rows),
            "customer_ids": sorted({m.customer_id for m in rows}),
            "messages": [{"message_id": m.id, "customer_id": m.customer_id, "title": m.title} for m in rows],
        }

    @tool(args_schema=CampaignArgs)
    def get_contact_policy(campaign_id: str) -> dict:
        """Đọc quy tắc liên hệ của chiến dịch: các khung giờ được dùng, số tin tối đa mỗi khung,
        số ô phải cách giữa hai tin cho cùng khách (gap)."""
        campaign = load_campaign(ctx.db, campaign_id)
        times = slot_times(campaign)
        return {
            "campaign_id": campaign_id,
            "name": campaign.name,
            "send_date": campaign.send_date,
            "slots": [{"index": i, "start": s, "end": e} for i, (s, e) in enumerate(times)],
            "max_per_slot": campaign.max_per_slot,
            "gap": campaign.gap,
            "rule": rule_text(campaign.gap),
        }

    @tool(args_schema=OptInArgs)
    def get_opt_in_status(customer_ids: list[str]) -> dict:
        """Đọc trạng thái đồng ý nhận tin của các khách (từ nguồn dữ liệu đồng ý, vd CRM)."""
        customers = read_consent(ctx.db, customer_ids)
        seen = ctx.seen.setdefault("opt_in", {})
        statuses = []
        for customer_id in sorted(set(customer_ids)):
            row = customers.get(customer_id)
            seen[customer_id] = snapshot(row)
            code = opt_in_code(row)
            statuses.append({"customer_id": customer_id, "opt_in": code, "label": OPT_IN_LABEL[code]})
        return {
            "statuses": statuses,
            "allowed": [s["customer_id"] for s in statuses if s["opt_in"] == "yes"],
            "not_allowed": [s["customer_id"] for s in statuses if s["opt_in"] != "yes"],
        }

    @tool(args_schema=CampaignArgs)
    def build_send_schedule(campaign_id: str) -> dict:
        """Chạy thuật toán xếp lịch gửi (max-heap + hàng đợi chờ) cho chiến dịch. Công cụ tự đọc lại tin chờ gửi,
        quy tắc liên hệ và kiểm tra lại quyền nhận tin; tin của khách chưa đồng ý bị loại trước khi xếp.
        Trả lịch từng ô (gửi/idle/trống), tin chưa xếp được, tin bị loại, các bước chọn khách.
        Đây là lịch đề xuất, chưa gửi tin nào."""
        return run_schedule(ctx.db, campaign_id, ctx.seen.get("opt_in"))

    @tool(args_schema=CampaignArgs)
    def propose_send_schedule(campaign_id: str) -> dict:
        """Tạo đề xuất chốt lịch gửi của chiến dịch, chờ người có quyền duyệt. KHÔNG gửi tin.
        Chỉ gọi khi người dùng muốn gửi hoặc chốt lịch."""
        calc = run_schedule(ctx.db, campaign_id)
        if calc["scheduled_count"] == 0:
            raise ToolError("nothing_to_schedule", f"Chiến dịch {campaign_id} không có tin nào xếp được để đề xuất",
                            details={"status": calc["status"]})
        window = calc["policy"]["window"]
        proposal, created = create_proposal(
            ctx,
            kind=PROPOSAL_KIND,
            target_id=campaign_id,
            payload=schedule_payload(calc),
            summary=(
                f"Chốt lịch gửi {campaign_id} ngày {calc['send_date']}: {calc['scheduled_count']} tin trong "
                f"{calc['policy']['slot_count']} ô ({window}), {calc['idle_count']} ô idle"
                + (f", {len(calc['unscheduled'])} tin chưa xếp được" if calc["unscheduled"] else "")
                + (f", loại {len(calc['excluded'])} tin của khách chưa đồng ý" if calc["excluded"] else "")
            ),
        )
        return {**proposal_view(proposal, created), "sent": 0}

    return [
        with_kind(get_pending_messages, "read"),
        with_kind(get_contact_policy, "read"),
        with_kind(get_opt_in_status, "read"),
        with_kind(build_send_schedule, "algorithm"),
        with_kind(propose_send_schedule, "action"),
    ]
