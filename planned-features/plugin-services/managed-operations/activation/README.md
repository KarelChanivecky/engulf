# Activation, current frames, and locks

Back to [managed operations](../README.md). Source:
[activation and lock coordinators](../../evidence.md#core-contracts-and-dispatch).

## State and ownership

Keep one execution stack per invocation on its invoking thread. Entries are internal
tagged participant frames or handler windows; public `OperationCallFrame` values are
immutable projections, not the stack itself. Participant frames reference the
existing activation generation and owner lock coordinator. Handler windows have a
fresh token and the operation they belong to. No process-global current-service
variable or thread-local state shared across Applications is needed.

The shared callback boundary in `engulf._dispatch` is the sole owner of participant
activation, frame push, deactivation and frame pop. `_HookRunner` uses it for both
outer hooks; `_PhaseDispatcher` uses it for every invocation phase, including
managed targets. `Application` uses the same boundary around `goal.achieve`.
The hook runner is a separate traversal, not a call through `_PhaseDispatcher`.
Setup callbacks have no invocation stack. Handler windows are pushed/popped only
by the operation coordinator.

An ordinary root participant frame needs no operation ID before its first request.
When projecting `OperationCallFrame` for a request, core supplies the requested
operation's registered ID along with that participant's current owner/phase facts.
Do not invent an empty or requestable root-operation identifier to seed the stack.

Ordinary invocation callbacks receive frames even before the first managed request.
The stack starts empty, the first callback pushes its root participant, and return
restores the prior top (or empty stack). Clients bind to that actual frame after
activation. Managed dispatch never pre-activates or pre-pushes a target before
calling `_PhaseDispatcher`. The detailed cleanup algorithm in the lifecycle page
is this same boundary, not another wrapper around it.

```text
request(client, request):
    require invoking thread == client.owner_thread
    require client.activation.current_generation == client.generation
    require client.activation is active
    require stack.top is the participant frame bound to client
    reject if an ancestor participant holds a state transaction
    invoke handler in a fresh window using runtime caller facts

operation_dispatch_preconditions(operation_api, target):
    require stack.top is operation_api.window
    require operation_api.window is open on the invoking thread
    require target is not an active participant ancestor
    require next managed provider depth <= 32
    delegate to canonical phase dispatcher
        # Its shared callback boundary activates/pushes exactly once.
```

The 32 limit counts nested managed provider activations, not private handler-window
entries. Generic recursion between handlers without a provider must also have a
bounded operation depth; use the same 32 ceiling, counted separately, to prevent
an operation recursively calling itself through a faulty local adapter. No public
API for direct handler-to-handler calls is introduced.

### Counterexample: active ancestor impersonation

```text
A enters; client_A captures generation 7 and thread T
A calls B; A stays active, B is now current on thread T
B obtains client_A and tries client_A.request(...)
generation == 7 and thread == T and A.active == True    # all insufficient
stack.top.participant == B                           # reject borrowed A client
B returns; A becomes current again                    # A client usable again
```

This protects attribution and lifetime correctness for cooperative code. It does
not isolate hostile in-process Python. Do not retrofit an OS-security claim or a
blanket behavior change onto every old context/state API in the foundation release.

## Lock rules across the stack

| Ancestor state | Nested operation/provider behavior |
| --- | --- |
| No transaction or external lease | Provider may acquire its own leases before its own state transaction |
| Any state transaction active | Reject the cross-owner request before dispatch, even for a nominally read-only method |
| Any external lease active, no transaction | Provider may use its own state store/short transaction; reject any additional external lease or reacquisition |
| Descendant returns or fails | Release descendant leaks only; ancestor locks remain owned and held until their own exit |

Integrate the cross-stack lease check into the existing lock coordinator's claim
path. Checking only at service entry is insufficient: a provider may try to acquire
a lease later in its callback. Rejection must happen before the new lock context
claims or acquires anything. The rule applies while inside managed nesting; existing
unrelated lock semantics and `timeout=None` defaults remain intact.

The registry's user-store read/merge/write occurs under its own explicit finite
transaction. Reclaim's ancestor `eclab-reclaim:docker` lease is legal around that call.
The registry cannot acquire another external lease inside it. Holding an outer
transaction while asking any provider is rejected without waiting.

## Recursive review

| Failure path | Resolution and proof obligation |
| --- | --- |
| The first before-goal or goal-originated request finds an empty stack. | Both ordinary entry paths push a frame before exposing the client; C-FRAME tests successful first hops and final empty-stack restoration. |
| Managed dispatch activates a target twice. | Dispatcher calls the shared boundary once; count generations and endpoint entries in C-FRAME. |
| Provider callback uses a retained outer `OperationAPI` to dispatch as the handler. | Top handler-window check rejects it; test both local nested calls and close callbacks. |
| A provider starts a worker with its own client. | Thread check rejects before dispatch. Build workers receive resolved data only. |
| Lock acquisition fails halfway through descendant activation. | Release only acquired descendant contexts; retain A's leases and preserve the first exception. |
| Provider's method advertises a finite deadline but calls `read_text` directly. | No false bound: service storage adapters use explicit finite transactions; audit other implicit lock/catalog/filesystem waits separately. |
| A long provider blocks child polling past its budget. | Cooperative deadline, not forced cancellation; observe expiry/exit on return. Transport tests demonstrate this limitation. |
| Repeated invocations reuse a provider singleton or a cached facade. | New invocation identity, handler instance and activation generation; stale clients fail, provider invocation data must reset explicitly. |

Do not add lock transfer, automatic lease union, worker dispatch, async callbacks,
or a general scheduler to solve these cases. Those abstractions change ownership
and would need separate contracts and consumers.
