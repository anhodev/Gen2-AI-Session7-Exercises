"""Bài 04 - Tìm phần có thể bị ảnh hưởng khi một dịch vụ lỗi, bằng BFS trên sơ đồ phụ thuộc.

Quy tắc (theo đề):
  - Mỗi dịch vụ là một điểm. Cạnh A -> B nghĩa là B phụ thuộc A: A lỗi thì B có thể bị ảnh hưởng.
  - Từ dịch vụ lỗi, BFS đi từng lớp: phụ thuộc trực tiếp, rồi gián tiếp.
  - Ghi nhớ điểm đã đi qua để không lặp vô hạn khi sơ đồ có vòng.
  - Lưu "điểm trước đó" để dựng lại đường đi ngắn nhất (ít cạnh nhất) tới từng dịch vụ.
  - Kết quả xếp theo số cạnh tăng dần, rồi mã dịch vụ theo alphabet.
  - Dịch vụ không có đường đi từ điểm lỗi thì không nằm trong danh sách ảnh hưởng.

Cạnh trùng chỉ tính một lần. Các điểm kề được xét theo alphabet để đường đi ra cùng một kết quả mỗi lần chạy.
Thời gian O(V + E) cho phần BFS (cộng O(E log E) để sắp điểm kề).

Không phụ thuộc database hay GenAI, test được riêng.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class Visit:
    """Một bước BFS: lấy điểm ra khỏi hàng đợi và xét các điểm kề."""

    service: str
    distance: int
    discovered: list[str] = field(default_factory=list)  # điểm mới thêm vào hàng đợi
    already_seen: list[str] = field(default_factory=list)  # điểm kề đã đi qua (vd do vòng), bỏ qua


@dataclass
class TraceResult:
    start: str
    distance: dict[str, int]
    previous: dict[str, str | None]
    visits: list[Visit]
    duplicate_edges: list[tuple[str, str]]

    def path_to(self, target: str) -> list[str] | None:
        """Đường đi ngắn nhất từ điểm lỗi tới target, dựng lại từ "điểm trước đó". None nếu không tới được."""
        if target not in self.distance:
            return None
        path = [target]
        while (prev := self.previous[path[-1]]) is not None:
            path.append(prev)
        return path[::-1]

    def layers(self) -> list[list[str]]:
        """Các lớp BFS: lớp 0 là điểm lỗi, lớp 1 phụ thuộc trực tiếp..."""
        result: list[list[str]] = []
        for service, d in self.distance.items():
            while len(result) <= d:
                result.append([])
            result[d].append(service)
        return [sorted(layer) for layer in result]

    def impacted(self, targets: set[str] | None = None) -> list[tuple[str, int, list[str]]]:
        """
        Dịch vụ tới được từ điểm lỗi (trừ chính nó), theo số cạnh rồi mã dịch vụ.

        Args:
            targets (set[str] | None): Chỉ lấy các dịch vụ này (vd dịch vụ người dùng thấy). None: lấy hết.
        """
        rows = [
            (s, d, self.path_to(s)) for s, d in self.distance.items()
            if s != self.start and (targets is None or s in targets)
        ]
        return sorted(rows, key=lambda r: (r[1], r[0]))


def check_edges(edges: list[tuple[str, str]]) -> None:
    """
    Raises:
        ValueError: Cạnh không phải cặp hai mã dịch vụ không rỗng.
    """
    for edge in edges:
        if len(edge) != 2 or not all(isinstance(x, str) and x for x in edge):
            raise ValueError(f"Cạnh không hợp lệ: {edge!r}")


def trace(edges: list[tuple[str, str]], start: str) -> TraceResult:
    """
    BFS từ dịch vụ lỗi theo chiều mũi tên.

    Args:
        edges (list[tuple[str, str]]): Cạnh (A, B): B phụ thuộc A. Có thể trùng, có thể có vòng.
        start (str): Dịch vụ lỗi.

    Raises:
        ValueError: Cạnh không hợp lệ.

    Returns:
        TraceResult: Khoảng cách, điểm trước đó, các bước duyệt, cạnh trùng.
    """
    check_edges(edges)
    neighbors: dict[str, set[str]] = {}
    seen_edges: set[tuple[str, str]] = set()
    duplicates: list[tuple[str, str]] = []
    for a, b in edges:
        if (a, b) in seen_edges:
            duplicates.append((a, b))
            continue
        seen_edges.add((a, b))
        neighbors.setdefault(a, set()).add(b)

    distance = {start: 0}
    previous: dict[str, str | None] = {start: None}
    visits: list[Visit] = []
    queue = deque([start])
    while queue:
        current = queue.popleft()
        visit = Visit(current, distance[current])
        for nxt in sorted(neighbors.get(current, ())):
            if nxt in distance:
                visit.already_seen.append(nxt)
                continue
            distance[nxt] = distance[current] + 1
            previous[nxt] = current
            visit.discovered.append(nxt)
            queue.append(nxt)
        visits.append(visit)

    return TraceResult(start, distance, previous, visits, duplicates)
