# Lab registry provider

Back to [eclab adoption](../README.md). Evidence:
[registry source and storage](../../evidence.md#registry-and-consumers).

The registry fits services because consumers need owner-executed reads and writes
at the time they ask. Today's capability-free `SessionLabRegistry` avoids sharing
dead state handles, but it serves an invocation-old snapshot and queues writes until
`after_goal`. It does not supply fresh polling or a persistence barrier for sleep.

## Domain contract

Keep `engulf_clab.lab_registry`, user-state ownership, `labs.json` version 1,
`(name, canonical directory)` record keys, stable sorting, topology retention,
`ever_deployed` retention, and replacement of image IDs only by complete observation.
Destroy keeps inventory records. Consumers still never read registry files directly.

The typed API exposes `records() -> tuple[LabRecord, ...]` and
`commit_observations(records) -> CommitAcknowledgment`. Their bounded primitive
methods and consistency are defined in [snapshots and batches](snapshots/README.md).
The convenience methods may make multiple calls; they never return a partial
inventory or acknowledge uncommitted observations.

| Storage condition | New service meaning |
| --- | --- |
| Missing file | Complete empty inventory |
| Valid existing file | Complete persisted snapshot |
| Corrupt/unreadable file | Declared `inventory_unavailable`; leave file intact |
| Expected failed lock/write | Declared `commit_failed` or inventory unavailable; no successful acknowledgment |
| Exceeded domain snapshot/record limit | Explicit size/resource domain error; never truncate ownership information |
| Unexpected implementation/codec defect | Managed provider failure, not a swallowed tracking warning |

## Storage interaction

```text
provider.begin_snapshot(request, context, api):
    with api.state(USER).transaction(timeout=remaining_finite_budget(context)) as store:
        records = read_and_validate_existing_format(store)
    # No state capability or lock is retained across service callbacks.
    return create_bounded_immutable_snapshot_and_first_page(records, context)

provider.commit_batch(request, context, api):
    validate complete observations and bounded request before mutation
    with api.state(USER).transaction(timeout=remaining_finite_budget(context)) as store:
        current = read_and_validate_existing_format(store)
        merged = preserve_current_merge_semantics(current, request.records)
        write_existing_format_atomically_if_changed(store, merged)
    return explicit CommitAcknowledgment(committed_count=...)
```

Refactor the private storage helper to accept a finite transaction budget or operate
on the already-locked store; do not nest its current unbounded `upsert` transaction
inside another transaction. User-store access inside that transaction skips the
implicit store lock reacquisition. Read and parse as one snapshot, then release the
transaction before paging, logging or calling any other service. Filesystem latency
is still cooperative; this is not a hard time bound on arbitrary storage devices.

Automatic successful-deploy/redeploy observation remains in the registry's own
`after_goal`, using its private storage helper directly. Expected observation and
persistence failures warn without changing a successful deployment result. Preserve
the distinction between those declared/known failures and implementation defects.

## Migration and review

Remove `SessionLabRegistry` publication and the operational context reads/writes
after API, provider and consumers migrate together. Remove deferred consumer
pending writes. Update usage/contribution instructions that currently promise an
empty snapshot on corruption or persistence after the invocation.

Test missing/corrupt storage, complete-observation merging, no-op acknowledgment,
finite lock contention, concurrent transaction merge, no retained state API,
repeated invocation, interrupted pagination/commit, and direct post-deploy tracking.
Services does not create a transaction spanning registry state and Docker.
