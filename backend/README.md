# Backend (FastAPI + LangChain)

Cài đặt và chạy: xem [README gốc](../README.md#cài-đặt-và-chạy).

## API

Swagger UI ở http://localhost:8000/docs khi backend đang chạy.

### Dùng chung

| Method | Đường dẫn | Việc |
|---|---|---|
| GET | `/health` | Đang dùng model nào (`mock` hoặc tên model), database nào, múi giờ |
| POST | `/chat` | `{module, question, conversation_id?}`. Chạy vòng lặp tool calling, trả câu trả lời, các lần gọi công cụ, đề xuất |
| GET | `/runs?module=&conversation_id=&limit=` | Lịch sử câu hỏi, mới nhất trước |
| GET | `/runs/{id}` | Một câu hỏi kèm các lần gọi công cụ (tên, tham số, kết quả hoặc lỗi) và đề xuất |
| GET | `/proposals?module=&status=` | Đề xuất |
| POST | `/proposals/{id}/approve` | `{reviewer, note?}`. Kiểm tra lại dữ liệu mới nhất rồi mới ghi. Dữ liệu đã đổi → 409, đề xuất vẫn chờ |
| POST | `/proposals/{id}/reject` | `{reviewer, note?}` |

`module` là `invoices`, `capacity`, `notifications` hoặc `incidents`.

### API phụ của từng bài

Mỗi bài có `GET /<bài>/samples` (câu hỏi mẫu), `GET /<bài>/data` (dữ liệu đang có) và `POST /<bài>/reset`
(khôi phục dữ liệu mẫu, đóng đề xuất đang chờ). Một số bài có thêm API để người dùng đổi dữ liệu khi thử:

| Bài | API | Dùng để thử |
|---|---|---|
| 02 | `PATCH /capacity/machines/{id}` `{rate_per_hour?, status?}` | Máy đổi tốc độ / bị đặt sau khi AI đề xuất |
| 03 | `PATCH /notifications/customers/{id}` `{opt_in}` | Khách đổi trạng thái đồng ý nhận tin |
| 03 | `PATCH /notifications/sources/{id}` `{available}` | Nguồn dữ liệu đồng ý không phản hồi |
| 04 | `POST /incidents/systems/{id}/publish` | Công bố sơ đồ phụ thuộc phiên bản mới (SHOP v7 → v8) |
| 04 | `PATCH /incidents/{id}` `{status}` | Sự cố chuyển sang đã xử lý xong |

Các API này không phải công cụ của AI. Không có API gửi tin, chuyển tiền hay khởi động lại dịch vụ.

## Cấu trúc

```
app/
  main.py               create_app: database, CORS, router; nạp dữ liệu mẫu lúc khởi động
  core/
    agent.py            Vòng lặp tool calling: bind_tools, kiểm tra tên + tham số, ToolMessage, giới hạn vòng
    chat.py             ask(): nối lịch sử hội thoại, chạy agent, lưu chat_runs + tool_calls
    mock_model.py       Model giả lập: mỗi bài có planner quyết định gọi công cụ nào
    tools.py            ToolArgs (không nhận ô lạ), ToolError, ToolContext, loại công cụ read/algorithm/action
    proposals.py        Tạo đề xuất (không tạo trùng), duyệt / từ chối
    entities.py         Bảng chat_runs, tool_calls, proposals
    router.py           API dùng chung
  modules/<bài>/
    algo.py             Thuật toán thuần Python, không cần database hay model
    tools.py            Công cụ @tool của bài
    planner.py          Planner cho model giả lập
    agent.py            System prompt, hàm duyệt đề xuất, AgentSpec
    entities.py         Bảng dữ liệu của bài
    store.py            Nạp dữ liệu mẫu từ samples/<bài>.json
    router.py           API phụ
samples/                Dữ liệu mẫu và câu hỏi mẫu
scripts/run_samples.py  Chạy hết câu hỏi mẫu qua backend đang chạy (mock hoặc model thật)
tests/
```

## Thêm một bài

1. Viết thuật toán trong `modules/<bài>/algo.py` và test riêng (`tests/test_<bài>_algo.py`).
2. Viết công cụ trong `tools.py`: tham số kế thừa `ToolArgs`, mã có `pattern`; gắn loại bằng `with_kind(...)`.
   Công cụ thuật toán chỉ nhận mã và tự đọc lại database.
3. Viết `planner.py` cho chế độ mock và `agent.py` với `AgentSpec(module, system_prompt, build_tools, mock_planner,
   approval_handlers, seed)`.
4. Thêm `AgentSpec` vào `AGENTS` trong `main.py`, gắn router phụ, và import `entities.py` của bài trong `create_tables` (`core/database.py`) để tạo bảng.

## Chạy câu hỏi mẫu

```bash
myenv/bin/python scripts/run_samples.py                 # cả 4 bài
myenv/bin/python scripts/run_samples.py incidents       # một bài
myenv/bin/python scripts/run_samples.py --out run.json  # lưu kết quả
```

In ra trạng thái, công cụ đã gọi và câu trả lời của từng câu. Trả mã lỗi khác 0 nếu có câu dừng vì `max_steps` hay lỗi model.
