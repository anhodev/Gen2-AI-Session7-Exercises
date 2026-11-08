// Kiểu dữ liệu khớp với response của FastAPI.

export interface Health {
  status: string;
  llm: string; // "mock" hoặc tên model
  database: string; // "postgresql" hoặc "sqlite"
}
