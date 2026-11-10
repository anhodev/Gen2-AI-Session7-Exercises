"""Test BFS Bài 04. Không cần database hay model."""

import random
import time

import pytest

from app.modules.incidents.algo import trace

SHOP_V7 = [
    ("DB", "Auth"), ("DB", "Reports"),
    ("Auth", "Checkout"), ("Auth", "MobileApp"),
    ("Checkout", "WebStore"),
]
CUSTOMER_FACING = {"Reports", "MobileApp", "WebStore"}


# --- Ca trong đề -------------------------------------------------------------------

def test_exercise_sample():
    result = trace(SHOP_V7, "DB")
    assert result.impacted(CUSTOMER_FACING) == [
        ("Reports", 1, ["DB", "Reports"]),
        ("MobileApp", 2, ["DB", "Auth", "MobileApp"]),
        ("WebStore", 3, ["DB", "Auth", "Checkout", "WebStore"]),
    ]


def test_exercise_layers_and_previous():
    result = trace(SHOP_V7, "DB")
    assert result.layers() == [["DB"], ["Auth", "Reports"], ["Checkout", "MobileApp"], ["WebStore"]]
    assert result.previous["WebStore"] == "Checkout" and result.previous["DB"] is None
    assert [v.service for v in result.visits] == ["DB", "Auth", "Reports", "Checkout", "MobileApp", "WebStore"]
    assert result.visits[0].discovered == ["Auth", "Reports"]


def test_all_impacted_includes_internal_services():
    names = [s for s, _, _ in trace(SHOP_V7, "DB").impacted()]
    assert names == ["Auth", "Reports", "Checkout", "MobileApp", "WebStore"]


def test_start_in_middle():
    assert trace(SHOP_V7, "Auth").impacted(CUSTOMER_FACING) == [
        ("MobileApp", 1, ["Auth", "MobileApp"]),
        ("WebStore", 2, ["Auth", "Checkout", "WebStore"]),
    ]


# --- Ca biên --------------------------------------------------------------------------

def test_duplicate_edges_counted_once():
    result = trace(SHOP_V7 + [("DB", "Auth"), ("DB", "Auth")], "DB")
    assert result.duplicate_edges == [("DB", "Auth"), ("DB", "Auth")]
    assert result.impacted(CUSTOMER_FACING) == trace(SHOP_V7, "DB").impacted(CUSTOMER_FACING)


def test_cycle_does_not_loop():
    edges = [("A", "B"), ("B", "C"), ("C", "A"), ("C", "D")]
    result = trace(edges, "A")
    assert result.distance == {"A": 0, "B": 1, "C": 2, "D": 3}
    assert result.visits[2].service == "C" and result.visits[2].already_seen == ["A"]


def test_self_loop():
    result = trace([("A", "A"), ("A", "B")], "A")
    assert result.impacted() == [("B", 1, ["A", "B"])]


def test_unreachable_service_not_included():
    edges = SHOP_V7 + [("CMS", "Blog")]
    result = trace(edges, "DB")
    assert result.path_to("Blog") is None
    assert "Blog" not in [s for s, _, _ in result.impacted()]


def test_upstream_not_impacted():
    # Mũi tên có chiều: Auth lỗi không làm DB bị ảnh hưởng
    assert "DB" not in trace(SHOP_V7, "Auth").distance


def test_start_without_edges():
    result = trace(SHOP_V7, "Lonely")
    assert result.impacted() == [] and result.layers() == [["Lonely"]]


def test_shortest_path_wins_over_longer():
    edges = [("DB", "A"), ("A", "B"), ("B", "Web"), ("DB", "Web")]
    assert trace(edges, "DB").path_to("Web") == ["DB", "Web"]


def test_tie_broken_alphabetically():
    edges = [("DB", "Zeta"), ("DB", "Alpha"), ("Zeta", "Web"), ("Alpha", "Web")]
    assert trace(edges, "DB").path_to("Web") == ["DB", "Alpha", "Web"]


@pytest.mark.parametrize("edges", [[("A",)], [("A", "")], [("A", 1)]])
def test_bad_edges(edges):
    with pytest.raises(ValueError):
        trace(edges, "A")


# --- So với cách tính khác ----------------------------------------------------------------

def relax_distances(edges, start):
    """Bellman-Ford với mọi cạnh nặng 1: chậm nhưng dễ đúng."""
    dist = {start: 0}
    for _ in range(len(edges) + 1):
        changed = False
        for a, b in edges:
            if a in dist and dist.get(b, 10**9) > dist[a] + 1:
                dist[b] = dist[a] + 1
                changed = True
        if not changed:
            break
    return dist


@pytest.mark.parametrize("seed", range(200))
def test_matches_bellman_ford_on_random_graphs(seed):
    rng = random.Random(seed)
    nodes = [f"S{i}" for i in range(rng.randint(1, 12))]
    edges = [(rng.choice(nodes), rng.choice(nodes)) for _ in range(rng.randint(0, 30))]
    start = rng.choice(nodes)
    result = trace(edges, start)

    assert result.distance == relax_distances(edges, start)
    edge_set = set(edges)
    for service, d, path in result.impacted():
        assert len(path) == d + 1 and path[0] == start and path[-1] == service
        assert all((a, b) in edge_set for a, b in zip(path, path[1:]))
    rows = result.impacted()
    assert rows == sorted(rows, key=lambda r: (r[1], r[0]))


def test_large_graph_is_fast():
    n = 200_000
    edges = [(f"S{i}", f"S{i + 1}") for i in range(n)] + [(f"S{i}", f"S{(i * 7) % n}") for i in range(n)]
    start = time.perf_counter()
    result = trace(edges, "S0")
    assert time.perf_counter() - start < 5
    assert len(result.distance) == n + 1
