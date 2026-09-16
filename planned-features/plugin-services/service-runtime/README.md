# Service runtime

`engulf-services` implements **one generic invocation operation** containing local
routing and private child-scope control. It owns per-invocation state; the immutable
setup directory and codec catalog can live with the application configuration.
No process-global provider registry, callback cache or current-scope global exists.

| Subcomponent | Details |
| --- | --- |
| [Directory and policy](directory/README.md) | Attributed setup, compatibility, defaults, access and readiness |
| [Routing and child control](routing/README.md) | Reentrant handler, trusted caller facts, private control envelopes |
| [Scopes and cleanup](scopes/README.md) | Per-scope DAG, touched providers, close ordering and dependency calls |

## Composition

```text
goal setup:
    dispatch CONFIGURE and REGISTER to selected participants
    freeze accepted directory, codec catalog, policy and optional broker config
    require implemented generic operations
    register one InvocationOperation(
        operation_id=SERVICE_OPERATION_ID,
        phases=(SERVICE_CALL_PHASE, SERVICE_CLOSE_PHASE),
        handler_factory=lambda invocation: ServiceHandler(frozen_setup, invocation)
    )

ServiceHandler:
    invocation_scope
    child_scopes indexed by opaque host token
    per-request context stack
    route local calls and goal-only control requests
    close all scopes once on core finalization
```

The lambda illustrates a setup-data-only factory; it does not capture a setup API,
plugin object or invocation capability. Factories and codec bindings are trusted
local integration code, never registered provider implementations.

## Why one handler

Splitting a local router operation and a child-control operation would require
cross-factory shared state and cross-operation cleanup ordering. One handler allows
a single invocation resource owner, scope stack and finalizer. Private host controls
remain a separate request variant guarded by actual goal caller kind; they do not
become capability methods or wire messages. This removes the need for a generic
control bus or shared-context bootstrap handle.

Local operation handling is available even without the child broker. The local
`install_services` entry point installs it directly during goal setup; an app-owned
wrapper subclass can use it without process-support changes. The optional wrapper
helper is a later alternative setup owner; `open()` returns `None` when no authorized
child transport is configured. Register once, through one path. Plain Python goals
use the same local entry point without wrapper imports.

## Review

There are two graphs with different purposes: existing plugin ordering establishes
initialization/preparation, while the service scope DAG records actual resource
dependencies. Neither replaces the other. There are also two identities: immediate
provider caller determines dependency access, while initiating scope determines
resource ownership. Conflating them either leaks child grants or closes resources
at the wrong time. The routing and scope pages make both explicit.
