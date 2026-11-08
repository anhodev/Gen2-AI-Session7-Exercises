"use client";

// Khung trang lấy từ buổi 4: sidebar tối + topbar + nội dung theo từng màn hình.
import { useEffect, useState } from "react";
import {
  AlertTriangle, BellRing, Bot, Command, Database, Factory, History, Menu, Network, ReceiptText, Wrench, X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "@/lib/api";
import type { Health } from "@/lib/types";
import { Empty } from "@/components/ui";

type View = "invoices" | "capacity" | "notifications" | "incidents" | "history";

const NAV: { id: View; label: string; icon: LucideIcon; ready: boolean }[] = [
  { id: "invoices", label: "01 · Đối soát hóa đơn", icon: ReceiptText, ready: false },
  { id: "capacity", label: "02 · Công suất máy", icon: Factory, ready: false },
  { id: "notifications", label: "03 · Lịch gửi thông báo", icon: BellRing, ready: false },
  { id: "incidents", label: "04 · Tác động sự cố", icon: Network, ready: false },
];

const TITLES: Record<View, [string, string]> = {
  invoices: ["Hai khoản chuyển tiền nào trả đủ hóa đơn?", "AI đọc hóa đơn và giao dịch qua công cụ. Code tìm cặp bằng hash map. Kế toán duyệt đề xuất đối soát."],
  capacity: ["Cần máy nhanh cỡ nào để kịp ca?", "AI gom lô hàng, giờ ca và máy rảnh qua công cụ. Code tìm tốc độ tối thiểu bằng tìm kiếm nhị phân."],
  notifications: ["Gửi thông báo khi nào cho hợp lý?", "AI đọc tin chờ gửi, quy tắc liên hệ và trạng thái đồng ý. Code xếp lịch bằng max-heap và hàng đợi chờ."],
  incidents: ["Một dịch vụ hỏng sẽ ảnh hưởng đến đâu?", "AI đọc sự cố và sơ đồ dịch vụ. Code duyệt đồ thị bằng BFS và dựng đường ảnh hưởng ngắn nhất."],
  history: ["Lịch sử xử lý", "Câu hỏi, các lần gọi công cụ (tên, tham số, kết quả hoặc lỗi), kết quả thuật toán và câu trả lời."],
};

export default function Home() {
  const [view, setView] = useState<View>("invoices");
  const [mobileNav, setMobileNav] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [connected, setConnected] = useState(true);

  useEffect(() => {
    api.health().then((h) => { setHealth(h); setConnected(true); }).catch(() => setConnected(false));
  }, []);

  const navigate = (next: View) => { setView(next); setMobileNav(false); };

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNav ? "open" : ""}`}>
        <div className="brand">
          <div className="brand-mark"><Command size={20} /></div>
          <div><strong>Ho Xuan An</strong><span>BÀI TẬP BUỔI 7</span></div>
          <button className="sidebar-close" onClick={() => setMobileNav(false)}><X size={18} /></button>
        </div>
        <nav>
          <p className="nav-heading">BÀI TẬP</p>
          {NAV.map(({ id, label, icon: Icon, ready }) => (
            <button key={id} onClick={() => navigate(id)} className={view === id ? "active" : ""}>
              <Icon size={18} /><span>{label}</span>{!ready && <em>Sắp có</em>}
            </button>
          ))}
          <p className="nav-heading">THEO DÕI</p>
          <button onClick={() => navigate("history")} className={view === "history" ? "active" : ""}>
            <History size={18} /><span>Lịch sử xử lý</span>
          </button>
        </nav>
        <div className="sidebar-spacer" />
        <div className="upgrade-card">
          <div className="glow" />
          <Bot size={22} />
          <strong>GenAI: {health?.llm ?? "…"}</strong>
          <span><Database size={11} /> Database: {health?.database ?? "…"}</span>
          <span>AI chọn công cụ. Backend tính toán. Người dùng kiểm tra kết quả.</span>
        </div>
      </aside>
      {mobileNav && <button className="sidebar-overlay" onClick={() => setMobileNav(false)} aria-label="Đóng menu" />}

      <main className="main-content">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMobileNav(true)} aria-label="Mở menu"><Menu size={20} /></button>
          <div>
            <p className="eyebrow">LANGCHAIN TOOL CALLING × THUẬT TOÁN</p>
            <h1>{TITLES[view][0]}</h1>
            <p className="subtitle">{TITLES[view][1]}</p>
          </div>
        </header>
        {!connected && (
          <div className="offline-banner"><AlertTriangle size={16} /> Chưa kết nối được backend. Chạy FastAPI ở cổng 8000: <code>cd backend && myenv/bin/uvicorn app.main:app --reload --reload-dir app</code></div>
        )}
        <section className="panel"><Empty icon={Wrench} text="Đang làm, sẽ có ở các bước sau." /></section>
      </main>
    </div>
  );
}
