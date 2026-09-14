# Platform transport strategies

Back to [transport](../README.md). This is the OS boundary required by the user.
These are proposed B runtime interfaces, not a new implemented package or an A
commitment to particular private class names.

| Component | Responsibility |
| --- | --- |
| Portable protocol engine | Framing, validation, grants, IDs, budgets, queues, uncertainty and service dispatch admission |
| `TransportStrategy` | Availability, endpoint creation/claim, identity and ownership checks, native byte I/O and closure |
| Optional wrapper binding | Convert strategy-owned endpoints into opaque execution attachments and wait resources |
| Wrapper execution strategy | Consume those resources to launch the child and wait; own process/signals/reaping |
| [Unix strategy](posix/README.md) | Initial socketpair implementation and its native bootstrap payload |
| [Windows strategy](windows/README.md) | Importable, explicitly unavailable stub with zero IPC side effects |

The strategy contains mechanisms. It receives no callback API, service directory,
provider instance, scope token or business-dispatch callback. The portable pump
remains responsible for calling the goal's managed operation client on the current
invocation thread. Strategies are trusted runtime collaborators, not plugins
registered in shared context.

## Interface and selection

```text
TransportSupport: frozen(backend_id, implemented, reason)

TransportStrategy:
    support -> TransportSupport
    open_pair() -> HostEndpoint
    connect(endpoint_payload) -> TransportChannel

HostEndpoint:
    channel -> TransportChannel
    bootstrap -> bounded immutable EndpointRecord
    release_child_copy() -> None              # idempotent after successful spawn
    close() -> None                           # idempotent, exhaust owned endpoints

TransportChannel:
    read_some(limit: int) -> bytes | None      # None: would block; b"": peer EOF
    write_some(data: memoryview) -> int        # 0: would block; failure raises
    wait(readable: bool, writable: bool, timeout: float) -> ChannelReady
    close() -> None                           # invalidate before native release

select_transport_strategy():
    if local_platform is Windows:
        lazily import WindowsTransportStrategy
        return WindowsTransportStrategy()
    if local_platform is supported POSIX:
        lazily import UnixTransportStrategy
        return UnixTransportStrategy()
    return UnsupportedTransportStrategy(reason="no IPC strategy for this platform")
```

Selection is a fixed, framework-owned dispatch at the services boundary. Importing
API, client or local-routing modules does not select a strategy or probe the OS.
Probe `.support` without allocating resources; an unavailable strategy must also
reject operations when a caller ignores the probe. Never map an unknown platform
to Unix by default, use a wire string as a module name, or retry with another
transport after failure. Tests may inject a strategy privately at composition time;
provider metadata and request payloads cannot supply one.

Endpoint payloads contain only bounded bootstrap data. The enclosing record has a
fixed version and a backend identifier. After bounded structural parsing, the client
selects its local strategy, checks availability, checks the identifier against that
strategy, and delegates payload validation/claim. Incompatible metadata fails
before native ownership is taken. Transport versioning is independent of the
service protocol and capability majors.

## Ownership and integration

`engulf-services` owns the portable engine, channel interface and concrete transport
strategies. Its optional `executable_wrapper` integration alone imports wrapper API
types. The Unix binding exposes strategy-owned resources using the native adapter
contracts described under [execution strategies](../../executable-support/strategies/README.md).
Neither portable services nor core imports the wrapper runtime.

Host steps call only nonblocking `read_some`/`write_some`, with the existing per-step
limits. The wrapper waits on bound opaque resources through its execution strategy;
the host pump does not also call `channel.wait`. A standalone child client or later
proxy uses channel/strategy waiting instead. Thus there is one wait owner per
execution path. Readiness is a hint: another operation or peer closure may make an
I/O attempt return would-block or EOF.

Generic code never calls `fileno`, `fstat`, `select`, native handle operations or
`Popen`. It never interprets attachment/resource internals. Backend buffers must be
included in the existing charged-memory and per-turn I/O limits; a strategy must
not hide an unbounded read-ahead queue. No host background provider dispatch is
introduced by this pattern. A future backend with completion-based I/O must adapt
to the same bounded channel events and invocation-thread dispatch contract.

## Availability and lifecycle

No broker/child transport configured means no strategy selection and no child
scope allocation. When transport is requested, reject unavailable or incompatible
transport/execution strategies before endpoint allocation, `OpenChild`, preparers
or spawning the intended child. The existing Linux-only wrapper may reject Windows
earlier; the services stub remains independently testable without importing it.

Opening self-unwinds every acquired resource, including when scope creation fails
after the endpoint pair exists. The returned session owns the pair; the wrapper
keeps opaque attachment references for independent idempotent cleanup if a helper
notification fails. `stop` closes ingress through the strategy, while `close`
releases the child scope through managed operations. OS errors do not fabricate
provider attribution. Neither a missing implementation nor an absent endpoint is
a successful connection.

A freezes only the portable wrapper definitions and unavailable generic surfaces.
B adds the working Unix transport, the Windows stub and private strategy selection.
A future Windows implementation replaces its strategy and corresponding process
binding without changing service methods, codecs, scopes or plugin catalogs.

## Recursive review

| Counterexample | Required behavior / gate |
| --- | --- |
| A module reads `socket.AF_UNIX` at import on Windows. | Block Unix imports in portable/stub import tests; load concrete modules only at selection. T-PLATFORM |
| An endpoint names a backend from another OS or an arbitrary Python module. | Fixed local selection and exact backend match; no dynamic import or native claim from that string. T-STRATEGY |
| Stub returns `None`, triggering the no-broker path and silently running without requested IPC. | Raise typed unavailability before allocation; no implicit fallback. T-WINDOWS |
| Replacing a channel changes frame parsing or error categories. | Run the portable engine against a non-fd fake strategy with the same vectors, limits and EOF/error cases. T-STRATEGY |
| Helper and process strategy both close the same numeric descriptor. | Share one idempotent owned attachment, never copy raw close authority. W-STRATEGY |
| A backend waits in the host step or dispatches on its I/O worker. | Bounded nonblocking host I/O; wrapper owns waits and invocation thread owns dispatch. T-BOUND, C-FRAME |
