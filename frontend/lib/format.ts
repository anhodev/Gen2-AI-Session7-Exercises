// Hiển thị thời gian theo múi giờ APP_TIMEZONE của backend (mặc định GMT+7),
// không để trình duyệt tự đổi sang múi giờ máy người xem. Luôn ghi kèm múi giờ.
// - Dữ liệu bài tập (giờ nhận tiền...) backend đã đổi sẵn sang APP_TIMEZONE: in nguyên văn.
// - Mốc hệ thống (lịch sử, đề xuất) backend trả UTC: dùng localTime() để đổi.

let displayTimezone = "Asia/Ho_Chi_Minh";

/** Gọi một lần sau khi đọc /health. */
export function setDisplayTimezone(tz: string) {
  displayTimezone = tz;
}

/** "2026-11-09T07:35:00+00:00" -> "09/11 14:35 GMT+7" (đổi sang múi giờ APP_TIMEZONE) */
export function localTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: displayTimezone, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
      hourCycle: "h23", timeZoneName: "shortOffset",
    }).formatToParts(date).map((p) => [p.type, p.value]),
  );
  return `${parts.day}/${parts.month} ${parts.hour}:${parts.minute} ${parts.timeZoneName}`;
}

/** "2026-10-21T09:50:00+07:00" -> "GMT+7"; "+05:30" -> "GMT+5:30"; "Z" hoặc "+00:00" -> "GMT+0" */
export function gmtLabel(iso: string): string {
  const match = iso.match(/([+-])(\d{2}):(\d{2})$|Z$/);
  if (!match) return "";
  if (!match[1]) return "GMT+0";
  const [, sign, hours, minutes] = match;
  return `GMT${sign}${Number(hours)}${minutes !== "00" ? `:${minutes}` : ""}`;
}

/** "2026-10-21T09:50:00+07:00" -> "21/10 09:50" (không kèm múi giờ, dùng khi múi giờ đã ghi ở chỗ khác) */
export function dayTime(iso: string): string {
  const match = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!match) return iso;
  const [, , month, day, hour, minute] = match;
  return `${day}/${month} ${hour}:${minute}`;
}

/** "2026-10-21T09:50:00+07:00" -> "09:50" */
export function clock(iso: string): string {
  const match = iso.match(/T(\d{2}):(\d{2})/);
  return match ? `${match[1]}:${match[2]}` : iso;
}

/** "2026-10-21T09:50:00+07:00" -> "21/10 09:50 GMT+7" */
export function shortTime(iso: string): string {
  const label = gmtLabel(iso);
  return label ? `${dayTime(iso)} ${label}` : dayTime(iso);
}

/** Số chữ số lẻ của đơn vị nhỏ nhất, giống backend (MINOR_DIGITS). */
const MINOR_DIGITS: Record<string, number> = { VND: 0, USD: 2 };

/** 1500000 VND -> "1.500.000 VND"; 25050 USD -> "250.50 USD". Giống format_amount ở backend. */
export function formatMoney(minor: number, currency: string): string {
  const digits = MINOR_DIGITS[currency];
  if (digits === undefined) return `${minor} ${currency} (đơn vị nhỏ nhất)`;
  const sign = minor < 0 ? "-" : "";
  const abs = Math.abs(minor);
  const whole = Math.floor(abs / 10 ** digits);
  if (currency === "VND") return `${sign}${whole.toLocaleString("en-US").replace(/,/g, ".")} VND`;
  const frac = String(abs % 10 ** digits).padStart(digits, "0");
  return `${sign}${whole.toLocaleString("en-US")}.${frac} ${currency}`;
}

/** 1834 -> "1,8 giây"; 42 -> "42 ms" */
export function duration(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1).replace(".", ",")} giây` : `${ms} ms`;
}
