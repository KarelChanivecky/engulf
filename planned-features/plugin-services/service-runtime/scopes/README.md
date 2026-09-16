# Resource scopes and dependency cleanup

Back to [service runtime](../README.md).

## Scope state

Each invocation scope or child scope owns an opaque identity, OPEN/CLOSING/CLOSED
state, touched-provider set, caller → dependency DAG, initiating grants, active
call context, and bounded diagnostic data. Provider instances may serve multiple
scopes, so service-owned resources are keyed by scope ID. Plugin singletons are not
invocation resource scopes. Child close never destroys invocation-local resources.

Edges include root consumers for cycle checking, but only providers actually entered
by service dispatch are members of the service-close set. A consumer's unrelated
outer-hook resources do not become service-owned merely because it called B.
Existing `prepare_failed`/self-unwind duties remain with that consumer.

Bound live child scopes per invocation (initial limit 16; the wrapper normally uses
one). Closed scopes drop their maps; reject stale tokens by invocation identity and
missing/open-state lookup without keeping an unbounded closed-token history. The
DAG has at most the selected directory's participants and O(V²) edges. Repeated
existing edges need no new reachability scan; retain core's active-stack checks.
These are managed bookkeeping bounds, separate from transport's charged buffers.

## Admission and closing algorithms

```text
admit(scope, caller, target):
    if scope == CLOSED: reject closed scope
    if scope == CLOSING:
        require target is an existing unclosed provider
        require edge(caller, target) already exists
    else:
        if caller == target or path_exists(target, caller): reject call_cycle
        insert edge(caller, target)
    touched.add(target)                 # before dispatch can allocate anything

close_scope(scope, op_api):
    if CLOSED: return
    if CLOSING: reject recursive root close
    scope.state = CLOSING
    freeze graph and touched set
    order = stable topological order(caller -> dependency), restricted to touched
    try:
        for provider in order:
            try:
                with closing_context(scope, current_provider=provider):
                    op_api.dispatch(CLOSE, close_event(scope), plugin_ids=(provider,))
            except OperationRequestError as rejection:
                if rejection.code == target_not_ready and rejection.target_id == provider:
                    pass  # conservative touched entry; owner never entered
                else: collect cleanup failure
            except BaseException as failure:
                collect failure; continue
            finally:
                mark provider closed; invalidate its scope handles
    finally:
        invalidate all remaining handles and tokens
        release scope bookkeeping; scope.state = CLOSED
    propagate first termination or recorded managed cleanup failure
```

The topological order is caller-before-dependency, **not its reverse**. If A used B
and B used C, close A, then B, then C; A may need B to release its resource. Break
ties by stable provider ID. Compute order on the full graph before restricting to
touched providers so transitive paths through roots are preserved.

During A's close, A can call B only over an already-established edge and only while
B remains open. B may then call C only over its own established edge. Core's current
frame, recursion, depth and lock checks still apply. Closing cannot discover new
dependencies, open a new scope, call an already closed provider or reopen A.

## Temporal cycle restriction

```text
A calls B; call returns successfully       # graph retains A -> B
later B calls A in the same scope          # rejected even though stack is empty
```

This is intentionally stricter than recursion prevention. Allowing the second call
would make cleanup order cyclic. The current plan retains this restriction. A new
scope is not a provider-controlled escape hatch; only the authorized goal can open
child scopes, and local business calls inherit their current scope.

## Cleanup budgets and ownership

Business deadlines do not erase cleanup obligations. Give each close attempt a
fresh finite application cleanup budget; dependencies inherit the remainder of that
close chain, capped by the single aggregate finalization deadline described in
[lifecycle](../../managed-operations/lifecycle/README.md#b-compatibility-and-interruption-policy).
An explicit child close starts that scope's aggregate budget; later finalization
cannot restart it. Bound provider count by the selected directory and nested depth by core.
Synchronous providers still cannot be forcibly timed out. Record exhausted budgets,
attempt every provider, and retain journals for external recovery.

When `close_scope` raises an ordinary managed cleanup failure to the wrapper helper,
the wrapper records it and still runs normal `after_call` with the saved child
outcome. See [child-close handling](../../executable-support/process/README.md#child-close-cannot-bypass-postprocessing).
Core-driven finalization records the same failure and continues other scopes.

Cleanup acquires fresh owner leases if needed after the original callback has ended.
If A calls B while A holds an external lease, B cannot acquire another external
lease. Design A's close to call dependencies before taking its own external cleanup
lease, or make the dependency's cleanup state-only. Do not transfer lease ownership
or silently bypass stack checks during finalization.

Registry snapshot handles are scope-owned data and are released on finalization.
Prepared image maps are invocation preparation data: they may be cleared by existing
wrapper unwind/after-call paths, after which the image method reports not ready.
They are not promised as permanent service resources merely because the provider
stays entered through `after_goal`. Durable images/build cache retain their existing
domain lifetime.

Core entered status is monotonic until finalization. Therefore a close admission
rejection of `target_not_ready` naming the exact closing owner proves it never had
a service callback in this invocation. A nested rejection naming a dependency does
not have that meaning and must not be ignored. This handles conservative touched
entries without adding a public readiness-inspection API to the foundation.

## Recursive review

Test independent root/child graphs, A→B→C order, later reverse-edge rejection,
partial provider allocation, cleanup calling existing dependencies, refusal of new
edges, two failing closers including termination, all token invalidation, repeated
close, and a root consumer that was never a touched service provider. Do not rely
solely on successful-path call ordering: assert resources are released and stale
handles fail after every exceptional path.
