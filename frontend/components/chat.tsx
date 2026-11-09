"use client";

// Khung chat dùng chung cho 4 bài. Ý tưởng lấy từ Copilot buổi 4 (bong bóng chat, danh sách công cụ, thẻ duyệt),
// khác ở chỗ mỗi câu trả lời hiện đủ các lần gọi công cụ: tên, tham số, kết quả hoặc lỗi.
import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle, Bot, Calculator, Check, ChevronRight, CircleAlert, Clock, Database, Loader2, MessageSquarePlus,
  Send, ShieldCheck, UserRound, X, Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { ApiError, api } from "@/lib/api";
import { duration, localTime } from "@/lib/format";
import type { Module, Proposal, RunDetail, SampleQuestion, ToolCall } from "@/lib/types";

export interface ChatMessage {
  key: string;
  role: "user" | "assistant";
  text: string;
  run?: RunDetail;
  failed?: boolean; // gọi API lỗi (mất kết nối, 404...), không có run
}

const KINDS: Record<string, { label: string; icon: LucideIcon; tone: string }> = {
  read: { label: "Đọc dữ liệu", icon: Database, tone: "blue" },
  algorithm: { label: "Thuật toán", icon: Calculator, tone: "violet" },
  action: { label: "Tạo đề xuất", icon: Zap, tone: "amber" },
};

const RUN_STATUS: Record<string, { label: string; tone: string } | undefined> = {
  max_steps: { label: "Dừng vì quá số vòng gọi công cụ", tone: "amber" },
  error: { label: "Lỗi khi gọi model", tone: "red" },
};

const REVIEWER_KEY = "reviewer-name";

export function ChatPanel({
  module, title, placeholder, samples, onRun, onDecided, syncKey = 0,
}: {
  module: Module;
  title: string;
  placeholder: string;
  samples: SampleQuestion[];
  onRun?: (run: RunDetail) => void;
  onDecided?: (proposal: Proposal) => void;
  /** Đổi giá trị này để đọc lại trạng thái đề xuất (vd sau khi khôi phục dữ liệu mẫu). */
  syncKey?: number;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const replaceProposal = (updated: Proposal) => setMessages((list) => list.map((m) => (
    m.run && m.run.proposals.some((p) => p.id === updated.id)
      ? { ...m, run: { ...m.run, proposals: m.run.proposals.map((p) => (p.id === updated.id ? updated : p)) } }
      : m
  )));

  // Đọc lại trạng thái các đề xuất đang hiện (có thể đã được duyệt/đóng ở chỗ khác)
  const syncProposals = async () => {
    try {
      const latest = await api.proposals(module);
      latest.forEach(replaceProposal);
    } catch {}
  };

  useEffect(() => {
    if (syncKey > 0) syncProposals();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [syncKey]);

  const send = async (text = input) => {
    const question = text.trim();
    if (!question || loading) return;
    setInput("");
    setMessages((list) => [...list, { key: `u${Date.now()}`, role: "user", text: question }]);
    setLoading(true);
    try {
      const run = await api.chat(module, question, conversationId);
      setConversationId(run.conversation_id);
      setMessages((list) => [...list, { key: `r${run.id}`, role: "assistant", text: run.answer ?? run.error ?? "", run }]);
      onRun?.(run);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Lỗi không xác định";
      setMessages((list) => [...list, { key: `e${Date.now()}`, role: "assistant", text: `Không gửi được câu hỏi: ${message}`, failed: true }]);
    } finally {
      setLoading(false);
    }
  };

  const restart = () => { setMessages([]); setConversationId(null); setInput(""); };

  const decided = (proposal: Proposal) => { replaceProposal(proposal); onDecided?.(proposal); };

  return (
    <section className="chat-panel">
      <div className="chat-heading">
        <div className="bot-avatar"><Bot size={18} /></div>
        <div>
          <strong>{title}</strong>
          <span>{conversationId ? `Hội thoại ${conversationId} · AI nhớ câu hỏi trước` : "Hội thoại mới"}</span>
        </div>
        <button className="secondary-button" onClick={restart} disabled={loading || messages.length === 0}>
          <MessageSquarePlus size={15} /> Hội thoại mới
        </button>
      </div>

      <div className="messages" ref={listRef}>
        {messages.length === 0 && (
          <div className="chat-intro">
            <Bot size={26} />
            <p>Hỏi bằng lời thường. AI chọn công cụ để đọc dữ liệu và chạy thuật toán, backend kiểm tra từng lần gọi.</p>
            <p>Mọi thay đổi dữ liệu chỉ là đề xuất, cần người duyệt.</p>
          </div>
        )}
        {messages.map((m) => (m.role === "user"
          ? <div className="message user" key={m.key}><div className="bubble"><p>{m.text}</p></div></div>
          : <AssistantMessage key={m.key} message={m} onDecided={decided} onConflict={syncProposals} />
        ))}
        {loading && (
          <div className="message assistant">
            <div className="bot-avatar"><Bot size={16} /></div>
            <div className="bubble typing"><i /><i /><i /></div>
          </div>
        )}
      </div>

      {samples.length > 0 && (
        <div className="suggestions chat-samples">
          {samples.map((s) => (
            <button key={s.label} onClick={() => send(s.question)} disabled={loading} title={s.question}>{s.label}</button>
          ))}
        </div>
      )}
      <div className="composer">
        <textarea
          value={input}
          maxLength={2000}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder={placeholder}
        />
        <button onClick={() => send()} disabled={loading || !input.trim()} aria-label="Gửi">
          {loading ? <Loader2 size={18} className="spin" /> : <Send size={18} />}
        </button>
        <span>Enter để gửi · Shift + Enter xuống dòng</span>
      </div>
    </section>
  );
}

function AssistantMessage({ message, onDecided, onConflict }: {
  message: ChatMessage; onDecided: (p: Proposal) => void; onConflict: () => void;
}) {
  const run = message.run;
  const status = run ? RUN_STATUS[run.status] : undefined;
  // Đề xuất trùng với đề xuất đã có (tạo ở câu hỏi trước) thì không thuộc run này
  const reused = run?.tool_calls
    .filter((c) => c.kind === "action" && c.ok && (c.result as { created?: boolean })?.created === false)
    .map((c) => (c.result as { proposal_id: number }).proposal_id) ?? [];

  return (
    <div className="message assistant">
      <div className="bot-avatar"><Bot size={16} /></div>
      <div className={`bubble ${message.failed ? "failed" : ""}`}>
        {status && <span className={`pill ${status.tone}`}>{status.label}</span>}
        <p>{message.text}</p>
        {run && run.tool_calls.length > 0 && <ToolTimeline calls={run.tool_calls} />}
        {run?.proposals.map((p) => <ProposalCard key={p.id} proposal={p} onDecided={onDecided} onConflict={onConflict} />)}
        {reused.map((id) => (
          <p className="reused-note" key={id}><ShieldCheck size={13} /> Đề xuất #{id} đã có từ câu hỏi trước, không tạo thêm.</p>
        ))}
        {run && (
          <div className="run-meta">
            <span>Lần xử lý #{run.id}</span>
            <span>{run.model}</span>
            <span>{run.rounds} vòng</span>
            <span><Clock size={11} /> {duration(run.latency_ms)}</span>
          </div>
        )}
      </div>
    </div>
  );
}

/** Các lần gọi công cụ theo thứ tự: loại, tên, tham số, kết quả hoặc lỗi. Bấm để xem JSON đầy đủ. */
export function ToolTimeline({ calls }: { calls: ToolCall[] }) {
  return (
    <div className="tool-timeline">
      <p className="tool-timeline-title">Đã gọi {calls.length} công cụ</p>
      <ol>
        {calls.map((call, index) => {
          const kind = KINDS[call.kind] ?? { label: call.kind, icon: CircleAlert, tone: "gray" };
          const Icon = kind.icon;
          return (
            <li key={call.tool_call_id} className={call.ok ? "" : "failed"}>
              <details>
                <summary>
                  <ChevronRight size={13} className="chevron" />
                  <span className="tool-index">{index + 1}</span>
                  <span className={`kind ${kind.tone}`}><Icon size={11} /> {kind.label}</span>
                  <code className="tool-name">{call.name}</code>
                  <code className="tool-args">{compactArgs(call.args)}</code>
                  {call.ok
                    ? <span className="tool-ok"><Check size={12} /></span>
                    : <span className="tool-err"><X size={12} /> {call.error?.code}</span>}
                </summary>
                <div className="tool-detail">
                  {!call.ok && call.error && <p className="tool-error-message"><AlertTriangle size={13} /> {call.error.message}</p>}
                  <div className="tool-json">
                    <span>Tham số</span>
                    <pre>{JSON.stringify(call.args, null, 2)}</pre>
                  </div>
                  <div className="tool-json">
                    <span>{call.ok ? "Kết quả" : "Lỗi"}</span>
                    <pre>{JSON.stringify(call.ok ? call.result : call.error, null, 2)}</pre>
                  </div>
                  <small>Vòng {call.round} · {call.tool_call_id} · {duration(call.latency_ms)}</small>
                </div>
              </details>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function compactArgs(args: unknown): string {
  if (!args || typeof args !== "object" || Array.isArray(args)) return JSON.stringify(args);
  return Object.entries(args as Record<string, unknown>).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ");
}

function readReviewer(): string {
  try { return localStorage.getItem(REVIEWER_KEY) ?? ""; } catch { return ""; }
}

/** Đề xuất AI tạo. Chỉ người dùng bấm Duyệt/Từ chối ở đây mới đổi được dữ liệu. */
export function ProposalCard({ proposal, onDecided, onConflict }: {
  proposal: Proposal; onDecided: (p: Proposal) => void; onConflict?: () => void;
}) {
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState("");

  useEffect(() => { setReviewer(readReviewer()); }, []);

  const decide = async (action: "approve" | "reject") => {
    if (!reviewer.trim()) { setError("Ghi tên người duyệt trước."); return; }
    setBusy(action);
    setError("");
    try {
      try { localStorage.setItem(REVIEWER_KEY, reviewer.trim()); } catch {}
      onDecided(await api.decide(proposal.id, action, reviewer.trim(), note.trim()));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Không gửi được quyết định.");
      if (e instanceof ApiError && e.status === 409) onConflict?.();
    } finally {
      setBusy(null);
    }
  };

  if (proposal.status !== "pending_approval") {
    const approved = proposal.status === "approved";
    return (
      <div className={`proposal-card ${approved ? "approved" : "rejected"}`}>
        <div className="proposal-head">
          {approved ? <ShieldCheck size={16} /> : <X size={16} />}
          <div>
            <strong>Đề xuất #{proposal.id} · {approved ? "Đã duyệt" : "Đã từ chối"}</strong>
            <span>{proposal.summary}</span>
            <small>
              <UserRound size={11} /> {proposal.reviewer}
              {proposal.decided_at && ` · ${localTime(proposal.decided_at)}`}
              {proposal.note && ` · "${proposal.note}"`}
            </small>
          </div>
        </div>
        {approved && proposal.decision_result && (
          <details className="raw-json"><summary>Kết quả ghi nhận</summary><pre>{JSON.stringify(proposal.decision_result, null, 2)}</pre></details>
        )}
      </div>
    );
  }

  return (
    <div className="proposal-card pending">
      <div className="proposal-head">
        <AlertTriangle size={16} />
        <div>
          <strong>Đề xuất #{proposal.id} · Chờ duyệt</strong>
          <span>{proposal.summary}</span>
          <small>AI chỉ tạo đề xuất. Dữ liệu chưa thay đổi cho đến khi người có quyền bấm Duyệt.</small>
        </div>
      </div>
      <div className="proposal-form">
        <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Tên người duyệt" maxLength={50} />
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Ghi chú (không bắt buộc)" maxLength={500} />
        <div className="proposal-actions">
          <button className="primary-button" onClick={() => decide("approve")} disabled={busy !== null}>
            {busy === "approve" ? <Loader2 size={14} className="spin" /> : <Check size={14} />} Duyệt
          </button>
          <button className="secondary-button" onClick={() => decide("reject")} disabled={busy !== null}>
            {busy === "reject" ? <Loader2 size={14} className="spin" /> : <X size={14} />} Từ chối
          </button>
        </div>
        {error && <p className="form-error">{error}</p>}
      </div>
    </div>
  );
}
