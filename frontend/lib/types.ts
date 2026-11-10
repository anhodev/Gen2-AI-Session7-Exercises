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

// --- Bài 02: công suất máy ---------------------------------------------------------

export type MachineStatus = "available" | "busy" | "maintenance" | "reserved";

export interface MachineView {
  machine_id: string;
  name: string;
  rate_per_hour: number;
  status: MachineStatus;
  version: number;
  hours_needed?: number;
}

export interface RateCheck {
  rate: number;
  hours_per_batch: number[];
  total_hours: number;
  fits: boolean;
  calculation: string; // "3 + 1 + 3 + 1 = 8 giờ"
}

export interface SearchStep {
  low: number;
  high: number;
  mid: number;
  hours: number;
  fits: boolean;
}

export type RateStatus = "ok" | "no_open_batches" | "impossible_under_rules" | "no_machine_fast_enough";

/** Kết quả công cụ calculate_min_required_rate */
export interface RateResult {
  line_id: string;
  shift_id: string;
  shift_name: string;
  hours_left: number;
  status: RateStatus;
  min_rate: number | null;
  reason: string;
  batches: { batch_id: string; product: string; quantity: number }[];
  zero_batches: { batch_id: string; product: string; note: string }[];
  check_at_min: RateCheck | null;
  check_below_min: RateCheck | null;
  search_steps: SearchStep[];
  chosen_machine: MachineView | null;
  fast_enough: MachineView[];
  too_slow: MachineView[];
  data_changed: { machine_id: string; before: string; now: string }[];
  rule: string;
}

export interface CapacityData {
  lines: { line_id: string; name: string }[];
  shifts: { shift_id: string; line_id: string; name: string; hours_left: number }[];
  batches: { batch_id: string; line_id: string; product: string; quantity: number; status: "open" | "done" }[];
  machines: (MachineView & { line_id: string; reserved_shift_id: string | null })[];
}

export interface MachineChange {
  rate_per_hour?: number;
  status?: "available" | "busy" | "maintenance";
}
