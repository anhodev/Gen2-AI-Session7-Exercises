import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GenAI2 - Ho Xuan An - Bai tap buoi 7",
  description: "AI chọn công cụ. Backend tính toán. Người dùng kiểm tra kết quả.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="vi"><body>{children}</body></html>;
}
