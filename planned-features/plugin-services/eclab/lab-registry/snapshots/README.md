# Bounded snapshots and observation batches

Back to [lab registry](../README.md). This is a refinement to the seed's unqualified
single-call `records()` design, motivated by its conflict with local/wire size
equivalence. It is domain paging, not a generic streaming-RPC feature.

## Primitive methods

| Method | Contract |
| --- | --- |
| `begin_snapshot` | Read one immutable persisted snapshot in the owner's finite transaction; return its first bounded page, opaque snapshot ID and optional next cursor |
| `read_snapshot_page` | Return the next page of that same snapshot; validate ID/cursor, scope and initiating caller |
| `end_snapshot` | Idempotently release an owned snapshot; final-page release and scope close also release it |
| `commit_observation_batch` | Compare all pre-sample record bases, then merge one bounded complete-observation batch in one short transaction; acknowledge only after successful exit |
| `validate_snapshot` | In a finite transaction, compare the current canonical inventory fingerprint with the caller's complete snapshot; return match or declared `inventory_changed` |

Snapshot IDs/cursors are opaque, invocation-bound, and associated with service scope
and the caller that began the read. They carry no state capability and cannot be
used by another scope/caller. The provider stores only immutable records and bounded
cursor progress. No lock remains held while the consumer processes a page.

Initial domain limits: at most one live snapshot per `(scope, initiating caller)`,
at most 16 snapshots per invocation, and at most 32 MiB aggregate **charged canonical
snapshot data** retained by this provider. These limits are application-configurable
within documented bounds and produce explicit domain errors when exceeded. They
are not Python RSS limits or a bound on the existing state API's whole-file read
allocation. A streaming state reader would be a separate future core change.

Each snapshot also has a fixed expiration no later than the admitted first call's
business deadline. Page calls cannot extend it. Expire stale snapshots on every
registry service entry and during scope close; no background provider thread is
needed. This handles a first-page timeout after allocation but before the client
learned the snapshot ID: the next fresh poll can reclaim the expired slot. The
limit bounds retained data between calls; expiration does not promise an immediate
timer-driven callback while the application is idle.

Each page fits the current method's actual encoded result-payload budget, including
page metadata, depth and node limits. Encode/count record sizes and envelope overhead
incrementally; do not split one record's image-ID set or silently omit it. A single
record too large for the negotiated payload returns a declared size error and releases
the snapshot. READY directory sizing is unrelated to this inventory protocol.

## Complete inventory facade

```text
records():
    deadline = one absolute budget for this complete facade call
    snapshot_id = none
    try:
        page = begin_snapshot(budget=remaining(deadline))
        snapshot_id = page.snapshot_id
        result = []
        while true:
            validate same snapshot, expected cursor progress and aggregate domain bound
            append decoded immutable records
            if page.next_cursor is none: return tuple(result)
            page = read_snapshot_page(snapshot_id, page.next_cursor,
                                      budget=remaining(deadline))
    finally:
        if snapshot_id exists: attempt end_snapshot(snapshot_id)
        preserve any primary error; mandatory scope close is the final fallback
```

All pages refer to the original immutable snapshot even if another process commits
between pages. A new `records()` invocation starts a new transaction/snapshot. On
any page failure the caller receives unavailable/error, not the accumulated prefix.
The final page can release storage immediately; an idempotent `end_snapshot` still
works if that release already occurred. If finalization itself has a managed defect,
the core latch remains even when an expected read error was primary.

`snapshot()` shares the complete paging implementation but returns a frozen
`RegistrySnapshot(records, inventory_fingerprint)` with `base_for(key)` for record
preconditions. `records()` returns only its records for read-only callers. Fingerprints
are SHA-256 over the capability-defined canonical record/inventory encoding; an
absent key has a distinct `None` base. They are equality preconditions, not authority
tokens or timestamps, and require no additional persisted field. Codec vectors must
fix their canonical form before B4. Page reads use the retained immutable snapshot;
only begin/validation/commit operations reread state, not every page.

An observer captures the complete baseline before sampling Docker, includes each
observed key's base in its commit, and discards conflicted observations. Validate all
bases in a batch under the same transaction before writing any record. This blocks
an older sample from overwriting a different value committed after its baseline.
All owned writers, including automatic registry tracking, must use the same rule.
It does not order observations by wall clock or claim that an arbitrary external
writer cooperates. Per-observer sequences/timestamps alone would not order different
observers and are not adopted as a substitute.

## Complete commit facade

```text
commit_observations(observations):
    deadline = one absolute budget for this complete facade call
    validate complete observations with pre-sample bases; prepare frame-fitting batches
    # Detect an oversized individual record before starting any writes.
    acknowledgments = []
    for batch in batches:
        ack = commit_observation_batch(batch, budget=remaining(deadline))
        validate explicit acknowledgment of this batch
        acknowledgments.append(ack)
    return acknowledgment of the complete supplied observation set

reclaim:
    plan = plan_from_complete_inventory_and_Docker_observation()
    commit_observations(plan.complete_observations)
    fresh = snapshot()                    # after our own acknowledged changes
    require current_inventory_and_Docker_checks_still_authorize_exact_plan(fresh)
    validate_snapshot(fresh.inventory_fingerprint)
    # All acknowledgments and the final recency check must succeed.
    execute_deletions(plan)
```

Batch transactions do not roll back prior acknowledged batches if a later batch
fails. Reclaim still deletes nothing. This preserves the required barrier without
inventing a distributed transaction or a giant unbounded request. Record field merge
semantics are retained, but conditional pre-sample bases replace unconditional
last-arrival overwrite. This is a domain contract change and R-FRESH must prove it.
The final snapshot comparison catches drift during paging/planning; after its lock
is released another Docker/registry actor can still race deletion. No claim of
cross-system atomicity or permanent deletion authorization is made.

## Recursive review

| Counterexample | Required result |
| --- | --- |
| Inventory exceeds 1 MiB but individual records fit. | Several bounded pages, one consistent full inventory |
| Concurrent writer changes the file between page reads. | Current read remains its snapshot; next polling iteration observes the commit |
| Third page fails or caller is interrupted. | No partial authoritative inventory; explicit/finally/scope cleanup releases retained data |
| Final response is lost after release. | No retry guarantee; close is idempotent and no snapshot leak |
| One record exceeds the negotiated limit. | Declared error, no truncation, reclaim deletes nothing |
| Second commit batch fails after first persisted. | Earlier batch may remain; zero Docker deletion |
| A client opens snapshots without finishing. | Per-caller/count/byte admission refuses additional allocation; scope finalizer clears leftovers |
| A stale cursor is reused in the next invocation or by another caller. | Rejected before reading retained data |
| First-page work allocates a snapshot but times out before its ID is received. | Fixed expiry reclaims the slot on the next entry; no permanent polling failure or retry of the lost request |
| Each page/batch asks for a fresh default duration. | Facade shares one deadline; primitive requests and provider snapshot expiration cannot extend it |
| Deploy commits NEW after consumption sampled OLD. | Consumption's old base conflicts; NEW remains persisted; a later poll samples again |
| Another lab begins sharing an image during reclaim's pages/planning. | Fresh eligibility or final snapshot validation rejects the stale plan; zero deletion |

The added abstraction is justified only by complete inventory and frame-equivalent
limits. Defer generic streaming, arbitrary snapshot sharing, filesystem cursors,
and cross-process long-lived snapshot leases.
