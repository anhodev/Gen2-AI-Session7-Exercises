// Gọi FastAPI. Cách viết lấy từ buổi 4: một hàm request() dùng chung, đọc lỗi từ "detail".
import type { CapacityData, Health, InvoiceData, MachineChange, Module, NotificationData, Proposal, ProposalStatus, RunDetail, SampleQuestion } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

/** Lỗi API kèm "detail" gốc backend trả về. */
export class ApiError extends Error {
  constructor(message: string, public status: number, public detail: unknown = null) {
    super(message);
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...options?.headers },
    });
  } catch {
    throw new ApiError("Không kết nối được tới API.", 0);
  }

  if (!response.ok) {
    let message = `API trả về lỗi ${response.status}`;
    let detail: unknown = null;
    try {
      const body = await response.json();
      detail = body?.detail ?? null;
      if (typeof body?.detail === "string") message = body.detail;
      // Lỗi 422 do Pydantic kiểm tra khuôn: lấy câu đầu tiên
      if (Array.isArray(body?.detail) && body.detail[0]?.msg) message = String(body.detail[0].msg);
    } catch {}
    throw new ApiError(message, response.status, detail);
  }
  return response.json();
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  health: () => request<Health>("/health"),

  // Chat dùng chung cho cả 4 bài
  chat: (module: Module, question: string, conversationId: string | null) =>
    post<RunDetail>("/chat", { module, question, conversation_id: conversationId }),
  run: (id: number) => request<RunDetail>(`/runs/${id}`),
  proposals: (module: Module, status?: ProposalStatus) =>
    request<Proposal[]>(`/proposals?module=${module}${status ? `&status=${status}` : ""}`),
  decide: (id: number, action: "approve" | "reject", reviewer: string, note: string) =>
    post<Proposal>(`/proposals/${id}/${action}`, { reviewer, note: note || null }),

  // Bài 01
  invoiceSamples: () => request<SampleQuestion[]>("/invoices/samples"),
  invoiceData: () => request<InvoiceData>("/invoices/data"),
  resetInvoices: () => post<{ status: string; closed_proposals: number }>("/invoices/reset"),

  // Bài 02
  capacitySamples: () => request<SampleQuestion[]>("/capacity/samples"),
  capacityData: () => request<CapacityData>("/capacity/data"),
  resetCapacity: () => post<{ status: string; closed_proposals: number }>("/capacity/reset"),
  /** Người dùng đổi máy trên UI để thử ca "dữ liệu đổi sau khi AI đọc". Không phải công cụ của AI. */
  changeMachine: (id: string, change: MachineChange) =>
    request<{ machine_id: string; rate_per_hour: number; status: string; version: number }>(
      `/capacity/machines/${id}`, { method: "PATCH", body: JSON.stringify(change) },
    ),

  // Bài 03. Hai API PATCH là thao tác của người dùng để thử dữ liệu đổi / nguồn lỗi, không phải công cụ của AI.
  notificationSamples: () => request<SampleQuestion[]>("/notifications/samples"),
  notificationData: () => request<NotificationData>("/notifications/data"),
  resetNotifications: () => post<{ status: string; closed_proposals: number }>("/notifications/reset"),
  changeConsent: (customerId: string, optIn: boolean | null) =>
    request<{ customer_id: string; opt_in: string; version: number }>(
      `/notifications/customers/${customerId}`, { method: "PATCH", body: JSON.stringify({ opt_in: optIn }) },
    ),
  changeSource: (sourceId: string, available: boolean) =>
    request<{ source_id: string; available: boolean }>(
      `/notifications/sources/${sourceId}`, { method: "PATCH", body: JSON.stringify({ available }) },
    ),
};
