"""Bài 01 - Tìm hai khoản chuyển tiền cộng lại vừa đủ số tiền hóa đơn còn thiếu.

Không gọi model, không cần database: nhận danh sách giao dịch, trả cặp tìm được hoặc lý do.

Quy tắc:
  1. Chỉ xét giao dịch unmatched, cùng khách, cùng loại tiền, số tiền dương.
  2. Sắp theo giờ nhận, rồi mã giao dịch, để kết quả không đổi giữa các lần chạy.
  3. Quét một lượt với hash map {số tiền: giao dịch đầu tiên có số tiền đó}.
     Với khoản x, nếu đã gặp khoản (thiếu - x) thì có cặp. Cặp hoàn tất sớm nhất là cặp được chọn.
  4. Kiểm tra trước, thêm vào hash map sau: một giao dịch không ghép với chính nó.
Tiền là số nguyên theo đơn vị nhỏ nhất (đồng, cent), không dùng số thực.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

UNMATCHED = "unmatched"

MATCHED = "matched"
NO_MATCH = "no_match"

# Số chữ số lẻ của từng loại tiền: 1.500.000 VND, 250.00 USD
MINOR_DIGITS = {"VND": 0, "USD": 2}

EXCLUDE_REASONS = {
    "wrong_customer": "khác khách hàng",
    "wrong_currency": "khác loại tiền",
    "already_matched": "đã ghép với hóa đơn khác",
    "non_positive_amount": "số tiền không dương",
}


@dataclass(frozen=True)
class Transfer:
    id: str
    customer_id: str
    currency: str
    amount_minor: int
    received_at: datetime
    status: str = UNMATCHED


@dataclass
class MatchResult:
    status: str  # matched hoặc no_match
    pair: tuple[Transfer, Transfer] | None
    eligible: list[Transfer]  # giao dịch hợp lệ, theo thứ tự quét
    excluded: list[tuple[Transfer, str]]  # (giao dịch, mã lý do)
    other_pairs: list[tuple[str, str]] = field(default_factory=list)  # cặp khác cũng đủ tiền nhưng hoàn tất muộn hơn
    reason: str = ""


def check_amount(value: int, name: str) -> None:
    """
    Tiền phải là số nguyên (đơn vị nhỏ nhất).

    Raises:
        ValueError: Số thực, chuỗi, hoặc bool.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} phải là số nguyên theo đơn vị nhỏ nhất, đang là {value!r}")


def split_transfers(
    transfers: list[Transfer], customer_id: str, currency: str
) -> tuple[list[Transfer], list[tuple[Transfer, str]]]:
    """
    Tách giao dịch hợp lệ và giao dịch bị loại (kèm lý do).

    Args:
        transfers (list[Transfer]): Giao dịch đọc từ database.
        customer_id (str): Khách của hóa đơn.
        currency (str): Loại tiền của hóa đơn.

    Returns:
        tuple: (giao dịch hợp lệ đã sắp theo giờ nhận rồi mã, giao dịch bị loại kèm mã lý do).
    """
    eligible, excluded = [], []
    for t in transfers:
        check_amount(t.amount_minor, f"Số tiền của {t.id}")
        if t.customer_id != customer_id:
            excluded.append((t, "wrong_customer"))
        elif t.currency != currency:
            excluded.append((t, "wrong_currency"))
        elif t.status != UNMATCHED:
            excluded.append((t, "already_matched"))
        elif t.amount_minor <= 0:
            excluded.append((t, "non_positive_amount"))
        else:
            eligible.append(t)
    eligible.sort(key=lambda t: (t.received_at, t.id))
    excluded.sort(key=lambda item: (item[0].received_at, item[0].id))
    return eligible, excluded


def find_pair(amounts: list[int], target: int) -> tuple[int, int] | None:
    """
    Hash map: tìm cặp (i, j), i < j, amounts[i] + amounts[j] == target, hoàn tất sớm nhất.

    "Hoàn tất sớm nhất" là j nhỏ nhất; với j đó lấy i xuất hiện đầu tiên. O(n) thời gian.

    Args:
        amounts (list[int]): Số tiền theo thứ tự quét.
        target (int): Số tiền cần đủ.

    Returns:
        tuple[int, int] | None: Vị trí hai khoản, hoặc None nếu không có cặp.
    """
    first_seen: dict[int, int] = {}
    for j, x in enumerate(amounts):
        i = first_seen.get(target - x)
        if i is not None:
            return i, j
        first_seen.setdefault(x, j)  # thêm sau khi kiểm tra: không tự ghép với chính mình
    return None


def other_pairs(amounts: list[int], target: int, chosen: tuple[int, int], limit: int = 5) -> list[tuple[int, int]]:
    """
    Các cặp khác cũng đủ tiền, để giải thích vì sao không chọn. Tối đa limit cặp.

    Args:
        amounts (list[int]): Số tiền theo thứ tự quét.
        target (int): Số tiền cần đủ.
        chosen (tuple[int, int]): Cặp đã chọn.
        limit (int, optional): Số cặp tối đa. Defaults to 5.
    """
    seen: dict[int, list[int]] = {}
    found = []
    for j, x in enumerate(amounts):
        for i in seen.get(target - x, []):
            if (i, j) != chosen:
                found.append((i, j))
                if len(found) >= limit:
                    return found
        seen.setdefault(x, []).append(j)
    return found


def match_two_transfers(transfers: list[Transfer], customer_id: str, currency: str, amount_due_minor: int) -> MatchResult:
    """
    Tìm hai giao dịch trả đủ số tiền còn thiếu của hóa đơn.

    Args:
        transfers (list[Transfer]): Giao dịch đọc lại từ database.
        customer_id (str): Khách của hóa đơn.
        currency (str): Loại tiền của hóa đơn.
        amount_due_minor (int): Số tiền còn thiếu, đơn vị nhỏ nhất.

    Raises:
        ValueError: Số tiền không phải số nguyên, hoặc số tiền còn thiếu không dương.

    Returns:
        MatchResult: Cặp tìm được, hoặc no_match kèm lý do. Không bao giờ chọn cặp "gần đúng".
    """
    check_amount(amount_due_minor, "Số tiền còn thiếu")
    if amount_due_minor <= 0:
        raise ValueError("Số tiền còn thiếu phải lớn hơn 0")

    eligible, excluded = split_transfers(transfers, customer_id, currency)
    amounts = [t.amount_minor for t in eligible]
    found = find_pair(amounts, amount_due_minor)

    if found is None:
        if len(eligible) < 2:
            reason = f"Chỉ có {len(eligible)} giao dịch hợp lệ, cần ít nhất 2"
        else:
            reason = f"Không có hai giao dịch nào trong {len(eligible)} giao dịch hợp lệ cộng lại đúng {format_amount(amount_due_minor, currency)}"
        return MatchResult(NO_MATCH, None, eligible, excluded, reason=reason)

    i, j = found
    others = [(eligible[a].id, eligible[b].id) for a, b in other_pairs(amounts, amount_due_minor, found)]
    reason = f"{eligible[i].id} + {eligible[j].id} là cặp đầu tiên cộng đủ tiền khi quét theo giờ nhận"
    return MatchResult(MATCHED, (eligible[i], eligible[j]), eligible, excluded, others, reason)


def format_amount(amount_minor: int, currency: str) -> str:
    """
    Hiển thị tiền: 1500000 VND -> "1.500.000 VND"; 25050 USD -> "250.50 USD".

    Loại tiền chưa khai báo trong MINOR_DIGITS thì in số nguyên kèm mã tiền.
    """
    digits = MINOR_DIGITS.get(currency)
    if digits is None:
        return f"{amount_minor} {currency} (đơn vị nhỏ nhất)"
    sign = "-" if amount_minor < 0 else ""
    whole, frac = divmod(abs(amount_minor), 10**digits) if digits else (abs(amount_minor), 0)
    if currency == "VND":
        return f"{sign}{whole:,}".replace(",", ".") + " VND"
    return f"{sign}{whole:,}.{frac:0{digits}d} {currency}"
