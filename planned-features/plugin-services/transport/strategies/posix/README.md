# Unix transport strategy

Back to [transport strategies](../README.md). This B implementation is the only
place in the service transport that knows Unix socket descriptors and their native
identity. The corresponding wrapper adapter is Linux-specific; a working POSIX
channel does not imply that the existing wrapper supports every POSIX OS.

## Native mechanism

`UnixTransportStrategy` creates a private `AF_UNIX` / `SOCK_STREAM` socketpair.
Both host-owned descriptors start non-inheritable; the host end is nonblocking.
The Linux execution strategy passes only the intended child end using `pass_fds`.
There is no filesystem listener, endpoint discovery or network fallback.

The proposed bootstrap record is:

```json
{
  "v": 1,
  "transport": "unix-stream-v1",
  "endpoint": {"fd": 7, "dev": "9", "ino": "12345"}
}
```

The numbers are illustrative. `fd` is a nonnegative integer excluding booleans;
`dev` and `ino` are canonical nonnegative decimal strings so JSON integer precision
does not constrain native identity. The entire bootstrap is limited to 4 KiB,
with exact fields, bounded nesting and strict UTF-8/JSON parsing. Reject metadata
above the limit before decoding it. `v` versions the outer bootstrap; `transport`
identifies the exact native payload format, independently of the service protocol.

## Ownership pseudocode

```text
open_pair():
    verify concrete support without allocating
    create socketpair; immediately record both owned endpoints
    make host end nonblocking; make both ends non-inheritable
    capture child descriptor identity and immutable bootstrap
    return HostEndpoint(...)
    on any failure: exhaust both endpoint closes; preserve original failure

connect(endpoint_payload):
    validate exact fd/dev/ino payload
    inspect fd without taking ownership
    require matching fstat identity and connected AF_UNIX SOCK_STREAM socket
    duplicate/claim under the client's endpoint-ownership lock
    recheck identity; mark owned child endpoint non-inheritable and nonblocking
    return UnixTransportChannel(...)
    on any failure: close only resources this attempt owns
```

Inspection through a temporary Python socket wrapper must not accidentally close
the borrowed descriptor. Use a non-owning inspection or inspect an owned duplicate
and detach any borrowed wrapper. Capture/claim/cleanup must all use the same
ownership record. A stale environment value cannot authorize closing an unrelated
descriptor that now has the old number. No validation check turns identity into
OS isolation or a trust decision.

One client owns each endpoint. Duplicate claims cannot race handshakes or readers.
The host drops its child-side copy after spawn notification; the child claims the
inherited endpoint and does not pass it to ordinary descendants. Bind explicit
proxy child endpoints through the same strategy later.

## Wrapper binding and readiness

The optional Unix wrapper binding creates opaque `ExecutionLaunchAttachment` and
`ExecutionWaitResource` objects tied to this endpoint/session. Only its platform
adapter and the Linux execution strategy inspect native descriptor/identity data.
The generic `ExecutionLaunch`, pump and plugin APIs never contain `pass_fds` or
require a `fileno()` method.

The Unix strategy implements bounded nonblocking reads/writes. The Linux process
strategy maps opaque interest resources to selector registrations and maps events
back to the same resource objects. Child clients use the Unix channel's own bounded
wait method. A timer wakeup still advances protocol deadlines with no ready events.

Acceptance covers actual Python/Go child traffic, stale/reused descriptors,
identity/family/type mismatch, partial I/O, no child inheritance leak, duplicate
claims and every open/spawn/close failure. Do not claim native Windows or all-POSIX
wrapper behavior from these Linux tests.
