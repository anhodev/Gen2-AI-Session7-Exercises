"use client";

// Bài 02 - Công suất máy: chat bên trái; bên phải là kết quả tính (phép tính từng lô, các bước tìm kiếm nhị phân,
// máy đạt/quá chậm) và dữ liệu trong hệ thống, có nút đổi máy để thử ca "dữ liệu đổi sau khi AI đọc".
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Factory, Gauge, Loader2, Minus, Plus, RotateCcw, SearchX, Split } from "lucide-react";
import { ApiError, api } from "@/lib/api";
import type { CapacityData, MachineChange, MachineStatus, MachineView, RateResult, RunDetail, SampleQuestion, ToolFailure } from "@/lib/types";
import { ChatPanel } from "./chat";
import { Empty, PanelHeader } from "./ui";

const MACHINE_STATUS: Record<MachineStatus, [string, string]> = {
  available: ["Rảnh", "green"],
  busy: ["Đang chạy", "blue"],
  maintenance: ["Bảo trì", "gray"],
  reserved: ["Đã đặt", "amber"],
};

const READ_TOOLS = ["get_open_batches", "get_shift_hours", "get_available_machines"];

export function CapacityPage() {
  const [samples, setSamples] = useState<SampleQuestion[]>([]);
  const [data, setData] = useState<CapacityData | null>(null);
  const [latest, setLatest] = useState<RunDetail | null>(null);
  const [syncKey, setSyncKey] = useState(0);

  const loadData = useCallback(() => { api.capacityData().then(setData).catch(() => {}); }, []);

  useEffect(() => {
    api.capacitySamples().then(setSamples).catch(() => {});
    loadData();
  }, [loadData]);

  return (
    <div className="chat-layout">
      <ChatPanel
        module="capacity"
        title="Trợ lý trưởng ca"
        placeholder="Ví dụ: Dây chuyền L-1 ca CA-1 cần máy nào? Đặt máy luôn"
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

/** Kết quả công cụ calculate_min_required_rate của câu hỏi gần nhất. */
function UsedDataPanel({ run }: { run: RunDetail | null }) {
  const calls = run?.tool_calls ?? [];
  const calcCall = [...calls].reverse().find((c) => c.name === "calculate_min_required_rate");
  const calc = calcCall?.ok ? (calcCall.result as RateResult) : null;
  const failures = [...calls].filter((c) => !c.ok && c.error).map((c) => c.error as ToolFailure);
  // Lỗi đọc trùng nhau (cùng dây chuyền sai) chỉ hiện một lần
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
        {!run && <Empty icon={Factory} text="Hỏi về một dây chuyền và ca để xem phép tính tốc độ tối thiểu ở đây." />}
        {run && !hasReads && <Empty text="Câu hỏi này chưa gọi công cụ nào (AI đang hỏi lại thông tin còn thiếu)." />}
        {uniqueFailures.map((f) => (
          <div className="result-card warn" key={f.code + f.message}>
            <AlertTriangle size={17} />
            <div><strong>Công cụ báo lỗi: {f.code}</strong><span>{f.message}</span></div>
          </div>
        ))}
        {calc && <RateView calc={calc} />}
      </div>
    </section>
  );
}

function RateView({ calc }: { calc: RateResult }) {
  const at = calc.check_at_min;
  const below = calc.check_below_min;
  const machines = [...calc.fast_enough, ...calc.too_slow].sort((a, b) => a.rate_per_hour - b.rate_per_hour);

  return (
    <>
      <div className="invoice-line">
        <span><b>{calc.line_id}</b> · ca {calc.shift_id} ({calc.shift_name}) · còn {calc.hours_left} giờ</span>
        {calc.min_rate !== null && <strong>Tối thiểu {calc.min_rate} sp/giờ</strong>}
      </div>

      <ResultCard calc={calc} />

      {calc.data_changed.length > 0 && (
        <div className="result-card warn">
          <AlertTriangle size={17} />
          <div>
            <strong>Dữ liệu máy đã đổi sau khi AI đọc</strong>
            {calc.data_changed.map((c) => <span key={c.machine_id}>{c.machine_id}: {c.before} → {c.now}</span>)}
            <span>Kết quả trên tính theo dữ liệu mới nhất.</span>
          </div>
        </div>
      )}

      {calc.batches.length > 0 && (
        <div>
          <h4 className="mini-heading"><Factory size={13} /> Giờ cần cho từng lô = ⌈số lượng / tốc độ⌉</h4>
          <div className="table-wrap">
            <table className="data-table compact">
              <thead>
                <tr>
                  <th>Lô</th><th>Số lượng</th>
                  {at && <th>Ở {at.rate} sp/giờ</th>}
                  {below && <th>Ở {below.rate} sp/giờ</th>}
                </tr>
              </thead>
              <tbody>
                {calc.batches.map((b, i) => (
                  <tr key={b.batch_id}>
                    <td><b>{b.batch_id}</b><small>{b.product}</small></td>
                    <td className="amount">{b.quantity}</td>
                    {at && <td className="amount">{at.hours_per_batch[i]} giờ</td>}
                    {below && <td className="amount muted">{below.hours_per_batch[i]} giờ</td>}
                  </tr>
                ))}
                {calc.zero_batches.map((b) => (
                  <tr key={b.batch_id} className="skipped">
                    <td><b>{b.batch_id}</b><small>{b.product}</small></td>
                    <td className="amount">0</td>
                    {at && <td colSpan={below ? 2 : 1} className="muted">Bỏ qua</td>}
                  </tr>
                ))}
              </tbody>
              {at && (
                <tfoot>
                  <tr>
                    <td>Tổng</td><td className="muted">≤ {calc.hours_left} giờ?</td>
                    <td className="amount"><CheckMark ok={at.fits} /> {at.total_hours} giờ</td>
                    {below && <td className="amount"><CheckMark ok={below.fits} /> {below.total_hours} giờ</td>}
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </div>
      )}

      {calc.search_steps.length > 0 && (
        <div>
          <h4 className="mini-heading"><Split size={13} /> Tìm kiếm nhị phân ({calc.search_steps.length} lần thử)</h4>
          <div className="table-wrap">
            <table className="data-table compact">
              <thead><tr><th>#</th><th>Khoảng</th><th>Thử</th><th>Tổng giờ</th><th>Kết quả</th></tr></thead>
              <tbody>
                {calc.search_steps.map((s, i) => (
                  <tr key={i}>
                    <td>{i + 1}</td>
                    <td className="muted">[{s.low}, {s.high}]</td>
                    <td className="amount"><b>{s.mid}</b></td>
                    <td className="amount">{s.hours}</td>
                    <td>
                      {s.fits
                        ? <span className="step-result ok">Kịp → tìm ≤ {s.mid}</span>
                        : <span className="step-result no">Không kịp → tìm ≥ {s.mid + 1}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {calc.min_rate !== null && (
        <div>
          <h4 className="mini-heading"><Gauge size={13} /> Máy rảnh trên {calc.line_id}</h4>
          {machines.length === 0 ? <p className="hint">Không có máy nào đang rảnh.</p> : (
            <div className="table-wrap">
              <table className="data-table compact">
                <thead><tr><th>Máy</th><th>Tốc độ</th><th>Giờ cần</th><th>Đánh giá</th></tr></thead>
                <tbody>
                  {machines.map((m) => <MachineRow key={m.machine_id} machine={m} calc={calc} />)}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <p className="hint rule">Quy tắc: {calc.rule}</p>
    </>
  );
}

function ResultCard({ calc }: { calc: RateResult }) {
  const chosen = calc.chosen_machine;
  if (calc.status === "ok" && chosen) {
    return (
      <div className="result-card ok">
        <CheckCircle2 size={17} />
        <div>
          <strong>Chọn {chosen.machine_id}: {chosen.rate_per_hour} sp/giờ, cần {chosen.hours_needed}/{calc.hours_left} giờ</strong>
          <span>{calc.reason}.</span>
        </div>
      </div>
    );
  }
  const title = {
    no_open_batches: "Không còn lô nào cần làm",
    impossible_under_rules: "Không thể kịp theo quy tắc",
    no_machine_fast_enough: `Thiếu công suất: cần ${calc.min_rate} sp/giờ, ca CHƯA khả thi`,
    ok: "",
  }[calc.status];
  return (
    <div className={`result-card ${calc.status === "no_open_batches" ? "ok" : "warn"}`}>
      {calc.status === "no_open_batches" ? <CheckCircle2 size={17} /> : <SearchX size={17} />}
      <div><strong>{title}</strong><span>{calc.reason}.</span></div>
    </div>
  );
}

function MachineRow({ machine, calc }: { machine: MachineView; calc: RateResult }) {
  const chosen = machine.machine_id === calc.chosen_machine?.machine_id;
  const fast = calc.fast_enough.some((m) => m.machine_id === machine.machine_id);
  return (
    <tr className={chosen ? "picked" : ""}>
      <td><b>{machine.machine_id}</b><small>{machine.name}</small></td>
      <td className="amount">{machine.rate_per_hour}</td>
      <td className="amount">{machine.hours_needed ?? "-"} giờ</td>
      <td>
        {chosen ? <span className="pill green">Chọn · chậm nhất vẫn đạt</span>
          : fast ? <span className="pill blue">Đạt, nhanh hơn mức cần</span>
            : <span className="pill red">Quá chậm</span>}
      </td>
    </tr>
  );
}

function CheckMark({ ok }: { ok: boolean }) {
  return <span className={`check-mark ${ok ? "ok" : "no"}`}>{ok ? "✓" : "✗"}</span>;
}

/** Dây chuyền, ca, lô, máy đang có trong database. Có nút đổi máy để thử dữ liệu thay đổi. */
function SystemDataPanel({ data, run, onChanged, onReset }: {
  data: CapacityData | null; run: RunDetail | null; onChanged: () => void; onReset: () => void;
}) {
  const [line, setLine] = useState("L-1");
  const [tab, setTab] = useState<"machines" | "batches">("machines");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  // Theo dây chuyền của câu hỏi gần nhất; thông báo chỉ còn tới câu hỏi kế tiếp
  const runLine = (run?.tool_calls.find((c) => READ_TOOLS.includes(c.name))?.args as { line_id?: string })?.line_id;
  useEffect(() => {
    setMessage("");
    if (runLine && data?.lines.some((l) => l.line_id === runLine)) setLine(runLine);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id]);

  const calcCall = [...(run?.tool_calls ?? [])].reverse().find((c) => c.name === "calculate_min_required_rate" && c.ok);
  const chosenId = (calcCall?.result as RateResult | undefined)?.chosen_machine?.machine_id;

  const shifts = data?.shifts.filter((s) => s.line_id === line) ?? [];
  const batches = data?.batches.filter((b) => b.line_id === line) ?? [];
  const machines = data?.machines.filter((m) => m.line_id === line) ?? [];

  const change = async (id: string, body: MachineChange, label: string) => {
    setBusy(id);
    setMessage("");
    try {
      const result = await api.changeMachine(id, body);
      setMessage(`${id}: ${label} (phiên bản ${result.version}). Đề xuất đặt máy tạo trước đó sẽ bị chặn khi duyệt; hỏi lại để AI tính theo dữ liệu mới.`);
      onChanged();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Không đổi được máy.");
    } finally {
      setBusy(null);
    }
  };

  const reset = async () => {
    setBusy("reset");
    setMessage("");
    try {
      const result = await api.resetCapacity();
      setMessage(result.closed_proposals
        ? `Đã khôi phục dữ liệu mẫu và đóng ${result.closed_proposals} đề xuất đang chờ.`
        : "Đã khôi phục dữ liệu mẫu.");
      onReset();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Không khôi phục được dữ liệu.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="panel">
      <PanelHeader
        step={2}
        title="Dữ liệu trong hệ thống"
        subtitle="Dữ liệu giả. Công cụ chỉ đọc từ đây; nút đổi máy là thao tác của người dùng, AI không gọi được."
        action={(
          <button className="secondary-button" onClick={reset} disabled={busy !== null}>
            {busy === "reset" ? <Loader2 size={14} className="spin" /> : <RotateCcw size={14} />} Khôi phục dữ liệu mẫu
          </button>
        )}
      />
      {message && <p className="panel-note">{message}</p>}

      <div className="line-picker">
        {data?.lines.map((l) => (
          <button key={l.line_id} className={line === l.line_id ? "active" : ""} onClick={() => setLine(l.line_id)} title={l.name}>
            {l.line_id}
          </button>
        ))}
      </div>
      {shifts.length > 0 && (
        <p className="shift-list">
          {shifts.map((s) => <span key={s.shift_id}><b>{s.shift_id}</b> {s.name} · còn {s.hours_left} giờ</span>)}
        </p>
      )}

      <div className="tabs">
        <button className={tab === "machines" ? "active" : ""} onClick={() => setTab("machines")}>Máy ({machines.length})</button>
        <button className={tab === "batches" ? "active" : ""} onClick={() => setTab("batches")}>Lô hàng ({batches.length})</button>
      </div>

      {!data ? <Empty text="Đang tải dữ liệu…" /> : tab === "machines" ? (
        <div className="table-wrap">
          <table className="data-table compact">
            <thead><tr><th>Máy</th><th>Tốc độ (sp/giờ)</th><th>Trạng thái</th><th>Phiên bản</th></tr></thead>
            <tbody>
              {machines.map((m) => {
                const [label, tone] = MACHINE_STATUS[m.status] ?? [m.status, "gray"];
                const disabled = busy !== null;
                return (
                  <tr key={m.machine_id} className={m.machine_id === chosenId ? "picked" : ""}>
                    <td><b>{m.machine_id}</b><small>{m.name}</small></td>
                    <td>
                      <div className="rate-stepper">
                        <button
                          aria-label={`Giảm tốc ${m.machine_id}`} disabled={disabled || m.rate_per_hour <= 1}
                          onClick={() => change(m.machine_id, { rate_per_hour: m.rate_per_hour - 1 }, `${m.rate_per_hour} → ${m.rate_per_hour - 1} sp/giờ`)}
                        ><Minus size={12} /></button>
                        <b>{busy === m.machine_id ? <Loader2 size={12} className="spin" /> : m.rate_per_hour}</b>
                        <button
                          aria-label={`Tăng tốc ${m.machine_id}`} disabled={disabled}
                          onClick={() => change(m.machine_id, { rate_per_hour: m.rate_per_hour + 1 }, `${m.rate_per_hour} → ${m.rate_per_hour + 1} sp/giờ`)}
                        ><Plus size={12} /></button>
                      </div>
                    </td>
                    <td>
                      <select
                        className={`status-select ${tone}`} value={m.status} disabled={disabled}
                        aria-label={`Trạng thái ${m.machine_id}`}
                        onChange={(e) => {
                          const next = e.target.value as MachineChange["status"];
                          change(m.machine_id, { status: next }, `${label} → ${MACHINE_STATUS[next as MachineStatus][0]}`);
                        }}
                      >
                        <option value="available">Rảnh</option>
                        <option value="busy">Đang chạy</option>
                        <option value="maintenance">Bảo trì</option>
                        {m.status === "reserved" && <option value="reserved" disabled>Đã đặt cho {m.reserved_shift_id}</option>}
                      </select>
                    </td>
                    <td className="muted">v{m.version}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table compact">
            <thead><tr><th>Lô</th><th>Sản phẩm</th><th>Số lượng</th><th>Trạng thái</th></tr></thead>
            <tbody>
              {batches.map((b) => (
                <tr key={b.batch_id} className={b.status === "done" ? "skipped" : ""}>
                  <td><b>{b.batch_id}</b></td>
                  <td>{b.product}</td>
                  <td className="amount">{b.quantity}</td>
                  <td>{b.status === "open" ? <span className="pill blue">Chưa làm</span> : <span className="pill gray">Đã xong</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
