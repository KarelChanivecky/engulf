# Bounded host pump and deadlines

Back to [transport](../README.md).

The pump is portable policy over a [strategy-owned channel](../strategies/README.md).
It sees bounded read/write results and normalized readiness, never socket families,
fd/handle layouts or OS branches. Native waiting belongs to the wrapper execution
strategy on the host; unsupported Windows IPC never constructs this pump.

## State and limits

```text
AWAIT_HELLO -> READY -> READING_CALL -> DISPATCHING -> WRITING_REPLY -> READY
      any peer/protocol/transport close -> REVOKED -> CLOSED
```

| Resource | Initial bound |
| --- | --- |
| Input/output | At most one bounded frame of each per connection; no decoded request backlog |
| Aggregate charged transport/parser storage | 32 MiB across connections; reserve bounded error output before admitting work |
| One `step` I/O | At most 64 KiB read and 64 KiB write |
| One `step` business work | At most one top-level provider call; synchronous dependencies stay inside it |
| Handshake deadline | 5 seconds from connection start |
| Incomplete frame deadline | 30 seconds from first byte of that frame |
| Blocked reply deadline | 30 seconds from output becoming pending |
| Child client waiters / later proxy connections | 16 each |
| Business budget | Application initial ceiling 30 seconds; inherited deadline cannot extend |

Tiny progress does not restart handshake/partial-frame/blocked-output deadlines.
`step(())` checks timers. Pending buffered work or newly generated response bytes
returns `immediate=True`, causing a nonblocking turn after the wrapper polls the
child. An immediate hint with no progress or pending work is a helper defect; avoid
an idle busy loop. Peer closure revokes ingress without closing unrelated invocation
services.

## Memory accounting

The 32 MiB limit is **charged managed storage**, not a claim about Python process RSS.
Count frame buffers, parser containers/string/key tables, queued encoded output,
decoded transport values and retained proxy work. General plugin allocations and
interpreter overhead are outside this bound and must not be described as sandboxed.

Do not call unbounded `json.loads` and then check node limits after allocating the
whole object graph. Use bounded tokenization/construction that reserves cost before
allocating each container/string/value, enforces depth/nodes, and rejects duplicate
keys. An implementation may use a preflight tokenizer plus a proven conservative
allocation reservation before standard decoding, but must demonstrate that bound
with worst-case fixtures. Select the parser implementation at the B conformance
gate; no new dependency is assumed by this design.

Serialize replies incrementally into charged output capacity. Do not first build
an arbitrarily large JSON string and then check its length. Preserve an error budget
even if normal reply encoding exceeds its permitted output. Decoded provider domain
objects remain trusted application allocations; domain snapshot limits additionally
bound registry-owned retained data.

## Pseudocode

```text
step(ready):
    expire handshake/frame/output timers using current monotonic time
    read bounded available bytes through channel.read_some
    parse at most one complete request
    if request ready and scope open and child still alive:
        check absolute request deadline and reserve response capacity
        reply = goal_client.request(ExecuteChild(scope_token, validated_call))
        # All provider work above occurs synchronously on the invocation thread.
        if child exited or deadline expired: revoke/discard as appropriate
        else: start bounded incremental reply encoding
    channel.write_some(bounded_ready_output) only after checking child/scope validity
    return ExecutionProgress(immediate=buffered_work_can_advance_without_wait)
```

Poll the child before/after each step and again before reply writes after provider
work. If the child dies during a callback, the host only learns that when execution
returns. Discard unsent replies and queued work, then perform child-scope cleanup.
Do not attempt asynchronous provider cancellation or background owner dispatch.

## Deadline propagation

Convert the admitted remaining duration into a host-local absolute deadline. Every
nested call uses `min(parent_deadline, now + requested_duration, application_limit)`.
Validate before provider entry and after return. Providers calculate finite lock,
subprocess and network waits from the remaining budget. Local calls expiring before
dispatch are known not started; after provider entry they may have committed work
even when the router reports expiry. No retry follows either uncertainty or channel
loss.

Registry reads use finite user-state transactions to avoid the existing implicit
unbounded read lock. Filesystem operations and arbitrary callbacks still cooperate;
a timeout parameter is not a guarantee that every underlying operation returns on
time. Keep image building outside the offer RPC.

## Recursive review

Use fake clocks for queue/timer edges and deterministic barriers for a provider
blocked while the real child exits. Prove delayed observation is expected, then
correct revocation/reaping on return. Flood tiny frames, large strings, deeply nested
objects and nonreading peers; assert charged accounting and per-turn I/O limits.
Measure prompt response scheduling after a callback without claiming a hard callback
latency bound.

Run the same protocol cases against a fake strategy whose resources have no native
descriptor fields. Check would-block separately from EOF, short reads/writes,
unrequested readiness, backend errors and idempotent close. These portable tests do
not replace real Unix transport or native Windows stub/import tests.
