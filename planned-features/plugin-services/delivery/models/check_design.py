"""Finite design checks; no runtime implementation, sockets, or external state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from itertools import permutations, product


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_current_frame() -> dict[str, object]:
    active = {"A": (7, "thread-1"), "B": (3, "thread-1")}
    captured = ("A", 7, "thread-1")
    stack = ["A", "handler-outer", "B"]

    def old_guard() -> bool:
        owner, generation, thread = captured
        return active.get(owner) == (generation, thread)

    def current_guard() -> bool:
        return old_guard() and stack[-1] == captured[0]

    require(old_guard(), "Counterexample must pass generation/thread checks")
    require(not current_guard(), "B must not borrow A's still-active client")
    require(stack[-1] != "handler-outer", "Outer handler window is suspended too")
    stack.pop()
    stack.pop()
    require(current_guard(), "A's original client must work after B returns")
    active["A"] = (8, "thread-1")
    require(not current_guard(), "A later activation must reject the old client")
    return {"ancestor_counterexample_reproduced": True, "resumption_checked": True}


def reaches(edges: set[tuple[str, str]], start: str, end: str) -> bool:
    pending = [start]
    seen: set[str] = set()
    while pending:
        node = pending.pop()
        if node == end:
            return True
        if node not in seen:
            seen.add(node)
            pending.extend(target for source, target in edges if source == node)
    return False


def stable_order(
    vertices: tuple[str, ...], edges: set[tuple[str, str]]
) -> tuple[str, ...] | None:
    remaining = set(vertices)
    ordered: list[str] = []
    while remaining:
        roots = sorted(
            node
            for node in remaining
            if not any(
                source in remaining and target == node for source, target in edges
            )
        )
        if not roots:
            return None
        node = roots[0]
        remaining.remove(node)
        ordered.append(node)
    return tuple(ordered)


def check_scope_dags() -> dict[str, object]:
    vertices = ("A", "B", "C", "D")
    possible_edges = tuple(permutations(vertices, 2))
    acyclic = 0
    rejected_cycle_edges = 0
    for bits in product((False, True), repeat=len(possible_edges)):
        edges = {edge for bit, edge in zip(bits, possible_edges, strict=True) if bit}
        order = stable_order(vertices, edges)
        if order is None:
            continue
        acyclic += 1
        positions = {node: index for index, node in enumerate(order)}
        require(
            all(positions[source] < positions[target] for source, target in edges),
            "Cleanup must visit each caller before its dependency",
        )
        for source, target in possible_edges:
            cycle = reaches(edges, target, source)
            new_order = stable_order(vertices, edges | {(source, target)})
            require((new_order is None) == cycle, "Admission and cleanup disagree")
            rejected_cycle_edges += int(cycle)
    require(acyclic == 543, "All labeled four-vertex DAGs must be covered")
    completed_edges = {("A", "B")}
    require(reaches(completed_edges, "A", "B"), "Temporal reverse edge must reject")
    root_edges = {("root", "A"), ("A", "B")}
    order = stable_order(("root", "A", "B"), root_edges)
    if order is None:
        raise AssertionError("Root graph must be acyclic")
    touched = {"A", "B"}
    require(
        tuple(node for node in order if node in touched) == ("A", "B"), "No root close"
    )
    require(
        stable_order(("A", "B"), {("B", "A")}) == ("B", "A"), "Scopes are independent"
    )
    return {
        "directed_graphs_examined": 2 ** len(possible_edges),
        "acyclic_graphs": acyclic,
        "cycle_forming_edge_checks": rejected_cycle_edges,
    }


def check_failure_cleanup() -> dict[str, object]:
    primary = ValueError("provider C defect")
    first_termination = KeyboardInterrupt("first termination")
    errors: list[BaseException] = [primary]
    attempted: list[str] = []
    for name, failure in (
        ("A-close", first_termination),
        ("B-close", RuntimeError("secondary")),
        ("state-destroy", SystemExit(3)),
        ("api-close", None),
    ):
        attempted.append(name)
        if failure is not None:
            errors.append(failure)
    termination = next(error for error in errors if not isinstance(error, Exception))
    require(termination is first_termination, "Preserve first termination")
    require(
        len(attempted) == 4 and errors[0] is primary, "Exhaust cleanup, retain origin"
    )

    actual_outcome = {"child_exit": 2, "process_started": True}
    latched_failure = primary
    saved_goal_value = actual_outcome
    after_hook_result = {"exit_code": 0, "value": None}
    final = {
        **after_hook_result,
        "exit_code": 70,
        "value": saved_goal_value,
        "error": latched_failure,
    }
    require(final["value"] is actual_outcome, "Preserve actual child outcome")
    require(final["exit_code"] == 70, "Success rewrite must not clear managed failure")
    return {"all_finalizers_attempted": attempted, "first_termination_preserved": True}


@dataclass(frozen=True)
class Record:
    name: str
    directory: str
    image_ids: tuple[str, ...]


def encoded_size(records: tuple[Record, ...]) -> int:
    value = {
        "snapshot_id": "s" * 32,
        "next_cursor": "c" * 32,
        "records": [asdict(record) for record in records],
    }
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def pages(snapshot: tuple[Record, ...], budget: int) -> tuple[tuple[Record, ...], ...]:
    result: list[tuple[Record, ...]] = []
    page: tuple[Record, ...] = ()
    for record in snapshot:
        if encoded_size((record,)) > budget:
            raise ValueError("record_too_large")
        candidate = (*page, record)
        if encoded_size(candidate) > budget:
            result.append(page)
            page = (record,)
        else:
            page = candidate
    result.append(page)
    return tuple(result)


def check_snapshots_and_barrier() -> dict[str, object]:
    backing = [
        Record(
            name=f"lab-{index}",
            directory=f"/labs/{index}/" + "x" * 400,
            image_ids=tuple("sha256:" + str(image) * 64 for image in range(4)),
        )
        for index in range(1600)
    ]
    snapshot = tuple(backing)
    full_bytes = encoded_size(snapshot)
    require(
        full_bytes > 1024 * 1024, "Fixture must expose the one-frame inventory flaw"
    )
    small_pages = pages(snapshot, 4096)
    require(
        all(encoded_size(page) <= 4096 for page in small_pages), "Each page must fit"
    )
    require(
        tuple(record for page in small_pages for record in page) == snapshot,
        "No omissions",
    )
    backing[0] = replace(backing[0], name="newly-committed")
    require(
        snapshot[0].name != backing[0].name, "Existing snapshot must remain consistent"
    )
    next_snapshot = tuple(backing)
    require(
        next_snapshot[0].name == "newly-committed", "Next read must observe new data"
    )
    try:
        pages((Record("oversized", "x" * 5000, ()),), 4096)
    except ValueError as error:
        require(str(error) == "record_too_large", "Size error must be explicit")
    else:
        raise AssertionError("Oversized records must not be silently split")

    for fail_at in (0, 1, 2, None):
        persisted: list[int] = []
        deletions = 0
        failed = False
        for batch in range(3):
            if batch == fail_at:
                failed = True
                break
            persisted.append(batch)
        if not failed:
            require(
                persisted == [0, 1, 2], "Every acknowledgment must precede deletion"
            )
            deletions += 1
        require(
            deletions == int(fail_at is None), "Any failed batch must block deletion"
        )
    return {
        "inventory_bytes": full_bytes,
        "small_pages": len(small_pages),
        "batch_failure_cases": 3,
    }


def check_deadlines() -> dict[str, object]:
    combinations = 0
    for now, parent, requested in product((0, 5, 20), (1, 10, 30), (1, 5, 30, 86400)):
        inherited = min(parent, now + requested, now + 30)
        require(inherited <= parent, "Nested duration cannot extend parent deadline")
        combinations += 1
    upstream_in_flight = True
    waiting = {"peer-A": 100, "peer-B": 5}
    now = 6
    expired = [peer for peer, deadline in waiting.items() if deadline <= now]
    for peer in expired:
        del waiting[peer]
    require(
        upstream_in_flight and expired == ["peer-B"],
        "Queue expiry cannot wait for upstream",
    )
    require("peer-A" in waiting, "Healthy peer must remain admitted")
    composite_deadline = 30
    for page_start in (0, 9, 20, 29):
        remaining = composite_deadline - page_start
        require(
            page_start + remaining == composite_deadline, "Pages share one deadline"
        )
    lost_first_page_snapshot = {"snapshot-1": composite_deadline}
    next_poll = 31
    live_snapshots = {
        key: expiry
        for key, expiry in lost_first_page_snapshot.items()
        if expiry > next_poll
    }
    require(
        not live_snapshots, "Lost first-page snapshot must not poison future polling"
    )
    return {
        "nested_budget_combinations": combinations,
        "independent_queue_expiry": True,
        "composite_deadline_and_snapshot_expiry": True,
    }


def main() -> None:
    results = {
        "current_frame": check_current_frame(),
        "scope_dags": check_scope_dags(),
        "failure_cleanup": check_failure_cleanup(),
        "snapshots_and_barrier": check_snapshots_and_barrier(),
        "deadlines": check_deadlines(),
    }
    print(json.dumps({"status": "passed", "checks": results}, indent=2))


if __name__ == "__main__":
    main()
