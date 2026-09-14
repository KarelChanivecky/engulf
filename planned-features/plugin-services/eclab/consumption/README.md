# Consumption consumer

Back to [eclab adoption](../README.md).

Consumption stays in `before_goal`, where it already owns its command and preempts
normal Containerlab execution. The new client replaces the operational context
object; it does not move the command into the wrapper's preparation phase.

```text
before_goal(invocation, api):
    if command != consumption: return
    registry = typed registry client built from services(api)
    repeat while polling:
        try:
            inventory = registry.records()           # new persisted snapshot each time
            inventory_complete = true
        except expected registry availability/size errors:
            inventory = unavailable
            inventory_complete = false
            warn using own callback logger
        sample Docker/workspace observations using explicit completeness flag
        render measurement; unknown ownership-dependent quantities are N/A
        if sample contains complete observations:
            try: registry.commit_observations(sample.observations)
            except expected commit error: warn
        wait existing two-second reporting interval or finish
    return existing command result
```

Preserve read-only measurement, lab selection, canonical paths, image deduplication,
running/stopped/sleeping classification, output formatting and N/A behavior. A
failed registry read must not be represented internally as a trustworthy empty
tuple: pass explicit completeness into ownership/shared-image calculations. Keep
other independently measurable quantities when the command already supports them.

Only complete Docker observations may replace recorded image IDs. Partial Docker
failure does not turn unknown ownership into an empty image set. Commit expected
failures warn; unexpected managed provider defects retain framework failure rather
than being swallowed as a transient polling warning.

The local client can be reused during this one long-lived callback; every provider
request gets a fresh owner API. Release each bounded registry snapshot before the
two-second wait, including interruption/error paths. Do not retain a registry state
handle or in-memory session across polling iterations.

## Review and tests

Use deterministic coordination for a second process/client committing inventory
between two samples. The second report must observe it. Test corrupt storage, a
later page failing, missing optional measurements, complete vs partial Docker
observations, failed commit warnings, interruption cleanup, and repeated invocation.
Assert that consumption still preempts before `goal.achieve` and that provider calls
are attributed to `engulf_clab.lab_registry`, not consumption.
