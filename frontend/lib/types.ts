// Kiểu dữ liệu khớp với response của FastAPI.

export interface Health {
  status: string;
  llm: string; // "mock" hoặc tên model
  database: string; // "postgresql" hoặc "sqlite"
  timezone: string; // APP_TIMEZONE, vd "Asia/Ho_Chi_Minh"
}

export type Module = "invoices" | "capacity" | "notifications" | "incidents";

// --- Chat dùng chung ---------------------------------------------------------

export type ToolKind = "read" | "algorithm" | "action";

export interface ToolFailure {
  code: string; // tool_not_allowed, invalid_args, invoice_not_found, ...
  message: string;
  details?: Record<string, unknown>;
}

export interface ToolCall {
  round: number;
  tool_call_id: string;
  name: string;
  kind: ToolKind | string;
  args: unknown;
  ok: boolean;
  result: unknown;
  error: ToolFailure | null;
  latency_ms: number;
}

export type ProposalStatus = "pending_approval" | "approved" | "rejected";

export interface Proposal {
  id: number;
  module: Module;
  kind: string;
  target_id: string;
  summary: string;
  payload: Record<string, unknown>;
  status: ProposalStatus;
  run_id: number | null;
  created_at: string;
  reviewer: string | null;
  note: string | null;
  decision_result: Record<string, unknown> | null;
  decided_at: string | null;
}

export type RunStatus = "running" | "answered" | "max_steps" | "error";

export interface Run {
  id: number;
  module: Module;
  conversation_id: string;
  question: string;
  status: RunStatus;
  answer: string | null;
  error: string | null;
  model: string;
  rounds: number;
  latency_ms: number;
  created_at: string;
  finished_at: string | null;
  tool_count: number;
}

export interface RunDetail extends Run {
  tool_calls: ToolCall[];
  proposals: Proposal[];
}

export interface SampleQuestion {
  label: string;
  question: string;
}

// --- Bài 01: đối soát hóa đơn ----------------------------------------------------

export interface InvoiceRow {
  invoice_id: string;
  customer_id: string;
  currency: string;
  amount_total_minor: number;
  amount_due_minor: number;
  amount_due: string;
  status: "open" | "paid" | "cancelled";
  issued_at: string;
}

export interface TransferRow {
  transfer_id: string;
  customer_id: string;
  currency: string;
  amount_minor: number;
  amount: string;
  received_at: string;
  status: "unmatched" | "matched";
  memo: string | null;
  matched_invoice_id?: string | null;
}

export interface ExcludedTransfer extends TransferRow {
  reason_code: string;
  reason: string;
}

/** Kết quả công cụ find_two_transfer_match */
export interface MatchResult {
  invoice_id: string;
  customer_id: string;
  currency: string;
  amount_due_minor: number;
  amount_due: string;
  status: "matched" | "no_match";
  pair: TransferRow[] | null;
  total: string | null;
  reason: string;
  scan_order: TransferRow[];
  excluded: ExcludedTransfer[];
  other_pairs: { transfer_ids: string[]; note: string }[];
  rule: string;
}

export interface InvoiceData {
  invoices: InvoiceRow[];
  transfers: TransferRow[];
}
