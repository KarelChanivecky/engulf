# Explicit proxies — follow-on milestone

Back to [transport](../README.md). This is retained scope after direct-child
acceptance, not a requirement for local migrations or A's foundation release.

A child that deliberately supports descendants creates a proxy with fresh downstream
endpoints through its selected transport strategy. The initial Unix strategy uses
socketpairs; the Windows stub rejects opening proxy transport before allocating
anything. The proxy grants only a subset of its own upstream visible triples.
It never shares the upstream channel, merges independently hosted Engulf directories,
or discovers an upstream endpoint automatically.

## Routing and queues

```text
downstream peer -> validate own ID/grants/deadline -> bounded per-peer waiting slot
round-robin ready peers -> choose one request while upstream idle
    recheck deadline; allocate new monotonically increasing upstream ID
    forward with reduced remaining duration
upstream reply -> map to original downstream ID -> bounded downstream output
```

There is one upstream outstanding request, at most 16 downstream connections, and
bounded admitted work. Keep only the in-flight ID mapping and bounded queue state.
Use deterministic fair scheduling among ready peers; never let a nonreading peer
hold all output capacity. An excessive grant is rejected at proxy configuration,
not silently upgraded.

At admission capacity, return correlated `request/resource_exhausted` when the peer
frame is valid and error capacity exists. A queued-unsent request that expires gets
correlated `request/deadline_exceeded` without upstream dispatch, while healthy peers
stay connected. Queue timers run while upstream is busy; a synchronous implementation
that blocks on upstream response and stops processing downstream timers is invalid.

If upstream disappears after forwarding, fail outstanding work as uncertain and
close descendants. Do not retry or predict whether an arbitrary provider completed.
An expired unsent queue entry is known not started. Recheck/decrement budgets at
every forwarding hop; downstreams cannot extend parent policy.

## Scope ownership

Initial proxy requests remain inside the host's direct-child resource scope unless
a later explicitly designed protocol creates finer host scopes. Do not imply that
closing one downstream socket automatically releases a distinct host scope that
the protocol never created. The proxy owns its downstream connection cleanup;
the host closes all associated provider resources when its direct child scope ends.

This keeps v1's private host control variants off the wire. Per-descendant host
resource isolation is a separately versioned extension if a concrete capability
requires earlier release. It must not be smuggled in through caller-supplied scope
IDs. Provider resources explicitly releasable by domain methods can still be released
by those methods while the direct-child scope is open.

## Recursive review

Test two peers where one request is blocked upstream and another expires unsent,
fair admission after saturation, ID remapping, bounded output for a nonreader,
denied expanded grants, parent/proxy death, uncertain upstream completion, and a
nested Engulf application with its own independent directory. Document the shared
host-scope limitation before exposing proxy support to resource-owning capabilities.
