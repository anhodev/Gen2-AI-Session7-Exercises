"""Chạy toàn bộ câu hỏi mẫu của 4 bài qua backend đang chạy, in công cụ đã gọi và câu trả lời.

Dùng để kiểm tra nhanh với model thật: điền OPENAI_API_KEY, MOCK_LLM=false trong backend/.env,
khởi động lại backend rồi chạy:

    myenv/bin/python scripts/run_samples.py                 # cả 4 bài
    myenv/bin/python scripts/run_samples.py incidents       # một bài
    myenv/bin/python scripts/run_samples.py --out run.json  # lưu kết quả để so sánh

Script khôi phục dữ liệu mẫu của từng bài trước khi chạy, không duyệt đề xuất nào.
Mọi lần chạy đều được lưu lại, xem ở trang "Lịch sử xử lý".
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

MODULES = ["invoices", "capacity", "notifications", "incidents"]


def call(base: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        base + path, data=data, method="GET" if body is None else "POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("modules", nargs="*", help=f"Bài cần chạy: {', '.join(MODULES)}. Bỏ trống = cả 4 bài")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--out", help="Lưu kết quả ra file JSON")
    args = parser.parse_args()
    unknown = [m for m in args.modules if m not in MODULES]
    if unknown:
        parser.error(f"Không có bài {', '.join(unknown)}. Chọn trong: {', '.join(MODULES)}")

    try:
        health = call(args.base_url, "/health")
    except urllib.error.URLError as exc:
        print(f"Không kết nối được backend ở {args.base_url}: {exc.reason}")
        return 1
    print(f"Model: {health['llm']} · Database: {health['database']}\n")

    report, problems = [], 0
    for module in args.modules or MODULES:
        call(args.base_url, f"/{module}/reset", {})
        print(f"=== {module} ===")
        for sample in call(args.base_url, f"/{module}/samples"):
            run = call(args.base_url, "/chat", {"module": module, "question": sample["question"]})
            tools = [c["name"] + ("" if c["ok"] else f" ✗{c['error']['code']}") for c in run["tool_calls"]]
            if run["status"] != "answered":
                problems += 1
            print(f"- [{run['status']}] {sample['label']} (#{run['id']}, {run['rounds']} vòng, {run['latency_ms']} ms)")
            print(f"  Hỏi: {sample['question']}")
            print(f"  Công cụ: {' → '.join(tools) or '(không gọi)'}")
            answer = (run["answer"] or run["error"] or "").strip().replace("\n", "\n    ")
            print(f"  Trả lời: {answer}\n")
            report.append({"module": module, "label": sample["label"], "question": sample["question"],
                           "run_id": run["id"], "status": run["status"], "tools": tools, "answer": run["answer"]})
        # Đề xuất tạo khi chạy thử không còn dùng: khôi phục để đóng chúng
        call(args.base_url, f"/{module}/reset", {})

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"model": health["llm"], "runs": report}, f, ensure_ascii=False, indent=2)
        print(f"Đã lưu {len(report)} lần chạy vào {args.out}")
    print(f"{len(report)} câu hỏi, {problems} câu không trả lời xong (max_steps/error).")
    return 0 if problems == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
