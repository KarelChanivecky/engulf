# Descriptors, participants and replies

Back to [service contracts](README.md).

## Immutable description model

| Record | Proposed information |
| --- | --- |
| `CapabilityDescriptor` | Qualified capability ID, independent positive major, canonical required method set and recognized optional methods |
| `MethodDescriptor` | Stable method ID, request/result codec identities and versions, declared domain error codes; no Python import target |
| `CapabilityImplementation` | Capability identity plus implemented compatible optional subset; image-domain preference metadata is capability-owned, not a generic routing priority |
| `ServiceRegistration` | Tuple of implementations supplied by one selected participant; no claimed provider ID or implementation object |
| `ProviderDescriptor` | Runtime attribution ID plus validated public implementation data; frozen after setup |
| `ServiceCallContext` | Opaque scope ID, immediate caller and initiating origin facts, host-local absolute monotonic deadline, maximum result-payload bytes |
| `ServiceRequest` | Capability/method identity, decoded immutable domain request, `ServiceCallContext` |
| `ServiceReply` | Explicit success value or declared domain error value; never absent contribution |
| `ServiceScopeClose` | Scope ID and reason, host cleanup budget, frozen dependency information sufficient for authorized cleanup calls |

Canonical descriptors come from the application's accepted capability APIs. Match
IDs **and** method/codec definitions; matching names alone is insufficient. Required
methods must all exist with exact compatible definitions. Optional subsets can
differ but cannot redefine a recognized method's request/result semantics. Unknown
optional methods are neither advertised nor callable until the application accepts
them. Capability/schema majors are independent from plugin catalog majors.

The context is host-derived. A service payload cannot override caller, provider,
scope, origin, deadline ceiling or grants. A host monotonic timestamp is not a
portable cross-process timestamp: the wire carries remaining duration. Provider
adapters may use the local deadline to calculate finite lock/I/O waits. Context
contains no API, state handle, logger, lease, socket or callback.

## Participant interface and adapters

The service participant interface is an opt-in mixin/protocol alongside the
goal-specific plugin base, not a new unrelated goal catalog. Nonparticipants have
an explicit no-registration result in setup and are never selected for business
service calls. Calls go to the active goal adapter's ID.

```text
ServiceParticipant:
    register_services(event, registration_api) -> ServiceRegistration | None
    call_service(request: ServiceRequest, invocation_api) -> ServiceReply
    close_service_scope(event: ServiceScopeClose, invocation_api) -> None

module_level_call_adapter(plugin, local_event, owner_api):
    # local_event contains a trusted application-selected MethodBinding;
    # that binding is local adapter metadata, not portable provider registration.
    request = local_event.binding.request_codec.decode(local_event.payload)
    reply = plugin.call_service(ServiceRequest(..., request, local_event.context), owner_api)
    require explicit ServiceReply and declared domain-error code
    encoded = local_event.binding.encode_reply(reply)  # validate while owner is active
    require encoded fits the result limit and canonical value limits
    return EncodedServiceReply(encoded)
```

The router already validates the incoming payload before touching the provider.
Failure to decode that validated canonical value inside the adapter is a codec or
adapter defect, not a new caller mistake. The adapter owns validation, not directory
selection or business logic. The trusted codec binding comes from the separate
application codec catalog; a registration or wire name never supplies executable
code. Provider method logic receives only the decoded request and its own API.

## Error semantics

| Category | Examples | Consequence |
| --- | --- | --- |
| Request rejection | Missing/ambiguous provider, denied access, unsupported method, expired before dispatch, scope cycle, not ready | Recoverable; provider not invoked for rejected admission |
| Declared domain failure | Registry unreadable, commit failed, inventory/record exceeds configured domain limits | Recoverable response; consumer chooses safe behavior |
| Valid negative domain result | Image `Reject` or `NoOpinion` | Successful typed response; image core applies domain policy |
| Provider defect | Unexpected exception, `None`, wrong result or undeclared error | Managed failure latch; preserve owner attribution |
| Infrastructure defect | Broken routing invariant, handler failure, internal transport failure | Managed failure latch with honest infrastructure origin |
| Termination | `KeyboardInterrupt`, `SystemExit`, other non-`Exception` termination | Cleanup, child reaping if needed, then propagation |

Map only known expected storage/observation failures to declared errors. Catching
every `Exception` as `inventory_unavailable` would hide bugs and defeat the latch.
An oversized arbitrary provider reply is a contract defect; a registry adapter
that detects its documented domain limit **before** constructing such a reply may
return the declared size error instead.

## Review gates

Prove incompatible same-ID descriptors fail setup, optional subsets remain usable,
unselected providers are not imported, wrapper adapter identity is retained, and
the provider's result codec failure is attributed while its API is active. Test
domain refusal separately from an unexpected provider exception; both consumers
must make different decisions without inspecting raw exception strings.
