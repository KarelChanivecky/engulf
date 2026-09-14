# Generic executable support

The wrapper owns process creation, readiness waiting, signal forwarding and reaping
through its platform strategy. Generic lifecycle code handles opaque resources;
the Linux strategy owns native mechanisms and the Windows strategy is a stub.
An optional helper contributes launch data and bounded work. The helper does not
own `Popen`, call plugins directly, or replace preparation/postprocessing.

| Subcomponent | Details |
| --- | --- |
| [Contracts](contracts.md) | Portable definitions reserved in A |
| [Execution strategies](strategies/README.md) | OS boundary, opaque resource binding, Linux implementation and Windows stub |
| [Process lifecycle](process/README.md) | Open/prepare/spawn/pump/stop/close and failure paths |
| [Environment and completion](environment/README.md) | Fresh child environment, endpoint inheritance and completion metadata |

Implement this generic seam using a fake helper before installing services in eclab.
The local services helper registers its operation during setup even without a child
broker, so installing it into A's deliberately rejecting wrapper cannot work.

## Integration sketch

```text
setup:
    existing argument/completion/help registration
    if support: support.setup(goal_setup_api)
    close setup window

achieve:
    existing analyzers and merge/veto resolution
    if normal executable call survives:
        session = support.open(prepared_event, goal_api, strategy.support) if support else None
        snapshot launch data and retain opaque attachments for cleanup
        preserve existing per-plugin preparation and unwind
        prepare launch and spawn through strategy with validated additions
        if session: run generic readiness pump
        else: use existing blocking wait
    close child session/resources before after_call
    dispatch after_call with real outcome whenever there was a call
    return outcome, retaining any managed execution failure for core finalization
```

Help, completion and preemption must not allocate a child service endpoint. Helper
setup may still install local operation definitions. Environment removal metadata
applies to every child path where the helper is installed, including when `open`
returns `None`.

## Review findings

An exception after spawn must not be translated into exit 126/127. A helper error
must not cause two owners to wait on the process. A pending response must not incur
an extra 100 ms just because work was generated during `step`. A provider's
termination must not be swallowed by the special wait-only Ctrl-C behavior.
The process design gives each of those cases an explicit branch. A fake strategy
with no fd/handle fields must exercise the generic path; Linux resource tests and
Windows unavailable-strategy tests validate their own platform boundaries.
