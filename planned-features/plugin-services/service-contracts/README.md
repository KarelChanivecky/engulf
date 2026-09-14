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

## Interaction pseudocode

```text
# Consumer imports its capability API and engulf-services-api, not the runtime.
registry = LabRegistryClient(services(api).require(REGISTRY_CAPABILITY))
inventory = registry.records()                  # complete immutable snapshot
registry.commit_observations(observations)      # return only after all acknowledgments

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
