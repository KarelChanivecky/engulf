# Sleep consumer and deletion barrier

Back to [eclab adoption](../README.md).

Sleep stays in `before_goal` and keeps its `eclab-sleep:docker` external-resource
lease across complete inventory read, Docker planning, observation commits and
deletion. Use a finite acquisition budget for the migrated path; do not change
unrelated callers' existing lease defaults.

```text
with api.leases(("eclab-sleep:docker",), timeout=finite_command_budget):
    try:
        records = registry.records()                # complete, persisted snapshot
        sleep_plan = existing_plan(records, Docker_observation, options)
        registry.commit_observations(sleep_plan.complete_observations)
        # All batches acknowledged; provider transaction has finished.
    except expected inventory/commit/Docker/planning errors:
        log; return command failure                 # no deletion happened

    independently preserve existing pre-delete storage measurement checks
    remove selected containers and exact eligible image IDs
    report independent partial Docker failures and measured saved storage
```

The registry is reactivated under its own ID while sleep remains active and keeps
its lease. The registry may use its state transaction, but may not acquire a new
external lease. No state transaction is held by sleep across this call. This is a
direct acceptance case for the generic cross-stack lock rules.

## Domain safety preserved

Keep existing `--all`/`--stopped` eligibility, stopped/running checks, complete image
ownership filters, shared-image preservation, exact image ID deletion, no force or
broad prune, workspace preservation and independent error reporting. A failed
commit, unknown inventory or incomplete page sequence cannot open the deletion
barrier. No fallback invokes `SessionLabRegistry.upsert` or delays writing until
`after_goal`.

The acknowledgment proves completed registry persistence before deletion begins;
it does not lock every concurrent Docker actor or make Docker and the filesystem
atomic. `eclab-sleep:docker` coordinates cooperating sleep operations, not every
deploy/build command. Preserve Docker's non-force checks and existing ownership
rules; do not claim the service architecture eliminates concurrent external mutation.
Any broader cross-command lease protocol needs its own domain design and migration.

## Acceptance test that proves persistence

```text
real managed invocation with temporary real Engulf user state:
    selected registry + sleep adapters, fake Docker client
    on first fake remove_container/remove_image:
        read registry through an independent fresh state reader
        assert every planned complete observation is already persisted
        assert sleep's external lease is still held
        assert provider's transaction is no longer held
```

The independent reader is test instrumentation, not permission for production
consumers to inspect registry storage. Use separate process/barrier coordination
where needed to prove lock state. Also inject failed writes, lock contention, a
second batch failure, corruption, interrupted calls, concurrent merges and partial
Docker deletion failures. Every pre-barrier failure must show **zero** deletion
calls; a mock `commit` event preceding a mock `remove` event is insufficient.
