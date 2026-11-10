# Frontend (Next.js)

Cài đặt và chạy: xem [README gốc](../README.md#cài-đặt-và-chạy).

```bash
npm install
npm run dev     # http://localhost:3000
npm run build   # kiểm tra build
```

Trình duyệt chỉ gọi `/api/...` cùng origin. Route [app/api/[...path]/route.ts](app/api/[...path]/route.ts) chuyển tiếp
sang FastAPI ở `BACKEND_INTERNAL_URL` (mặc định `http://localhost:8000`), nên không cần CORS và API key không bao giờ
ra trình duyệt. Đổi địa chỉ backend: copy `.env.example` thành `.env.local`.

| File | Nội dung |
|---|---|
| `app/page.tsx` | Khung trang: sidebar, chuyển giữa 4 bài và Lịch sử. Trang bài đã mở được giữ lại để không mất hội thoại |
| `components/chat.tsx` | Ô chat dùng chung: câu trả lời, danh sách công cụ đã gọi (bấm để xem tham số / kết quả), thẻ duyệt đề xuất |
| `components/invoices.tsx` … `incidents.tsx` | Trang từng bài: dữ liệu AI đã dùng + dữ liệu trong hệ thống |
| `components/history.tsx` | Lịch sử xử lý: lọc theo bài, xem lại công cụ, kết quả thuật toán, câu trả lời, đề xuất |
| `lib/api.ts`, `lib/types.ts` | Gọi API và kiểu dữ liệu khớp với response của FastAPI |
| `lib/format.ts` | Hiển thị giờ theo `APP_TIMEZONE` của backend (mặc định GMT+7), định dạng tiền |
