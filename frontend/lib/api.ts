// Gọi FastAPI. Cách viết lấy từ buổi 4: một hàm request() dùng chung, đọc lỗi từ "detail".
import type { Health } from "./types";

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

export const api = {
  health: () => request<Health>("/health"),
};
