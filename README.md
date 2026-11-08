# LangChain Tool Calling × Thuật toán

Bài tập Gen2-AI buổi 7: 4 tình huống doanh nghiệp ghép thành **một web app có ô chat**.

- **AI chọn công cụ**: model đọc câu hỏi, gọi công cụ (`@tool` + `bind_tools`) để lấy dữ liệu từ backend.
- **Backend tính toán**: thuật toán viết bằng Python, đọc lại dữ liệu từ database, không tin số liệu model tự điền.
- **Người dùng kiểm tra**: xem các công cụ đã gọi, dữ liệu đã dùng, và duyệt đề xuất. App không tự thay đổi dữ liệu.

| Bài | Câu hỏi | Thuật toán | Trạng thái |
|---|---|---|---|
| 01 | Hai khoản chuyển tiền nào trả đủ hóa đơn? | Hash map (tìm hai số có tổng cho trước) | Đang làm |
| 02 | Cần máy nhanh cỡ nào để kịp ca? | Tìm kiếm nhị phân trên đáp án | Đang làm |
| 03 | Gửi thông báo khi nào cho hợp lý? | Max-heap + hàng đợi chờ | Đang làm |
| 04 | Một dịch vụ hỏng sẽ ảnh hưởng đến đâu? | Duyệt đồ thị theo chiều rộng (BFS) | Đang làm |

## Cài đặt và chạy

Cần có Python 3.12 và Node.js 20 trở lên.

### Backend

```bash
cd backend
python3.12 -m venv myenv
myenv/bin/pip install -r requirements.txt
cp .env.example .env
myenv/bin/uvicorn app.main:app --reload --reload-dir app --port 8000
```

Để trống `OPENAI_API_KEY` (hoặc `MOCK_LLM=true`) thì app chạy bằng model giả lập, không cần API key.
Để trống `DB_HOST` thì app dùng SQLite tại `backend/data/app.db`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Mở http://localhost:3000. Trình duyệt gọi `/api/...`, Next.js chuyển tiếp sang FastAPI ở `BACKEND_INTERNAL_URL` (mặc định `http://localhost:8000`). API key chỉ nằm ở backend.

### Test

```bash
cd backend
myenv/bin/python -m pytest -q
```

## Dữ liệu

Mọi hóa đơn, giao dịch, lô hàng, khách hàng và dịch vụ trong `samples/` đều là dữ liệu giả để luyện tập.
