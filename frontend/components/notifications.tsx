"use client";

// Bài 03 - Lịch gửi thông báo: chat bên trái; bên phải là lịch từng ô (gồm ô idle), quy tắc liên hệ,
// trạng thái đồng ý, các bước chọn khách của max-heap, và dữ liệu trong hệ thống (có nút đổi trạng thái đồng ý,
// bật/tắt nguồn dữ liệu để thử ca dữ liệu đổi và công cụ đọc bị lỗi).
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, BellRing, CalendarClock, CheckCircle2, Layers, Loader2, RotateCcw, SearchX, ShieldCheck } from "lucide-react";
import { ApiError, api } from "@/lib/api";
import type { NotificationData, OptIn, RunDetail, SampleQuestion, ScheduleResult, ToolFailure } from "@/lib/types";
import { ChatPanel } from "./chat";
import { Empty, PanelHeader } from "./ui";

const OPT_IN: Record<OptIn, [string, string]> = {
  yes: ["Đã đồng ý", "green"],
  no: ["Đã từ chối", "red"],
  unknown: ["Chưa có bản ghi", "amber"],
  not_found: ["Không có khách", "gray"],
};

const READ_TOOLS = ["get_pending_messages", "get_contact_policy", "get_opt_in_status"];

/** Màu riêng cho từng khách trong lịch, theo thứ tự mã khách. */
function colorOf(customers: string[], id: string | null) {
  const i = id ? customers.indexOf(id) : -1;
  return i < 0 ? "" : `c${i % 6}`;
}

export function NotificationsPage() {
  const [samples, setSamples] = useState<SampleQuestion[]>([]);
  const [data, setData] = useState<NotificationData | null>(null);
  const [latest, setLatest] = useState<RunDetail | null>(null);
  const [syncKey, setSyncKey] = useState(0);

  const loadData = useCallback(() => { api.notificationData().then(setData).catch(() => {}); }, []);

  useEffect(() => {
    api.notificationSamples().then(setSamples).catch(() => {});
    loadData();
  }, [loadData]);

  return (
    <div className="chat-layout">
      <ChatPanel
        module="notifications"
        title="Trợ lý marketing"
        placeholder="Ví dụ: Chiến dịch CP-1 hôm nay nên gửi giờ nào?"
        samples={samples}
        onRun={(run) => { setLatest(run); loadData(); }}
        onDecided={loadData}
        syncKey={syncKey}
      />
      <div className="side-stack">
        <UsedDataPanel run={latest} />
        <SystemDataPanel
          data={data}
          run={latest}
          onChanged={loadData}
          onReset={() => { loadData(); setSyncKey((k) => k + 1); }}
        />
      </div>
    </div>
  );
}

/** Kết quả công cụ build_send_schedule của câu hỏi gần nhất. */
function UsedDataPanel({ run }: { run: RunDetail | null }) {
  const calls = run?.tool_calls ?? [];
  const scheduleCall = [...calls].reverse().find((c) => c.name === "build_send_schedule");
  const schedule = scheduleCall?.ok ? (scheduleCall.result as ScheduleResult) : null;
  const failures = calls.filter((c) => !c.ok && c.error).map((c) => c.error as ToolFailure);
  const uniqueFailures = failures.filter((f, i) => failures.findIndex((x) => x.message === f.message) === i);
  const hasReads = calls.some((c) => READ_TOOLS.includes(c.name));

  return (
    <section className="panel">
      <PanelHeader
        step={1}
        title="Dữ liệu AI đã dùng"
        subtitle={run ? `Lần xử lý #${run.id}: "${run.question}"` : "Kết quả công cụ của câu hỏi gần nhất."}
      />
      <div className="panel-body">
        {!run && <Empty icon={BellRing} text="Hỏi về một chiến dịch để xem lịch gửi từng ô ở đây." />}
        {run && !hasReads && <Empty text="Câu hỏi này chưa gọi công cụ nào (AI đang hỏi lại thông tin còn thiếu)." />}
        {uniqueFailures.map((f) => (
          <div className="result-card warn" key={f.code + f.message}>
            <AlertTriangle size={17} />
            <div>
              <strong>Công cụ báo lỗi: {f.code}</strong>
              <span>{f.message}</span>
              {f.code === "consent_source_unavailable" && <span>Không kiểm tra được quyền nhận tin nên không xếp lịch.</span>}
            </div>
          </div>
        ))}
        {schedule && <ScheduleView calc={schedule} />}
      </div>
    </section>
  );
}

function ScheduleView({ calc }: { calc: ScheduleResult }) {
  const customers = calc.customers.map((c) => c.customer_id);
  const receivers = calc.customers.filter((c) => c.slots.length > 0);
  const p = calc.policy;

  return (
    <>
      <div className="invoice-line">
        <span><b>{calc.campaign_id}</b> · {calc.campaign_name} · {calc.send_date}</span>
        <strong>{calc.scheduled_count}/{calc.total_pending} tin xếp được</strong>
      </div>

      <div className="policy-chips">
        <span><CalendarClock size={12} /> {p.slot_count} ô {p.window} · {p.slot_minutes} phút/ô</span>
        <span>Tối đa {p.max_per_slot} tin/ô</span>
        <span>gap = {p.gap} → nhận tiếp sớm nhất ở ô i+{p.gap + 1}</span>
      </div>

      <ResultCard calc={calc} />

      {calc.data_changed.length > 0 && (
        <div className="result-card warn">
          <AlertTriangle size={17} />
          <div>
            <strong>Trạng thái đồng ý đã đổi sau khi AI đọc</strong>
            {calc.data_changed.map((c) => <span key={c.customer_id}>Khách {c.customer_id}: {c.before} → {c.now}</span>)}
            <span>Lịch trên tính theo dữ liệu mới nhất.</span>
          </div>
        </div>
      )}

      <div>
        <h4 className="mini-heading"><ShieldCheck size={13} /> Quyền nhận tin (kiểm tra lại trước khi xếp)</h4>
        <div className="consent-list">
          {calc.customers.map((c) => {
            const [label, tone] = OPT_IN[c.opt_in];
            return <span key={c.customer_id} className={`pill ${tone}`}>{c.customer_id}: {label}</span>;
          })}
        </div>
      </div>

      {calc.slots.length > 0 && (
        <div>
          <h4 className="mini-heading"><CalendarClock size={13} /> Lịch đề xuất từng ô</h4>
          <div className="table-wrap">
            <table className="data-table compact slot-grid">
              <thead>
                <tr><th>Ô</th>{calc.slots.map((s) => <th key={s.index}>{s.index}<small>{s.start}</small></th>)}</tr>
              </thead>
              <tbody>
                <tr className="slot-result">
                  <td>Kết quả</td>
                  {calc.slots.map((s) => (
                    <td key={s.index} title={s.title ?? undefined}>
                      {s.state === "send"
                        ? <span className={`slot-chip ${colorOf(customers, s.customer_id)}`}>{s.message_id}</span>
                        : <span className={`slot-chip ${s.state}`}>{s.state === "idle" ? "idle" : "trống"}</span>}
                    </td>
                  ))}
                </tr>
                {receivers.map((c) => (
                  <tr key={c.customer_id}>
                    <td>Khách {c.customer_id}</td>
                    {calc.slots.map((s) => (
                      <td key={s.index}>{s.customer_id === c.customer_id && <span className={`slot-dot ${colorOf(customers, c.customer_id)}`} />}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {receivers.length > 0 && (
            <p className="hint">
              {receivers.map((c) => `${c.customer_id} nhận ở ô ${c.slots.join(", ")}`).join("; ")}.
              {calc.violations.length === 0 ? " Không ai nhận hai tin quá gần nhau." : ` Vi phạm: ${calc.violations.join("; ")}`}
            </p>
          )}
        </div>
      )}

      {calc.excluded.length > 0 && (
        <div>
          <h4 className="mini-heading">Loại trước khi xếp</h4>
          <ul className="excluded-list">
            {calc.excluded.map((m) => (
              <li key={m.message_id}><b>{m.message_id}</b> khách {m.customer_id}<em>{m.reason}</em></li>
            ))}
          </ul>
        </div>
      )}

      {calc.unscheduled.length > 0 && (
        <div>
          <h4 className="mini-heading">Chưa xếp được</h4>
          <ul className="excluded-list">
            {calc.unscheduled.map((m) => (
              <li key={m.message_id}><b>{m.message_id}</b> khách {m.customer_id}<em>{m.reason}</em></li>
            ))}
          </ul>
        </div>
      )}

      {calc.trace.length > 0 && calc.scheduled_count > 0 && (
        <div>
          <h4 className="mini-heading"><Layers size={13} /> Các bước chọn khách (max-heap + hàng đợi chờ)</h4>
          <div className="table-wrap">
            <table className="data-table compact">
              <thead><tr><th>Ô</th><th>Sẵn sàng (heap)</th><th>Đang chờ</th><th>Chọn</th></tr></thead>
              <tbody>
                {calc.trace.map((t) => (
                  <tr key={t.slot}>
                    <td><b>{t.slot}</b><small>{t.start}</small></td>
                    <td>{t.ready.length ? t.ready.map((r) => `${r.customer_id}(${r.remaining})`).join(", ") : <span className="muted">trống</span>}</td>
                    <td className="muted">{t.waiting.length ? t.waiting.map((w) => `${w.customer_id} → ô ${w.ready_at}`).join(", ") : "-"}</td>
                    <td>
                      {t.picked
                        ? <span className={`slot-chip ${colorOf(customers, t.picked)}`}>{t.picked}</span>
                        : <span className="slot-chip idle">idle</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="hint">Số trong ngoặc là số tin còn lại. Khách còn nhiều tin đứng đầu heap; bằng nhau thì theo mã khách.</p>
        </div>
      )}

      <p className="hint rule">Quy tắc: {calc.rule}</p>
    </>
  );
}

function ResultCard({ calc }: { calc: ScheduleResult }) {
  if (calc.status === "no_messages") {
    return (
      <div className="result-card warn">
        <SearchX size={17} />
        <div>
          <strong>Không còn tin nào để xếp</strong>
          <span>{calc.excluded.length ? "Mọi tin chờ gửi đều thuộc khách chưa đồng ý nhận tin." : "Chiến dịch không còn tin chờ gửi."}</span>
        </div>
      </div>
    );
  }
  const partial = calc.status === "partial";
  return (
    <div className={`result-card ${partial ? "warn" : "ok"}`}>
      {partial ? <AlertTriangle size={17} /> : <CheckCircle2 size={17} />}
      <div>
        <strong>
          {partial
            ? `Hết khung giờ: còn ${calc.unscheduled.length} tin chưa xếp được`
            : `Xếp hết ${calc.scheduled_count} tin, tin cuối lúc ${calc.last_send_time}`}
        </strong>
        <span>
          {calc.scheduled_count} ô gửi, {calc.idle_count} ô idle
          {calc.unused_count ? `, ${calc.unused_count} ô cuối để trống` : ""}. Đây là lịch đề xuất, chưa gửi tin nào.
        </span>
      </div>
    </div>
  );
}

/** Chiến dịch, tin, khách, nguồn đồng ý đang có trong database. */
function SystemDataPanel({ data, run, onChanged, onReset }: {
  data: NotificationData | null; run: RunDetail | null; onChanged: () => void; onReset: () => void;
}) {
  const [campaign, setCampaign] = useState("CP-1");
  const [tab, setTab] = useState<"messages" | "customers" | "sources">("messages");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  // Theo chiến dịch của câu hỏi gần nhất; thông báo chỉ còn tới câu hỏi kế tiếp
  const runCampaign = (run?.tool_calls.find((c) => c.name === "get_pending_messages")?.args as { campaign_id?: string })?.campaign_id;
  useEffect(() => {
    setMessage("");
    if (runCampaign && data?.campaigns.some((c) => c.campaign_id === runCampaign)) setCampaign(runCampaign);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id]);

  const info = data?.campaigns.find((c) => c.campaign_id === campaign);
  const messages = data?.messages.filter((m) => m.campaign_id === campaign) ?? [];
  const customerIds = new Set(messages.map((m) => m.customer_id));
  const customers = data?.customers.filter((c) => customerIds.has(c.customer_id)) ?? [];
  const sourceName = (id: string) => data?.sources.find((s) => s.source_id === id)?.name ?? id;
  const sourceDown = (id: string) => data?.sources.find((s) => s.source_id === id)?.available === false;

  const act = async (key: string, fn: () => Promise<string>) => {
    setBusy(key);
    setMessage("");
    try {
      setMessage(await fn());
      onChanged();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Không thực hiện được.");
    } finally {
      setBusy(null);
    }
  };

  const changeConsent = (id: string, value: string) => act(id, async () => {
    const optIn = value === "yes" ? true : value === "no" ? false : null;
    const result = await api.changeConsent(id, optIn);
    return `Khách ${id}: ${OPT_IN[result.opt_in as OptIn][0]} (phiên bản ${result.version}). `
      + "Đề xuất chốt lịch tạo trước đó sẽ bị chặn khi duyệt; hỏi lại để AI xếp theo dữ liệu mới.";
  });

  const toggleSource = (id: string, available: boolean) => act(id, async () => {
    await api.changeSource(id, available);
    return available ? `Nguồn ${sourceName(id)} đã hoạt động lại.` : `Nguồn ${sourceName(id)} đang giả lập lỗi: công cụ đọc quyền nhận tin sẽ báo lỗi.`;
  });

  const reset = () => act("reset", async () => {
    const result = await api.resetNotifications();
    onReset();
    return result.closed_proposals
      ? `Đã khôi phục dữ liệu mẫu và đóng ${result.closed_proposals} đề xuất đang chờ.`
      : "Đã khôi phục dữ liệu mẫu.";
  });

  return (
    <section className="panel">
      <PanelHeader
        step={2}
        title="Dữ liệu trong hệ thống"
        subtitle="Dữ liệu giả. Công cụ chỉ đọc từ đây; nút đổi đồng ý và bật/tắt nguồn là thao tác của người dùng, AI không gọi được."
        action={(
          <button className="secondary-button" onClick={reset} disabled={busy !== null}>
            {busy === "reset" ? <Loader2 size={14} className="spin" /> : <RotateCcw size={14} />} Khôi phục dữ liệu mẫu
          </button>
        )}
      />
      {message && <p className="panel-note">{message}</p>}

      <div className="line-picker">
        {data?.campaigns.map((c) => (
          <button key={c.campaign_id} className={campaign === c.campaign_id ? "active" : ""} onClick={() => setCampaign(c.campaign_id)} title={c.name}>
            {c.campaign_id}
          </button>
        ))}
      </div>
      {info && (
        <p className="shift-list">
          <span><b>{info.name}</b></span>
          <span>{info.send_date} · {info.slot_count} ô từ {info.first_slot} · {info.slot_minutes} phút/ô · gap {info.gap}</span>
        </p>
      )}

      <div className="tabs">
        <button className={tab === "messages" ? "active" : ""} onClick={() => setTab("messages")}>Tin ({messages.length})</button>
        <button className={tab === "customers" ? "active" : ""} onClick={() => setTab("customers")}>Khách ({customers.length})</button>
        <button className={tab === "sources" ? "active" : ""} onClick={() => setTab("sources")}>Nguồn đồng ý ({data?.sources.length ?? 0})</button>
      </div>

      {!data ? <Empty text="Đang tải dữ liệu…" /> : tab === "messages" ? (
        <div className="table-wrap">
          <table className="data-table compact">
            <thead><tr><th>Tin</th><th>Khách</th><th>Trạng thái</th></tr></thead>
            <tbody>
              {messages.map((m) => (
                <tr key={m.message_id}>
                  <td><b>{m.message_id}</b><small>{m.title}</small></td>
                  <td>{m.customer_id}</td>
                  <td>
                    {m.status === "scheduled"
                      ? <span className="pill green">Đã chốt {m.scheduled_at?.slice(11)}</span>
                      : <span className="pill gray">Chờ xếp</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : tab === "customers" ? (
        <div className="table-wrap">
          <table className="data-table compact">
            <thead><tr><th>Khách</th><th>Nguồn</th><th>Đồng ý nhận tin</th><th>Phiên bản</th></tr></thead>
            <tbody>
              {customers.map((c) => {
                const [, tone] = OPT_IN[c.opt_in];
                return (
                  <tr key={c.customer_id}>
                    <td><b>{c.customer_id}</b><small>{c.name}</small></td>
                    <td>{c.source_id}{sourceDown(c.source_id) && <small className="text-red">không phản hồi</small>}</td>
                    <td>
                      <select
                        className={`status-select ${tone}`} value={c.opt_in} disabled={busy !== null}
                        aria-label={`Đồng ý nhận tin của khách ${c.customer_id}`}
                        onChange={(e) => changeConsent(c.customer_id, e.target.value)}
                      >
                        <option value="yes">Đã đồng ý</option>
                        <option value="no">Đã từ chối</option>
                        <option value="unknown">Chưa có bản ghi</option>
                      </select>
                    </td>
                    <td className="muted">v{c.version}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table compact">
            <thead><tr><th>Nguồn</th><th>Trạng thái</th><th></th></tr></thead>
            <tbody>
              {data.sources.map((s) => (
                <tr key={s.source_id}>
                  <td><b>{s.source_id}</b><small>{s.name}</small></td>
                  <td>{s.available ? <span className="pill green">Hoạt động</span> : <span className="pill red">Không phản hồi</span>}</td>
                  <td>
                    <button className="secondary-button small" disabled={busy !== null} onClick={() => toggleSource(s.source_id, !s.available)}>
                      {busy === s.source_id && <Loader2 size={12} className="spin" />}
                      {s.available ? "Giả lập lỗi" : "Bật lại"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
