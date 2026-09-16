# API-only local clients

Back to [service contracts](../README.md).

`services(api)` obtains the callback-bound `api.operations` client. The facade knows
the stable service operation ID and immutable request/reply envelopes; it imports
no router, live provider class or application runtime. Typed capability clients
wrap it with the domain's encode/decode and method signatures.

The public entry point is
`engulf_services_api.services(api: engulf_api.InvocationAPI) -> ServiceClient`.
`ServiceClient` is a nominal API-owned facade with
`providers(capability: CapabilityDescriptor) -> tuple[ProviderHandle, ...]` and
`require(capability: CapabilityDescriptor, provider_id: str | None = None) -> ProviderHandle`.
`ProviderHandle` exposes frozen `provider_id`, `capability` and `method_ids` fields;
its private callback client is installed only by the facade, not accepted as a
caller-supplied identity. `call(method: str, value: object, budget: float | None = None)
-> object` is the low-level escape hatch; typed domain clients own typed signatures.
Budgets must be positive finite seconds, excluding booleans, and are clamped by host
policy. Descriptor-selected codec bindings remain API-owned local code.

`services` checks `api.operations.support` immediately. A maps to
`ServiceUnavailableError(code="runtime_unavailable", message=...)`; a B runtime
without the service operation maps its `unknown_operation` response on first use to
`ServiceUnavailableError(code="operation_not_registered", message=...)`.
Both use actionable text naming the needed application integration. Other lifetime,
request and managed failures retain their categories. There is no silent fallback.
Define this error and the facade at the package top level; do not import the runtime
to probe availability. S-AUTHOR type-checks these definitions with a real A stub.

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

Managed diagnostics must render the runtime origin and ordered call chain, plus the
fact that catching the error did not clear the invocation failure. Emit this when
the failure is latched, not only at exit 70. Avoid payloads and repeat diagnostics.
For child calls, host diagnostics include the invocation identity, host-local
connection ordinal and existing wire request ID; wire replies retain that request
ID, so a new correlation field is unnecessary in v1. S-OBS verifies the rendered
provider identity and chain survive the wrapper and outer hooks. Live scope
introspection is deferred to a future sanitized diagnostic snapshot, not an
invitation for isolated diagnostic workers to import providers.

Consumption may catch expected registry errors, log a warning and report unknown
measurements. Reclaim may catch them and return failure with zero deletion. Neither
consumer should catch every `RuntimeError` and continue as though inventory were
empty. There is no legacy context fallback when services are missing.

## Review

Check stale callback handles, same-thread borrowing of an active ancestor handle,
missing operations on A runtimes, ambiguous providers, filtered defaults, unsupported
optional methods, and fresh detached responses on repeated calls. Prove the import
closure of a provider/consumer excludes `engulf-services` runtime, and that of a
Python child excludes concrete Engulf/wrapper runtimes.
