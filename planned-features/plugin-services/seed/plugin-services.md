# Optional plugin service broker

Status: planned; implementation has not started.

## Summary

Implement services as an optional broker plugin and goal integration library.
Engulf core continues to provide discovery, managed callbacks, state, leases, and
diagnostics through its existing APIs.

The broker provides **discover → select → call → execute → return**. Goals publish
their capability interfaces; active goal plugins implement them. Service-specific
workflows and communication remain part of those contracts.

## Packages and public interfaces

- Add `engulf-services-api` for typed capability definitions, method identities,
  request/result codecs, immutable provider descriptions, and provider adapters.
  Capability compatibility uses a stable identifier and independent API major.
- Add `engulf-plugin-services` for the broker, Python client, POSIX transport,
  proxy support, and goal integration helpers. Export a normal
  executable-wrapper plugin adapter; other goals supply adapters for their own
  plugin contracts.
- Goal-owned service API packages publish Python interfaces and explicit codecs.
  Codecs translate requests and results to JSON-compatible values; Python
  implementation objects never cross the broker interface.
- Expose an invocation-bound `ServicesSession` with:
  - `providers(capability)` to enumerate compatible active providers.
  - `require(capability, provider_id=None)` to obtain a provider handle.
  - A typed method-call interface on that handle.
- Resolve a single provider using an explicit ID, a goal-configured default, or
  the sole available provider. Otherwise raise a missing-provider or ambiguity
  error. Enumeration is deterministic; plugin priority does not silently select
  a provider.

## Registration and goal integration

- Collect immutable capability declarations during goal setup using existing
  `GoalPhase` dispatch. Freeze the directory after registration and derive
  provider identity from Engulf’s attributed contributions.
- Keep implementations inside their providing plugins. The broker stores
  descriptions and routing information, and the goal supplies a bridge that
  dispatches each request through the existing execution endpoint.
- Use normal plugin selection and goal compatibility checks. Service lookup does
  not discover or activate additional plugins. Applications requiring services
  explicitly require the appropriate broker plugin.
- Execute service callbacks serially on the invoking goal’s thread. Each call
  receives the providing plugin’s active API, preserving its context declarations,
  state namespace, logging, and lease cleanup.
- Add an optional `execution_support` interface to the executable-wrapper goal,
  defined in its API package. It supports setup, a scoped execution session, child
  environment additions, explicitly inherited descriptors, a post-spawn
  notification, and request pumping while waiting for the child. The broker
  package implements this interface; the wrapper does not import the broker.
- Preserve shell-free execution, inherited standard streams, terminal behavior,
  process groups, signal forwarding, and existing exit-code semantics. Create
  broker connections only for viable normal execution.
- Scope connections and dispatch bridges with `try/finally` around goal
  execution. Close them before postprocessing, including on spawn failure and
  interrupts; do not depend solely on `after_goal`.

## RPC, process relationships, and failures

- Implement protocol version 1 as request/response JSON messages with a four-byte
  network-order length prefix and a configurable 1 MiB default message limit.
  Requests identify the capability, API major, provider, method, and encoded
  input; responses contain an encoded result or structured error.
- Use private POSIX socket pairs. Explicitly pass the child endpoint during
  launch, close redundant parent copies, and make received endpoints
  non-inheritable in clients.
- Provide child-proxy support: descendants receive a newly created connection to
  their immediate parent’s proxy. Each proxy can expose a subset of its upstream
  capability/provider grants. Do not introduce a public listener or authorize
  callers through claimed PIDs.
- Treat parent-channel loss as terminal for that session. Fail pending and
  subsequent calls; supported clients end the affected invocation. Recovery
  starts a fresh invocation.
- Never automatically retry calls. Losing a response can leave the operation’s
  outcome unknown. Preserve provider attribution and distinguish declared service
  errors, invalid requests, provider failures, and connection loss.
- Keep sockets, shared-memory objects, streaming protocols, accessors, and their
  lifetime rules entirely within the goal–service contract. The broker does not
  manage those resources or police communication outside brokerage.
- Implement the POSIX backend now. Keep imports portable and provide a Windows
  transport stub that raises a clear unsupported-platform error. In-process
  Python calls remain portable.

## Validation and defaults

- Demonstrate the same capability through a Python goal and a Go executable
  launched by the wrapper, including two interchangeable providers.
- Test registration failures, version mismatches, empty and ambiguous lookup,
  explicit defaults, inactive providers, and non-import of unselected plugins.
- Verify equivalent codec behavior locally and across processes, malformed and
  oversized messages, attributed failures, and absence of automatic retries.
- Use deterministic process coordination to test direct-child access, restricted
  descendant proxies, descriptor inheritance, parent/proxy crashes, interrupts,
  repeated invocations, and cleanup.
- Cover callback-bound APIs and leases, wrapper signal/terminal regressions,
  portable imports, and the Windows stub.
- Run the required workspace checks and new package suites; add the packages to
  build, typing, and documentation checks, then run `make build` with Twine
  validation.
- Start new distributions at `0.1.0`, include `py.typed`, and leave existing
  versions and `PLUGIN_API_MAJOR` unchanged.
- Trust installed providers and participating goal/proxy code. Broker grants
  constrain broker access; they do not establish an OS sandbox or prevent an
  authorized participant from forwarding requests.
