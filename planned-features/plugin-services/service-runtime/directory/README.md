# Directory, policy and readiness

Back to [service runtime](../README.md).

## Setup algorithm

```text
configuration = goal-owned accepted capabilities, codecs and application policy
broker_contributions = setup.dispatch(CONFIGURE, immutable configuration event)
registrations = setup.dispatch(REGISTER, immutable accepted-capability event)

for contribution in registrations:
    provider_id = contribution.plugin_id           # runtime attribution
    reject duplicate capability registration by this provider
    validate against canonical accepted descriptors and codec catalog
    add immutable provider descriptor              # no implementation/callback/API

freeze directory sorted by provider ID and capability identity
validate configured defaults and conditional required services
freeze access policy and optional broker configuration
```

`org.engulf.services.configure` and `org.engulf.services.register` are broadcast setup
phases. All participants see the same input; contributions are merged only after
dispatch. Registration does not inspect other contributions. Reject duplicate broker
configuration rather than choose one by traversal order. Missing broker is ordinary:
there is simply no child transport configuration.

Application-accepted descriptors and codec identities define compatibility. Child
directory views advertise only permitted capability/major/provider triples and the
accepted method subset. No request triggers fresh discovery or imports. A new
Application still observes a new installed environment using core's discovery
snapshot; do not add a process-global directory cache.

## Access and selection

Local access is an application-owned policy indexed by runtime caller kind/ID and
target capability/provider. Child grants default to empty. A provider serving a
child uses its own policy when it calls dependencies; the dependency is still owned
by the child's resource scope. This does not grant the child direct dependency
access or expose the dependency in the child directory.

Resolve an explicit provider, an authorized configured default, or a sole compatible
authorized provider; otherwise return missing/ambiguous. Defaults are validated at
setup and again against the particular caller's filtered view. An inaccessible
default cannot silently grant access or change to another provider. Use an explicit
typed rejection so configuration mistakes are visible.

Conditional requirements use immutable selected-plugin IDs from setup. eclab
requires the registry only when its selected consumers need it. An optional provider
selected by application policy can still be a mandatory dependency of an active
consumer; services does not weaken the existing packaging dependency rules.

## Readiness

| State | Meaning |
| --- | --- |
| Selected | Core chose the installed goal adapter |
| Registered | Its setup contribution matched an accepted capability |
| Entered | Core completed its `before_goal` successfully |
| Method ready | The owner has completed any domain-specific preparation required for this method |
| Closing/closed | The current resource scope only permits existing cleanup dependencies, or permits no calls |

The directory is not a readiness registry. Core enforces entered status at dispatch;
providers enforce later method readiness before business work. Archive/vrnetlab
maps become ready in their own `prepare_call`, not upon setup registration. Preserve
packaging order paths for every early selectable alternative. Arbitrary priority or
retrying `ProviderNotReady` is not a replacement for that path.

## Observability and review

Expose a safe immutable setup snapshot of accepted descriptors, registered provider
IDs, defaults and policy. Managed debug reporting begins after invocation logging
options apply. Setup-only diagnostics report readiness as unevaluated. Explain local
rejections with caller, target and phase without exposing hidden providers to children.
Do not teach isolated diagnostic workers to import host providers; a separate future
sanitized snapshot contract is required for that extension.

Test both application construction paths, minimal policies, editions, absent broker,
filtered defaults, optional method subsets, early consumers, and no import of an
unselected catalog module. Setup has no sockets and no provider business work.
