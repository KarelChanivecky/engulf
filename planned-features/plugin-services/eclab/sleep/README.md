# Reclaim consumer and deletion barrier

Back to [eclab adoption](../README.md).

The former sleep command is now `eclab reclaim`, implemented by
`engulf_clab.reclaim` at sibling HEAD `f8c9063` (rename `e543a30`). This page and
R-SLEEP retain their historical path/label; R-SOURCE refreshes the current source
before implementation. The service migration described below remains proposed.

Reclaim stays in `before_goal` and keeps its `eclab-reclaim:docker` external-resource
lease across complete inventory read, Docker planning, observation commits and
deletion. Use a finite acquisition budget for the migrated path; do not change
unrelated callers' existing lease defaults.

```text
with api.leases(("eclab-reclaim:docker",), timeout=finite_command_budget):
    try:
        baseline = registry.snapshot()              # complete pre-sample baseline
        records = baseline.records
        reclaim_plan = existing_plan(records, Docker_observation, options)
        registry.commit_observations(reclaim_plan.observations_with_bases(baseline))
        # All batches acknowledged; provider transaction has finished.
        fresh = registry.snapshot()                 # includes our own commits
        require exact planned deletions remain eligible using fresh + current Docker checks
        perform existing pre-delete storage measurement checks
        registry.validate_snapshot(fresh.inventory_fingerprint)
    except expected inventory/commit/Docker/planning errors:
        log; return command failure                 # no deletion happened

    remove selected containers and exact eligible image IDs
    report independent partial Docker failures and measured saved storage
```

The registry is reactivated under its own ID while reclaim remains active and keeps
its lease. The registry may use its state transaction, but may not acquire a new
external lease. No state transaction is held by reclaim across this call. This is a
direct acceptance case for the generic cross-stack lock rules.

## Domain safety preserved

Keep existing `--all`/`--stopped` eligibility, stopped/running checks, complete image
ownership filters, shared-image preservation, exact image ID deletion without force
or broad prune, workspace preservation and independent error reporting. The existing
container removal uses `container rm --force --volumes` on exact selected IDs; the
no-force rule applies to images, not all Docker removal. A failed
commit, observation conflict, unknown inventory, incomplete page sequence or changed
inventory at the final recency check cannot open the deletion
barrier. No fallback invokes `SessionLabRegistry.upsert` or delays writing until
`after_goal`.

The acknowledgment proves completed registry persistence before deletion begins;
it does not lock every concurrent Docker actor or make Docker and the filesystem
atomic. `eclab-reclaim:docker` coordinates cooperating reclaim operations, not every
deploy/build command. Preserve Docker's non-force checks and existing ownership
rules; do not claim the service architecture eliminates concurrent external mutation.
Any broader cross-command lease protocol needs its own domain design and migration.
Even a complete immutable snapshot may be stale. R-FRESH checks for a newly shared
image between initial paging, commit, revalidation and the final registry comparison.
On detected drift abort with zero deletion; do not silently expand/replan the resource
set. A change after the final comparison releases its transaction is still possible.
Non-force Docker checks remain required, and the plan does not claim they protect
every stopped lab's future image needs or close the cross-system race.

## Acceptance test that proves persistence

```text
real managed invocation with temporary real Engulf user state:
    selected registry + reclaim adapters, fake Docker client
    on first fake remove_container/remove_image:
        read registry through an independent fresh state reader
        assert every planned complete observation is already persisted
        assert reclaim's external lease is still held
        assert provider's transaction is no longer held
```

The independent reader is test instrumentation, not permission for production
consumers to inspect registry storage. Use separate process/barrier coordination
where needed to prove lock state. Also inject failed writes, lock contention, a
second batch failure, corruption, interrupted calls, concurrent merges and partial
Docker deletion failures. Every pre-barrier failure must show **zero** deletion
calls; a mock `commit` event preceding a mock `remove` event is insufficient.
