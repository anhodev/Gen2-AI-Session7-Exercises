"use client";

// Lịch sử xử lý: mỗi câu hỏi đã hỏi ở 4 bài, kèm các lần gọi công cụ (tên, tham số, kết quả hoặc lỗi),
// kết quả thuật toán, câu trả lời và đề xuất. Dữ liệu đọc từ GET /runs và GET /runs/{id}.
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Calculator, Clock, History, Loader2, RefreshCw, Wrench } from "lucide-react";
import { ApiError, api } from "@/lib/api";
import { duration, localTime } from "@/lib/format";
import type { Module, Run, RunDetail } from "@/lib/types";
import { ProposalCard, ToolTimeline } from "./chat";
import { Empty, PanelHeader } from "./ui";

const MODULES: { id: Module | "all"; label: string }[] = [
  { id: "all", label: "Tất cả" },
  { id: "invoices", label: "01 · Hóa đơn" },
  { id: "capacity", label: "02 · Công suất" },
  { id: "notifications", label: "03 · Thông báo" },
  { id: "incidents", label: "04 · Sự cố" },
];

const MODULE_LABEL: Record<string, string> = Object.fromEntries(MODULES.map((m) => [m.id, m.label]));

const RUN_STATUS: Record<string, [string, string]> = {
  answered: ["Đã trả lời", "green"],
  running: ["Đang chạy", "blue"],
  max_steps: ["Quá số vòng", "amber"],
  error: ["Lỗi model", "red"],
};

export function HistoryPage() {
  const [module, setModule] = useState<Module | "all">("all");
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const detailRef = useRef<HTMLDivElement>(null);

  const pick = (id: number) => {
    setSelected(id);
    // Màn hẹp: chi tiết nằm dưới danh sách nên cuộn tới cho người dùng thấy
    if (window.matchMedia("(max-width:1100px)").matches) {
      setTimeout(() => detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const list = await api.runs(module === "all" ? undefined : module);
      setRuns(list);
      setSelected((id) => (id !== null && list.some((r) => r.id === id) ? id : list[0]?.id ?? null));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Không đọc được lịch sử.");
    } finally {
      setLoading(false);
    }
  }, [module]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="history-layout">
      <section className="panel">
        <PanelHeader
          title="Các câu hỏi gần đây"
          subtitle="50 lần xử lý mới nhất. Bấm một dòng để xem chi tiết."
          action={(
            <button className="secondary-button" onClick={load} disabled={loading}>
              {loading ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />} Tải lại
            </button>
          )}
        />
        <div className="line-picker">
          {MODULES.map((m) => (
            <button key={m.id} className={module === m.id ? "active" : ""} onClick={() => setModule(m.id)}>{m.label}</button>
          ))}
        </div>
        {error && <p className="form-error history-error">{error}</p>}
        {runs === null ? <Empty text="Đang tải…" /> : runs.length === 0 ? (
          <Empty icon={History} text="Chưa có câu hỏi nào. Hỏi ở một bài rồi quay lại đây." />
        ) : (
          <ul className="run-list">
            {runs.map((r) => {
              const [label, tone] = RUN_STATUS[r.status] ?? [r.status, "gray"];
              return (
                <li key={r.id}>
                  <button className={selected === r.id ? "active" : ""} onClick={() => pick(r.id)}>
                    <div className="run-row-head">
                      <b>#{r.id}</b>
                      <span className="run-module">{MODULE_LABEL[r.module] ?? r.module}</span>
                      <span className={`pill ${tone}`}>{label}</span>
                    </div>
                    <p>{r.question}</p>
                    <div className="run-row-meta">
                      <span><Wrench size={11} /> {r.tool_count} công cụ · {r.rounds} vòng</span>
                      <span><Clock size={11} /> {duration(r.latency_ms)}</span>
                      <span>{localTime(r.created_at)}</span>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <div ref={detailRef} className="history-detail">
        {selected !== null ? <RunView id={selected} onDecided={load} /> : (
          <section className="panel"><Empty icon={History} text="Chọn một câu hỏi để xem chi tiết." /></section>
        )}
      </div>
    </div>
  );
}

function RunView({ id, onDecided }: { id: number; onDecided: () => void }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    api.run(id).then(setRun).catch((e) => setError(e instanceof ApiError ? e.message : "Không đọc được lần xử lý."));
  }, [id]);

  useEffect(() => { setRun(null); load(); }, [load]);

  if (error) return <section className="panel"><div className="panel-body"><p className="form-error">{error}</p></div></section>;
  if (!run || run.id !== id) return <section className="panel"><Empty text="Đang tải…" /></section>;

  const algorithms = run.tool_calls.filter((c) => c.kind === "algorithm");
  const failed = run.tool_calls.filter((c) => !c.ok);
  const [label, tone] = RUN_STATUS[run.status] ?? [run.status, "gray"];

  return (
    <section className="panel">
      <PanelHeader
        title={`Lần xử lý #${run.id}`}
        subtitle={`${MODULE_LABEL[run.module] ?? run.module} · hội thoại ${run.conversation_id} · ${localTime(run.created_at)}`}
        action={<span className={`pill ${tone}`}>{label}</span>}
      />
      <div className="panel-body">
        <div className="policy-chips">
          <span>{run.model}</span>
          <span>{run.rounds} vòng gọi model</span>
          <span>{run.tool_calls.length} lần gọi công cụ{failed.length ? ` · ${failed.length} lỗi` : ""}</span>
          <span><Clock size={12} /> {duration(run.latency_ms)}</span>
        </div>

        <div>
          <h4 className="mini-heading">Câu hỏi</h4>
          <p className="history-question">{run.question}</p>
        </div>

        <div>
          <h4 className="mini-heading">Câu trả lời</h4>
          {run.error && <p className="form-error"><AlertTriangle size={12} /> {run.error}</p>}
          <p className="history-answer">{run.answer ?? "(không có)"}</p>
        </div>

        {run.tool_calls.length > 0 ? (
          <div className="history-tools"><ToolTimeline calls={run.tool_calls} /></div>
        ) : (
          <p className="hint">Không gọi công cụ nào (AI hỏi lại thông tin còn thiếu hoặc trả lời ngay).</p>
        )}

        {algorithms.map((c) => (
          <details className="raw-json" key={c.tool_call_id}>
            <summary><Calculator size={12} /> Kết quả thuật toán: {c.name} {c.ok ? "" : `(lỗi ${c.error?.code})`}</summary>
            <pre className="history-json">{JSON.stringify(c.ok ? c.result : c.error, null, 2)}</pre>
          </details>
        ))}

        {run.proposals.length > 0 && (
          <div className="history-proposals">
            <h4 className="mini-heading">Đề xuất tạo trong lần này</h4>
            {run.proposals.map((p) => (
              <ProposalCard key={p.id} proposal={p} onDecided={() => { load(); onDecided(); }} onConflict={load} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
