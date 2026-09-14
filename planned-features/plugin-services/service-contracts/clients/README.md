# API-only local clients

Back to [service contracts](../README.md).

`services(api)` obtains the callback-bound `api.operations` client. The facade knows
the stable service operation ID and immutable request/reply envelopes; it imports
no router, live provider class or application runtime. Typed capability clients
wrap it with the domain's encode/decode and method signatures.

## Resolution and calls

```text
facade.providers(capability):
    request filtered compatible descriptors through the service operation
    return immutable provider handles ordered by plugin ID

facade.require(capability, provider_id=None):
    if explicit ID: resolve that authorized compatible provider
    else if configured authorized default exists: use it
    else if exactly one authorized compatible provider: use it
    else: raise typed missing/ambiguous request rejection

handle.call(method, value, budget=None):
    validate handle's callback client generation/current owner
    encode value with accepted capability codec
    send LocalCall(provider_id, capability, method, payload, requested_budget)
    decode explicit success/domain reply
```

Handles contain immutable identifiers/descriptors and their callback-bound operation
client, never an implementation. Do not reuse a handle across callbacks or pass it
to workers. Long polling within a single `before_goal` callback can reuse it while
that callback remains current. Nested calls create a facade from the provider's own
fresh API. Scope and access are derived again by the router on every call.

Enumeration and lookup return only providers visible under the caller's policy.
They do not activate plugins or allocate provider resource scope entries. A lookup
may succeed before business readiness; calling still performs readiness checks.
No generic priority resolves ambiguity. Image callers deliberately enumerate all
eligible providers and then apply image-specific ordering.

Composite capability methods such as paged `records()` and batched
`commit_observations()` create one absolute deadline for the entire facade call.
Pass its remaining duration to every primitive request. Sequential page/batch calls
are not nested core requests, so core cannot infer that shared budget automatically.
Explicit release in `finally` can use a separate finite cleanup budget; it does not
extend the business deadline or justify retrying uncertain work.

## Errors and catch boundaries

Expose typed request and declared-domain errors with stable codes. Preserve actual
`OperationFailure` for local managed defects rather than relabeling it as an ordinary
RPC rejection; catching it does not clear core's failure latch. Python child clients
also expose client-only endpoint-absent, channel-closed and uncertain-outcome errors.
Those are not invented server error replies.

Consumption may catch expected registry errors, log a warning and report unknown
measurements. Sleep may catch them and return failure with zero deletion. Neither
consumer should catch every `RuntimeError` and continue as though inventory were
empty. There is no legacy context fallback when services are missing.

## Review

Check stale callback handles, same-thread borrowing of an active ancestor handle,
missing operations on A runtimes, ambiguous providers, filtered defaults, unsupported
optional methods, and fresh detached responses on repeated calls. Prove the import
closure of a provider/consumer excludes `engulf-services` runtime, and that of a
Python child excludes concrete Engulf/wrapper runtimes.
