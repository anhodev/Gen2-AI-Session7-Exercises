"use client";

// Bài 01 - Đối soát hóa đơn: chat bên trái; bên phải là dữ liệu AI đã dùng và dữ liệu đang có trong hệ thống.
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Hash, Loader2, ReceiptText, RotateCcw, SearchX } from "lucide-react";
import { ApiError, api } from "@/lib/api";
import { clock, formatMoney, gmtLabel, shortTime } from "@/lib/format";
import type { InvoiceData, InvoiceRow, MatchResult, RunDetail, SampleQuestion, ToolFailure } from "@/lib/types";
import { ChatPanel } from "./chat";
import { Empty, PanelHeader } from "./ui";

const INVOICE_STATUS: Record<string, [string, string]> = {
  open: ["Còn mở", "blue"],
  paid: ["Đã thanh toán", "green"],
  cancelled: ["Đã hủy", "gray"],
};

export function InvoicesPage() {
  const [samples, setSamples] = useState<SampleQuestion[]>([]);
  const [data, setData] = useState<InvoiceData | null>(null);
  const [latest, setLatest] = useState<RunDetail | null>(null);
  const [syncKey, setSyncKey] = useState(0);

  const loadData = useCallback(() => { api.invoiceData().then(setData).catch(() => {}); }, []);

  useEffect(() => {
    api.invoiceSamples().then(setSamples).catch(() => {});
    loadData();
  }, [loadData]);

  return (
    <div className="chat-layout">
      <ChatPanel
        module="invoices"
        title="Trợ lý đối soát"
        placeholder="Ví dụ: Kiểm tra hóa đơn I-77 và ghi nhận luôn"
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
          onReset={() => { loadData(); setSyncKey((k) => k + 1); }}
        />
      </div>
    </div>
  );
}

/** Dữ liệu lần hỏi gần nhất đã dùng: hóa đơn, thứ tự quét, cặp chọn, giao dịch bị loại. */
function UsedDataPanel({ run }: { run: RunDetail | null }) {
  const invoiceCall = run?.tool_calls.find((c) => c.name === "get_open_invoice");
  const matchCall = [...(run?.tool_calls ?? [])].reverse().find((c) => c.name === "find_two_transfer_match");
  const match = matchCall?.ok ? (matchCall.result as MatchResult) : null;
  const failure: ToolFailure | null = (!invoiceCall?.ok && invoiceCall?.error) || (!matchCall?.ok && matchCall?.error) || null;

  return (
    <section className="panel">
      <PanelHeader
        step={1}
        title="Dữ liệu AI đã dùng"
        subtitle={run ? `Lần xử lý #${run.id}: "${run.question}"` : "Kết quả công cụ của câu hỏi gần nhất."}
      />
      <div className="panel-body">
        {!run && <Empty icon={ReceiptText} text="Hỏi về một hóa đơn để xem dữ liệu và kết quả thuật toán ở đây." />}
        {run && !invoiceCall && <Empty text="Câu hỏi này chưa gọi công cụ nào (AI đang hỏi lại thông tin còn thiếu)." />}
        {failure && (
          <div className="result-card warn">
            <AlertTriangle size={17} />
            <div><strong>Công cụ báo lỗi: {failure.code}</strong><span>{failure.message}</span></div>
          </div>
        )}
        {match && <MatchView match={match} />}
      </div>
    </section>
  );
}

function MatchView({ match }: { match: MatchResult }) {
  const pairIds = new Set(match.pair?.map((p) => p.transfer_id));
  const otherIds = new Set(match.other_pairs.flatMap((p) => p.transfer_ids));
  const tz = match.scan_order[0] ? gmtLabel(match.scan_order[0].received_at) : "";

  return (
    <>
      <div className="invoice-line">
        <span><b>{match.invoice_id}</b> · khách {match.customer_id} · {match.currency}</span>
        <strong>Còn thiếu {match.amount_due}</strong>
      </div>

      {match.status === "matched" && match.pair ? (
        <div className="result-card ok">
          <CheckCircle2 size={17} />
          <div>
            <strong>{match.pair.map((p) => p.transfer_id).join(" + ")} = {match.total}</strong>
            <span>{match.reason}</span>
          </div>
        </div>
      ) : (
        <div className="result-card warn">
          <SearchX size={17} />
          <div><strong>Không có hai giao dịch nào cộng lại đúng {match.amount_due}</strong><span>{match.reason}</span></div>
        </div>
      )}

      <div>
        <h4 className="mini-heading"><Hash size={13} /> Thứ tự quét của hash map ({tz})</h4>
        {match.scan_order.length === 0 ? <p className="hint">Không có giao dịch hợp lệ để quét.</p> : (
          <div className="table-wrap">
            <table className="data-table compact">
              <thead><tr><th>#</th><th>Giao dịch</th><th>Số tiền</th><th>Giờ nhận</th><th>Cần thêm</th></tr></thead>
              <tbody>
                {match.scan_order.map((t, i) => (
                  <tr key={t.transfer_id} className={pairIds.has(t.transfer_id) ? "picked" : ""}>
                    <td>{i + 1}</td>
                    <td>
                      <b>{t.transfer_id}</b>
                      {pairIds.has(t.transfer_id) && <small className="tag-picked">Cặp chọn</small>}
                      {!pairIds.has(t.transfer_id) && otherIds.has(t.transfer_id) && <small>Cặp khác</small>}
                    </td>
                    <td className="amount">{t.amount}</td>
                    <td>{clock(t.received_at)}</td>
                    <td className="amount muted">{formatMoney(match.amount_due_minor - t.amount_minor, match.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {match.excluded.length > 0 && (
        <div>
          <h4 className="mini-heading">Không xét</h4>
          <ul className="excluded-list">
            {match.excluded.map((t) => (
              <li key={t.transfer_id}><b>{t.transfer_id}</b> {t.amount} · khách {t.customer_id}<em>{t.reason}</em></li>
            ))}
          </ul>
        </div>
      )}

      {match.other_pairs.length > 0 && (
        <p className="hint">Cặp khác cũng đủ tiền: {match.other_pairs.map((p) => p.transfer_ids.join(" + ")).join("; ")}. Không chọn vì hoàn tất muộn hơn khi quét theo giờ nhận.</p>
      )}
      <p className="hint rule">Quy tắc: {match.rule}</p>
    </>
  );
}

/** Hóa đơn và giao dịch đang có trong database. Dòng AI vừa dùng được tô đậm. */
function SystemDataPanel({ data, run, onReset }: { data: InvoiceData | null; run: RunDetail | null; onReset: () => void }) {
  const [tab, setTab] = useState<"invoices" | "transfers">("invoices");
  const [resetting, setResetting] = useState(false);
  const [message, setMessage] = useState("");

  // Thông báo khôi phục chỉ còn đúng tới câu hỏi kế tiếp
  useEffect(() => { setMessage(""); }, [run?.id]);

  const invoiceId = (run?.tool_calls.find((c) => c.name === "get_open_invoice")?.args as { invoice_id?: string })?.invoice_id;
  const usedTransfers = new Set(
    run?.tool_calls.flatMap((c) => (c.name === "list_unmatched_transfers" && c.ok
      ? (c.result as { transfers: { transfer_id: string }[] }).transfers.map((t) => t.transfer_id)
      : [])) ?? [],
  );

  const reset = async () => {
    setResetting(true);
    setMessage("");
    try {
      const result = await api.resetInvoices();
      setMessage(result.closed_proposals
        ? `Đã khôi phục dữ liệu mẫu và đóng ${result.closed_proposals} đề xuất đang chờ.`
        : "Đã khôi phục dữ liệu mẫu.");
      onReset();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Không khôi phục được dữ liệu.");
    } finally {
      setResetting(false);
    }
  };

  return (
    <section className="panel">
      <PanelHeader
        step={2}
        title="Dữ liệu trong hệ thống"
        subtitle="Dữ liệu giả để đối chiếu. Công cụ chỉ đọc từ đây."
        action={(
          <button className="secondary-button" onClick={reset} disabled={resetting}>
            {resetting ? <Loader2 size={14} className="spin" /> : <RotateCcw size={14} />} Khôi phục dữ liệu mẫu
          </button>
        )}
      />
      {message && <p className="panel-note">{message}</p>}
      <div className="tabs">
        <button className={tab === "invoices" ? "active" : ""} onClick={() => setTab("invoices")}>Hóa đơn ({data?.invoices.length ?? 0})</button>
        <button className={tab === "transfers" ? "active" : ""} onClick={() => setTab("transfers")}>Giao dịch ({data?.transfers.length ?? 0})</button>
      </div>
      {!data ? <Empty text="Đang tải dữ liệu…" /> : tab === "invoices" ? (
        <InvoiceTable invoices={data.invoices} highlight={invoiceId} />
      ) : (
        <div className="table-wrap">
          <table className="data-table compact">
            <thead><tr><th>Mã</th><th>Khách</th><th>Số tiền</th><th>Nhận lúc</th><th>Trạng thái</th></tr></thead>
            <tbody>
              {data.transfers.map((t) => (
                <tr key={t.transfer_id} className={usedTransfers.has(t.transfer_id) ? "picked" : ""}>
                  <td><b>{t.transfer_id}</b>{t.memo && <small>{t.memo}</small>}</td>
                  <td>{t.customer_id}</td>
                  <td className="amount">{t.amount}</td>
                  <td>{shortTime(t.received_at)}</td>
                  <td>
                    {t.status === "matched"
                      ? <span className="pill green">Đã ghép {t.matched_invoice_id}</span>
                      : <span className="pill gray">Chưa ghép</span>}
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

function InvoiceTable({ invoices, highlight }: { invoices: InvoiceRow[]; highlight?: string }) {
  return (
    <div className="table-wrap">
      <table className="data-table compact">
        <thead><tr><th>Mã</th><th>Khách</th><th>Tổng tiền</th><th>Còn thiếu</th><th>Trạng thái</th></tr></thead>
        <tbody>
          {invoices.map((i) => {
            const [label, tone] = INVOICE_STATUS[i.status] ?? [i.status, "gray"];
            return (
              <tr key={i.invoice_id} className={i.invoice_id === highlight ? "picked" : ""}>
                <td><b>{i.invoice_id}</b><small>{shortTime(i.issued_at)}</small></td>
                <td>{i.customer_id}</td>
                <td className="amount">{formatMoney(i.amount_total_minor, i.currency)}</td>
                <td className="amount">{i.amount_due}</td>
                <td><span className={`pill ${tone}`}>{label}</span></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
