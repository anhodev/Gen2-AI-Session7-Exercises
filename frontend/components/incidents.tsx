"use client";

// Bài 04 - Tác động sự cố: chat bên trái; bên phải là danh sách dịch vụ người dùng thấy có thể bị ảnh hưởng
// kèm đường đi ngắn nhất, các lớp BFS, từng bước duyệt, cảnh báo dữ liệu thiếu, và dữ liệu trong hệ thống
// (có nút công bố sơ đồ mới và đổi trạng thái sự cố để thử ca dữ liệu đổi sau khi AI đọc).
import { Fragment, useCallback, useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, GitBranch, Layers, Loader2, Network, RotateCcw, SearchX, Upload } from "lucide-react";
import { ApiError, api } from "@/lib/api";
import { shortTime } from "@/lib/format";
import type { ImpactResult, IncidentData, IncidentStatus, RunDetail, SampleQuestion, ToolFailure } from "@/lib/types";
import { ChatPanel } from "./chat";
import { Empty, PanelHeader } from "./ui";

const STATUS: Record<IncidentStatus, [string, string]> = {
  investigating: ["Đang điều tra", "red"],
  monitoring: ["Đang theo dõi", "amber"],
  resolved: ["Đã xử lý xong", "green"],
};

const READ_TOOLS = ["get_incident", "get_service_graph", "get_customer_facing_services"];

export function IncidentsPage() {
  const [samples, setSamples] = useState<SampleQuestion[]>([]);
  const [data, setData] = useState<IncidentData | null>(null);
  const [latest, setLatest] = useState<RunDetail | null>(null);
  const [syncKey, setSyncKey] = useState(0);

  const loadData = useCallback(() => { api.incidentData().then(setData).catch(() => {}); }, []);

  useEffect(() => {
    api.incidentSamples().then(setSamples).catch(() => {});
    loadData();
  }, [loadData]);

  return (
    <div className="chat-layout">
      <ChatPanel
        module="incidents"
        title="Trợ lý trực vận hành"
        placeholder="Ví dụ: Sự cố INC-9 có thể ảnh hưởng những phần nào người dùng thấy?"
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

/** Kết quả công cụ trace_impact của câu hỏi gần nhất. */
function UsedDataPanel({ run }: { run: RunDetail | null }) {
  const calls = run?.tool_calls ?? [];
  const traceCall = [...calls].reverse().find((c) => c.name === "trace_impact");
  const calc = traceCall?.ok ? (traceCall.result as ImpactResult) : null;
  const failures = calls.filter((c) => !c.ok && c.error).map((c) => c.error as ToolFailure);
  const uniqueFailures = failures.filter((f, i) => failures.findIndex((x) => x.message === f.message) === i);
  const hasReads = calls.some((c) => READ_TOOLS.includes(c.name));
  const facingCall = calls.find((c) => c.name === "get_customer_facing_services" && c.ok);
  const facing = new Set(((facingCall?.result as { services?: { service_id: string }[] })?.services ?? []).map((s) => s.service_id));

  return (
    <section className="panel">
      <PanelHeader
        step={1}
        title="Dữ liệu AI đã dùng"
        subtitle={run ? `Lần xử lý #${run.id}: "${run.question}"` : "Kết quả công cụ của câu hỏi gần nhất."}
      />
      <div className="panel-body">
        {!run && <Empty icon={Network} text="Hỏi về một sự cố để xem các dịch vụ có thể bị ảnh hưởng và đường đi ở đây." />}
        {run && !hasReads && <Empty text="Câu hỏi này chưa gọi công cụ nào (AI đang hỏi lại thông tin còn thiếu)." />}
        {uniqueFailures.map((f) => (
          <div className="result-card warn" key={f.code + f.message}>
            <AlertTriangle size={17} />
            <div><strong>Công cụ báo lỗi: {f.code}</strong><span>{f.message}</span></div>
          </div>
        ))}
        {calc && <ImpactView calc={calc} facing={facing} />}
      </div>
    </section>
  );
}

function ImpactView({ calc, facing }: { calc: ImpactResult; facing: Set<string> }) {
  const [label, tone] = STATUS[calc.incident_status];
  const loops = calc.bfs_steps.flatMap((s) => s.already_seen.map((to) => `${s.service} → ${to}`));
  const hasDuplicate = (from: string, to: string) => calc.duplicate_edges.some((e) => e.from === from && e.to === to);

  return (
    <>
      <div className="invoice-line">
        <span><b>{calc.incident_id}</b> · hệ thống {calc.system_id} · <span className={`pill ${tone}`}>{label}</span></span>
        <strong>{calc.impacted.length} dịch vụ người dùng thấy</strong>
      </div>

      <div className="policy-chips">
        <span className="failed-chip"><AlertTriangle size={12} /> Lỗi tại {calc.failed_service}</span>
        <span><GitBranch size={12} /> Sơ đồ v{calc.graph_version} · chụp {shortTime(calc.graph_captured_at)}</span>
        <span>{calc.counts.services} dịch vụ · {calc.counts.unique_edges} cạnh{calc.counts.edges !== calc.counts.unique_edges ? ` (+${calc.counts.edges - calc.counts.unique_edges} trùng)` : ""}</span>
      </div>

      <ResultCard calc={calc} />

      {calc.graph_changed && (
        <div className="result-card warn">
          <AlertTriangle size={17} />
          <div>
            <strong>Sơ đồ đã đổi từ v{calc.graph_changed.before} sang v{calc.graph_changed.now} sau khi AI đọc</strong>
            <span>Kết quả tính theo v{calc.graph_changed.now}, phiên bản mới nhất.</span>
          </div>
        </div>
      )}

      {calc.impacted.length > 0 && (
        <div>
          <h4 className="mini-heading"><ArrowRight size={13} /> Có thể bị ảnh hưởng · đường đi ít cạnh nhất</h4>
          <ul className="impact-list">
            {calc.impacted.map((r) => (
              <li key={r.service_id}>
                <div className="impact-head">
                  <b>{r.service_id}</b><small>{r.name}</small>
                  <span className="pill blue">{r.distance} cạnh</span>
                </div>
                <div className="path-chain">
                  {r.path.map((node, i) => (
                    <Fragment key={node}>
                      {i > 0 && <ArrowRight size={12} className="path-arrow" />}
                      <span className={`node-chip ${i === 0 ? "failed" : i === r.path.length - 1 ? "facing" : ""}`}>{node}</span>
                    </Fragment>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {calc.layers.length > 0 && (
        <div>
          <h4 className="mini-heading"><Layers size={13} /> Các lớp BFS (số cạnh từ {calc.failed_service})</h4>
          <div className="layer-grid">
            {calc.layers.map((layer, d) => (
              <div className="layer" key={d}>
                <span className="layer-title">{d === 0 ? "Điểm lỗi" : `${d} cạnh`}</span>
                {layer.map((node) => (
                  <span key={node} className={`node-chip ${d === 0 ? "failed" : facing.has(node) ? "facing" : ""}`}>{node}</span>
                ))}
              </div>
            ))}
          </div>
          <p className="hint"><span className="legend failed" /> dịch vụ lỗi · <span className="legend facing" /> người dùng thấy · còn lại là dịch vụ nội bộ trên đường đi.</p>
        </div>
      )}

      {(calc.not_reached.length > 0 || calc.duplicate_edges.length > 0 || loops.length > 0) && (
        <div>
          <h4 className="mini-heading">Không đưa vào danh sách / bỏ qua khi duyệt</h4>
          <ul className="excluded-list">
            {calc.not_reached.map((r) => <li key={r.service_id}><b>{r.service_id}</b><em>{r.reason}</em></li>)}
            {calc.duplicate_edges.map((e) => (
              <li key={`d${e.from}${e.to}`}><b>{e.from} → {e.to}</b><em className="muted-em">Cạnh trùng, chỉ tính một lần</em></li>
            ))}
            {loops.map((l) => <li key={`l${l}`}><b>{l}</b><em className="muted-em">Dẫn về dịch vụ đã duyệt, không đi lại (tránh lặp vô hạn)</em></li>)}
          </ul>
        </div>
      )}

      {calc.bfs_steps.length > 0 && (
        <div>
          <h4 className="mini-heading"><Network size={13} /> Từng bước BFS (lấy ra khỏi hàng đợi theo thứ tự)</h4>
          <div className="table-wrap">
            <table className="data-table compact">
              <thead><tr><th>#</th><th>Đang xét</th><th>Phát hiện mới</th><th>Đã thăm, bỏ qua</th></tr></thead>
              <tbody>
                {calc.bfs_steps.map((s, i) => (
                  <tr key={s.service}>
                    <td className="muted">{i + 1}</td>
                    <td><b>{s.service}</b><small>{s.distance} cạnh</small></td>
                    <td>{s.discovered.length ? s.discovered.join(", ") : <span className="muted">-</span>}</td>
                    <td className={s.already_seen.length ? "text-amber" : "muted"}>
                      {s.already_seen.length ? s.already_seen.join(", ") : "-"}
                      {s.already_seen.some((x) => hasDuplicate(s.service, x)) && " (trùng)"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="hint">Điểm kề được xét theo thứ tự chữ cái nên đường đi ra giống nhau mỗi lần chạy.</p>
        </div>
      )}

      {calc.impacted.length > 0 && <p className="hint possible-note">{calc.note}</p>}
      <p className="hint rule">Quy tắc: {calc.rule}</p>
    </>
  );
}

function ResultCard({ calc }: { calc: ImpactResult }) {
  const blocking = calc.warnings.filter((w) => w.code !== "graph_version_changed");
  if (calc.status === "incomplete_data") {
    return (
      <div className="result-card warn">
        <AlertTriangle size={17} />
        <div>
          <strong>incomplete_data: danh sách CHƯA chắc đầy đủ</strong>
          {blocking.map((w) => <span key={w.code}>• {w.message}</span>)}
          <span>Cần cập nhật sơ đồ rồi kiểm tra lại.</span>
        </div>
      </div>
    );
  }
  if (calc.impacted.length === 0) {
    return (
      <div className="result-card warn">
        <SearchX size={17} />
        <div>
          <strong>Không có dịch vụ người dùng thấy nào nối tới {calc.failed_service}</strong>
          <span>Theo sơ đồ v{calc.graph_version}, lỗi chỉ lan trong các dịch vụ nội bộ.</span>
        </div>
      </div>
    );
  }
  return (
    <div className="result-card ok">
      <CheckCircle2 size={17} />
      <div>
        <strong>{calc.impacted.map((r) => r.service_id).join(", ")} có thể bị ảnh hưởng</strong>
        <span>
          Duyệt tới {calc.all_reached.length} dịch vụ phía sau {calc.failed_service}. Đây là phân tích theo sơ đồ, chưa xác nhận đã hỏng;
          không dịch vụ nào bị khởi động lại hay thay đổi.
        </span>
      </div>
    </div>
  );
}

/** Hệ thống, sơ đồ, dịch vụ, sự cố đang có trong database. */
function SystemDataPanel({ data, run, onChanged, onReset }: {
  data: IncidentData | null; run: RunDetail | null; onChanged: () => void; onReset: () => void;
}) {
  const [system, setSystem] = useState("SHOP");
  const [tab, setTab] = useState<"incidents" | "graph" | "services" | "notes">("incidents");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  // Theo hệ thống của câu hỏi gần nhất; thông báo chỉ còn tới câu hỏi kế tiếp
  const runSystem = (run?.tool_calls.find((c) => c.name === "get_incident" && c.ok)?.result as { system_id?: string })?.system_id;
  useEffect(() => {
    setMessage("");
    if (runSystem) setSystem(runSystem);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id]);

  const info = data?.systems.find((s) => s.system_id === system);
  const graph = data?.graphs.find((g) => g.system_id === system && g.version === info?.current_version);
  const services = data?.services.filter((s) => s.system_id === system) ?? [];
  const incidents = data?.incidents.filter((i) => i.system_id === system) ?? [];
  const incidentIds = new Set(incidents.map((i) => i.incident_id));
  const notes = data?.notes.filter((n) => incidentIds.has(n.incident_id)) ?? [];
  const inGraph = new Set(graph?.edges.flatMap((e) => [e.from, e.to]) ?? []);
  const catalog = new Set(services.map((s) => s.service_id));
  const unknown = [...inGraph].filter((id) => !catalog.has(id)).sort();
  const edgeKeys = graph?.edges.map((e) => `${e.from}>${e.to}`) ?? [];

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

  const publish = () => act("publish", async () => {
    const result = await api.publishGraph(system);
    return `${system}: đã công bố sơ đồ v${result.current_version} (trước là v${result.before}). `
      + "Đề xuất ghi chú tạo theo sơ đồ cũ sẽ bị chặn khi duyệt; hỏi lại để AI duyệt theo sơ đồ mới.";
  });

  const changeStatus = (id: string, status: IncidentStatus) => act(id, async () => {
    await api.changeIncident(id, status);
    return status === "resolved"
      ? `${id}: ${STATUS[status][0]}. Đề xuất ghi chú đang chờ của sự cố này sẽ không duyệt được.`
      : `${id}: ${STATUS[status][0]}.`;
  });

  const reset = () => act("reset", async () => {
    const result = await api.resetIncidents();
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
        subtitle="Dữ liệu giả. Công cụ chỉ đọc từ đây; nút công bố sơ đồ và đổi trạng thái sự cố là thao tác của người dùng, AI không gọi được."
        action={(
          <button className="secondary-button" onClick={reset} disabled={busy !== null}>
            {busy === "reset" ? <Loader2 size={14} className="spin" /> : <RotateCcw size={14} />} Khôi phục dữ liệu mẫu
          </button>
        )}
      />
      {message && <p className="panel-note">{message}</p>}

      <div className="line-picker">
        {data?.systems.map((s) => (
          <button key={s.system_id} className={system === s.system_id ? "active" : ""} onClick={() => setSystem(s.system_id)} title={s.name}>
            {s.system_id}
          </button>
        ))}
      </div>
      {info && (
        <div className="shift-list">
          <span><b>{info.name}</b></span>
          <span>Sơ đồ đang dùng v{info.current_version}{graph && ` · chụp ${shortTime(graph.captured_at)}`}</span>
          {graph?.note && <span>{graph.note}</span>}
          {info.next_version !== null && (
            <button className="secondary-button small" onClick={publish} disabled={busy !== null}>
              {busy === "publish" ? <Loader2 size={12} className="spin" /> : <Upload size={12} />} Công bố v{info.next_version}
            </button>
          )}
        </div>
      )}

      <div className="tabs">
        <button className={tab === "incidents" ? "active" : ""} onClick={() => setTab("incidents")}>Sự cố ({incidents.length})</button>
        <button className={tab === "graph" ? "active" : ""} onClick={() => setTab("graph")}>Sơ đồ ({graph?.edges.length ?? 0} cạnh)</button>
        <button className={tab === "services" ? "active" : ""} onClick={() => setTab("services")}>Dịch vụ ({services.length})</button>
        <button className={tab === "notes" ? "active" : ""} onClick={() => setTab("notes")}>Ghi chú ({notes.length})</button>
      </div>

      {!data ? <Empty text="Đang tải dữ liệu…" /> : tab === "incidents" ? (
        <div className="table-wrap">
          <table className="data-table compact">
            <thead><tr><th>Sự cố</th><th>Dịch vụ lỗi</th><th>Bắt đầu</th><th>Trạng thái</th></tr></thead>
            <tbody>
              {incidents.map((i) => (
                <tr key={i.incident_id}>
                  <td><b>{i.incident_id}</b><small>{i.title}</small></td>
                  <td>{i.service_id}{!inGraph.has(i.service_id) && <small className="text-red">không có trong sơ đồ</small>}</td>
                  <td className="muted">{shortTime(i.started_at)}</td>
                  <td>
                    <select
                      className={`status-select ${STATUS[i.status][1]}`} value={i.status} disabled={busy !== null}
                      aria-label={`Trạng thái sự cố ${i.incident_id}`}
                      onChange={(e) => changeStatus(i.incident_id, e.target.value as IncidentStatus)}
                    >
                      {Object.entries(STATUS).map(([value, [text]]) => <option key={value} value={value}>{text}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : tab === "graph" ? (
        <div className="table-wrap">
          <table className="data-table compact">
            <thead><tr><th>Từ</th><th></th><th>Tới (phụ thuộc vào "Từ")</th></tr></thead>
            <tbody>
              {graph?.edges.map((e, idx) => {
                const duplicate = edgeKeys.indexOf(`${e.from}>${e.to}`) !== idx;
                return (
                  <tr key={idx} className={duplicate ? "skipped" : ""}>
                    <td><b>{e.from}</b></td>
                    <td className="muted">→</td>
                    <td>
                      {e.to}
                      {duplicate && <small className="text-amber">cạnh trùng</small>}
                      {!catalog.has(e.to) && <small className="text-red">không có trong danh mục</small>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {unknown.length > 0 && <p className="hint table-hint">Dịch vụ lạ trong sơ đồ: {unknown.join(", ")}.</p>}
        </div>
      ) : tab === "services" ? (
        <div className="table-wrap">
          <table className="data-table compact">
            <thead><tr><th>Dịch vụ</th><th>Người dùng thấy</th><th>Trong sơ đồ v{info?.current_version}</th></tr></thead>
            <tbody>
              {services.map((s) => (
                <tr key={s.service_id}>
                  <td><b>{s.service_id}</b><small>{s.name}</small></td>
                  <td>{s.customer_facing ? <span className="pill blue">Có</span> : <span className="muted">Nội bộ</span>}</td>
                  <td>{inGraph.has(s.service_id) ? <span className="muted">Có</span> : <span className="pill red">Thiếu</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : notes.length === 0 ? (
        <Empty text="Chưa có ghi chú nào. Ghi chú chỉ được ghi khi người trực duyệt đề xuất của AI." />
      ) : (
        <ul className="excluded-list note-list">
          {notes.map((n) => (
            <li key={n.note_id}>
              <b>{n.incident_id}</b>
              <span className="muted">sơ đồ v{n.graph_version} · {shortTime(n.created_at)}</span>
              {n.status === "incomplete_data" && <span className="pill amber">chưa đầy đủ</span>}
              <span className="note-paths">{n.impacted.map((r) => r.path.join(" → ")).join(" · ") || "Không có dịch vụ người dùng thấy"}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
