# Explicitly unavailable Windows strategy

Back to [transport strategies](../README.md). The user chose a strategy boundary
with a Windows stub. This is an intentional B delivery result; implementing named
pipes, Windows sockets or a Windows child-process adapter is not required here.

```text
WindowsTransportStrategy.support:
    return TransportSupport(
        backend_id="windows-unavailable",
        implemented=False,
        reason="child-process service IPC is not implemented on Windows"
    )

WindowsTransportStrategy.open_pair():
    raise UnsupportedTransportError(reason=support.reason)

WindowsTransportStrategy.connect(endpoint_payload):
    raise UnsupportedTransportError(reason=support.reason)
```

The stub imports only portable definitions. Construction and support queries do
not import a Unix module, inspect native descriptors, create sockets/pipes, spawn
a process, change environment variables, allocate a child scope or dispatch a
provider. Requests fail in the same way even if a caller skips the support probe.
No dummy channel or partial handshake is returned.

`windows-unavailable` is an availability identifier, not a valid bootstrap or wire
transport. The stub never publishes endpoint metadata. A future working backend
will have a separately specified native payload identifier; no Windows payload or
IPC primitive is frozen now. A stale Unix environment value cannot select a Unix
implementation on Windows.

## Separation from local services and A

| Use | Required result |
| --- | --- |
| Import service API/client/local runtime | Succeeds without loading transport or wrapper implementation |
| Register/call local services in B | Uses normal managed dispatch on Windows; no IPC strategy involved |
| Probe the Windows IPC strategy | Reports unavailable with a stable reason; no side effects |
| Request IPC, with or without the probe | Raises `UnsupportedTransportError` before resource allocation |
| No configured child transport | No strategy opening; ordinary local service behavior |
| A foundation on any supported core OS | Managed operations and wrapper support remain explicitly unavailable as already agreed |

The generic wrapper uses an unavailable Windows execution strategy as described in
[execution strategies](../../../executable-support/strategies/README.md). This
does not make the existing Linux wrapper runnable on Windows. Local Windows tests
use a portable goal and independently exercise the services transport stub.

## Acceptance

Run on actual Windows CI: import API/client/local runtime with forbidden Unix and
wrapper-runtime imports instrumented to fail; invoke real local service ownership,
failure and repeated-invocation cases; probe and call the stub; check unchanged
environment and zero socket/pipe/process/scope/provider side effects. Include stale
Unix metadata and calls that ignore availability. Non-fd fake-strategy tests also
run on Linux, but do not replace native Windows import/local/stub acceptance.
