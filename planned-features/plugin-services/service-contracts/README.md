# Service contracts

`engulf-services-api` owns optional service definitions and an API-only local facade.
It depends on `engulf-api`, never on `engulf` or a wrapper runtime. Capability API
packages own domain records, codecs and typed clients. Providers and consumers
depend on those API packages. Their code does not import the broker/router.

| Subcomponent | Details |
| --- | --- |
| [Descriptors and participants](descriptors.md) | Capability compatibility, registration, method calls and close events |
| [Values and codecs](codecs/README.md) | Local/wire equivalence, canonical values, ownership of codec code |
| [Client facade](clients/README.md) | API-only calls, handles, errors and lifetime |

These definitions are B work. A reserves only the generic operation entry point
through which the facade will communicate. Finalize capability APIs against registry
and image consumers before publishing their new versions.

The author-facing module, signatures, identifier grammar and phase values are in
[descriptors](descriptors.md) and [clients](clients/README.md). S-AUTHOR requires a
complete typed provider/consumer/application fixture using those public imports,
including an old nonparticipant plugin. Until that fixture passes, B's public
constructors remain proposed; no prose example counts as implementation evidence.

## Worked local call

Use the registry as the first complete authoring fixture. The application creates
accepted registry descriptors/codecs and calls `install_services` during its goal's
setup (see [composition](../eclab/application/README.md)). REGISTER broadcasts to all
selected plugins; ordinary plugins return no contribution, and the registry returns
its immutable `ServiceRegistration`. Packaging order lets registry enter before
consumption's `before_goal`.

Consumption creates `LabRegistryClient(services(api).require(REGISTRY_CAPABILITY))`.
Its `snapshot()` call encodes `begin_snapshot`, enters the one service operation,
and dispatches the registry adapter with the registry's API. The registry takes its
finite state transaction, returns a validated page, and deactivates. Consumption
receives detached records and read tokens. Later pages use retained immutable data;
they do not reread the whole file. After consumption finishes, core closes the
invocation's touched registry scope. A declared unreadable inventory is recoverable;
an unexpected provider error is attributed to the registry and latches exit 70.

## Interaction pseudocode

```text
# Consumer imports its capability API and engulf-services-api, not the runtime.
registry = LabRegistryClient(services(api).require(REGISTRY_CAPABILITY))
baseline = registry.snapshot()                 # complete pre-sample records/bases
observations = sample_with_record_bases(baseline)
registry.commit_observations(observations)      # conditional writes, all acknowledged

# Facade talks to the one generic service operation.
wire_request = capability_codec.encode_and_validate(request)
reply = api.operations.request(SERVICE_OPERATION_ID,
    LocalCall(capability_id, major, provider_id, method_id, wire_request))
return capability_codec.decode_and_validate(reply)

# Registration returns data. Provider identity is supplied by dispatch attribution.
plugin.register_services(setup_event, registration_api):
    return ServiceRegistration(capabilities=(REGISTRY_IMPLEMENTATION,))
```

Avoid a universal remote-object API, annotation-driven auto-export, arbitrary Python
exception serialization, or a generic persistent resource manager. The abstractions
here are justified by two domain consumers and the Python/Go boundary: explicit
method descriptors, codec bindings, typed replies and an invocation-bound facade.

## Review

Portable service **payloads** are distinct from local framework **dispatch events**.
The latter can carry a trusted host codec binding so validation happens while the
provider owns the activation. That binding is not advertised, transmitted, or
accepted from a child. This avoids pretending the existing local `GoalPhase` adapter
is already a remote endpoint contract. A future endpoint backend must define a
goal-owned codec for this envelope and resolve codec IDs at its destination.
