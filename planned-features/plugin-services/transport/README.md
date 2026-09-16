# Child transport and later proxies

The transport uses a strategy interface for all OS-specific behavior. The first
working strategy uses a private Unix stream socketpair; the Windows strategy is
explicitly unavailable. Framing, protocol state and deadlines use the same portable
channel contract. Host I/O runs in bounded steps on the invocation thread; decoded
business calls enter the service handler through the goal's managed operation client.
There is no listener discovery, raw provider access, reconnect or automatic retry.

| Subcomponent | Details |
| --- | --- |
| [Platform strategies](strategies/README.md) | Portable channel boundary, lazy selection, Unix implementation and Windows stub |
| [Wire protocol](wire/README.md) | Frames, envelopes, negotiation and errors |
| [Endpoints and child client](endpoints/README.md) | Strategy-tagged bootstrap, connection ownership and uncertainty |
| [Bounded pump](pump/README.md) | Budgets, queues, timers, parsing and cooperative execution |
| [Explicit proxies](proxies/README.md) | Separately gated descendant forwarding |

Protocol definitions, vectors and a small independent Go reference client precede
transport implementation. Python and Go must also implement accepted capability
payload codecs. The reference Go client is interoperability evidence, not a new
published SDK commitment. Local calls pass codec gates before child access ships.

## Interaction

```text
helper.open:
    if no broker, no executable opt-in, or empty effective grants: return None
    strategy = select_transport_strategy()     # fixed local selection, lazy imports
    require strategy.support.implemented      # Windows fails before allocation
    require compatible wrapper execution strategy
    create child scope through goal-only OpenChild after policy validation
    create endpoint pair through strategy and bind opaque launch/wait resources
    return session; exhaust acquired resources on any open failure

wrapper strategy spawns child -> helper.spawned(pid) releases child-side host copy
child strategy validates/claims endpoint -> HELLO -> host grants-filtered READY
child CALL -> bounded parser -> host ExecuteChild(token, validated_call)
    -> service handler -> core owner dispatch -> canonical reply
host polls child -> writes reply only while peer/scope still valid
child exit / peer closure -> stop ingress -> child-scope cleanup
```

The [Windows stub](strategies/windows/README.md) is selected before importing any
Unix implementation. It raises `UnsupportedTransportError` when IPC is requested;
local clients and service setup do not select or open a transport strategy.

No child services are granted for the initial registry/image migrations. Those are
local plugin use cases and create no child scope or endpoint, even with a broker
selected. The broker is a transport-configuration plugin, not a privilege-separation
broker. It cannot expand application grants or opt an executable into IPC.

Before B6, record an application-owned child consumer and its minimum grants at
T-CONSUMER. Until one exists, local B delivery may complete while child transport
remains a separately gated milestone. Keep the agreed strategy/Windows-stub design;
do not claim that implementing a no-service handshake benefits the local consumers.

## Review boundary

The protocol supplies bounded admission and cooperative deadlines, not execution
isolation or a hard wall-clock guarantee. Access filtering constrains cooperating
protocol use; the direct child and normal plugins retain their actual OS authority.
Do not describe a socket token, plugin state directory or catalog filter as a sandbox.
