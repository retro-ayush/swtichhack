"""Task dependency graph: cycle rejection and readiness computation."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable


class CycleError(ValueError):
    pass


def assert_acyclic(edges: Iterable[tuple[int, int]]) -> None:
    """edges are (task, depends_on). Raises CycleError on any cycle,
    including self-dependencies."""
    adj: dict[int, list[int]] = defaultdict(list)
    nodes: set[int] = set()
    for a, b in edges:
        if a == b:
            raise CycleError(f"task {a} depends on itself")
        adj[a].append(b)
        nodes.add(a)
        nodes.add(b)

    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(nodes, WHITE)

    def visit(n: int, stack: list[int]) -> None:
        color[n] = GREY
        stack.append(n)
        for m in adj.get(n, ()):
            if color[m] == GREY:
                cyc = stack[stack.index(m):] + [m]
                raise CycleError("circular dependency: " + " -> ".join(map(str, cyc)))
            if color[m] == WHITE:
                visit(m, stack)
        stack.pop()
        color[n] = BLACK

    for n in nodes:
        if color[n] == WHITE:
            visit(n, [])


def deps_satisfied(task_id: int, edges: Iterable[tuple[int, int]], completed: set[int]) -> bool:
    return all(dep in completed for t, dep in edges if t == task_id)


def ready_tasks(task_ids: Iterable[int], edges: list[tuple[int, int]], completed: set[int]) -> list[int]:
    return [t for t in task_ids if deps_satisfied(t, edges, completed)]
