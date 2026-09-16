# Endpoint identity and child client

Back to [transport](../README.md).

## Bootstrap and endpoint ownership

The host sets one bounded versioned `ENGULF_SERVICES_ENDPOINT` value in the intended
child's environment. The proposed outer record contains `v`, a fixed `transport`
identifier, and a backend-owned `endpoint` payload. Cap the whole value at 4 KiB
before bounded parsing, reject unknown fields, and use only the locally selected
[strategy](../strategies/README.md). The identifier selects no import or fallback.
The [Unix payload](../strategies/posix/README.md) contains descriptor identity;
the Windows stub emits no bootstrap at all. This is launch metadata, not a portable
service value or secret-based authorization scheme.

```text
connect_from_environment:
    parse exact small versioned endpoint record
    strategy = select local transport strategy
    require strategy support and matching bootstrap transport identifier
    channel = strategy.connect(record.endpoint)
        # Native identity, exclusive claim and inheritance belong to the strategy.
    send bounded HELLO; accept validated READY
    on handshake failure: close the owned channel
```

The package must have one owner per endpoint so two client instances cannot race
reads or handshakes on the same stream. A native identity failure must not close
unrelated OS resources named by stale metadata. The concrete strategy owns the
claim lock and idempotent release record; generic client code never closes a raw
fd/handle or inspects its identity fields.

The strategy releases the redundant child-side host copy after spawn notification,
and every owned endpoint on failure paths. Once a cooperating client claims the
endpoint it marks its descriptors non-inheritable, preventing accidental inheritance
through ordinary exec-based subprocess creation. This is client cooperation.
Explicit proxies are required for supported descendant access.

## Connection authority

Grants attach to whoever possesses the inherited connection. The host does not
authenticate the writer's PID with socketpair peer credentials. An uncooperative
child may retain inheritance, fork, or transfer the descriptor to another process;
that process obtains the same connection grants. Client non-inheritance flags do
not prevent deliberate delegation or fork-only sharing.

Require application opt-in for the resolved executable/launch contract before
OpenChild. Shells and shell shims are not implicitly opted in by their eventual
command. With no opt-in or no grants, pass no endpoint and create no child scope.
If an application explicitly opts in a delegating launcher, it accepts that its
descendants may hold the connection; v1 cannot promise host-enforced containment.
T-AUTH includes an unopted `sh -c` launcher with no endpoint and a cooperating-client
inheritance check. A future stronger peer/descendant boundary needs a different
transport/security contract, not a claim added to the socketpair strategy.

## Synchronous client and queue

One connection has one reader/writer owner and one in-flight request. A Python client
may serialize concurrent caller threads through a bounded owner loop/lock with at
most 16 waiting callers; it never uses an Engulf callback API on those threads.
Local plugin facades remain restricted to the invoking thread and do not use this
child-client queue.

Each queued request records a local absolute monotonic deadline when admitted.
Check expiry before encoding/transmitting and send only the remaining duration.
Queue saturation or queued-unsent expiry is a typed known-not-started client error.
After any bytes are sent, absence of a valid correlated reply is outcome-unknown;
close the connection and never retry implicitly. A write that only sent the header
still counts as transmission for this conservative rule.

```text
call(request):
    admit bounded waiter with absolute deadline
    wait for sole connection ownership while enforcing own deadline
    if expired before send: fail known-not-started
    send remaining budget and monotonic next request ID
    wait for bounded correlated reply
    if expiry/loss after send: close connection; raise OutcomeUnknown
    return decoded typed result or declared error
```

Do not hold the queue admission mutex during channel waiting, or blocked callers
cannot expire independently. A child client background I/O owner is allowed; a host
background thread dispatching providers is not. Distinguish these roles in tests.

## Review

Exercise inherited stale metadata, wrong backend/version, unavailable Windows
strategy, duplicate client claims, unintended descendant inheritance, concurrent callers, queue
expiry while another request waits, partial-send failure, reply decode failure and
parent loss. Provider side effects may already be committed after a lost reply;
only domain-specific idempotency/reconciliation can resolve that uncertainty.
Native fd reuse and socket family/type checks belong to the Unix strategy suite.
