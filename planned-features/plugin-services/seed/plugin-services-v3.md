# Optional plugin services: implementation plan v3

Status: proposed implementation plan; implementation has not started.

This saves the expanded services plan agreed in the planning discussion. It succeeds
[v2](plugin-services-v2.md), the [original plan](plugin-services.md), the
[critique](plugin-services-critique.md), the
[synthesis](plugin-services-critique-synthesis.md), and the
[synthesis review](plugin-services-synthesis-review.md). Earlier plans and reviews
remain unchanged. Where their decisions conflict with this document, v3 governs.
The plan revision is 3; the proposed services API major and wire protocol version
both remain 1.

Source baselines are Engulf `4bac606f1aeb3547ad64febfd1fd8068dcd994d4` and
engulf-clab `5f3afaec5032133e003e4e5309ab1c690450e284`, together with the inspected
working-tree state. Engulf-clab source references use the sibling checkout
`../../engulf-clab/` relative to this document. Public names introduced below are
proposals, not existing APIs. Saving this plan does not implement or publish it.

## 1. Outcome and decisions

Selected plugins expose typed services to goals, other plugins, and explicitly
granted child processes. Every provider runs through the framework's execution
endpoint, inside its own activation, with its own state, context, logger, and lease
capabilities. Shared context carries invocation data; it does not carry a second
plugin execution mechanism.

The first production acceptance cases are the lab registry, consumption, sleep,
and image-provider workflows in engulf-clab. A portable Python example and a wrapped
Go example exercise the same capability with two interchangeable providers. An
explicit descendant proxy example exercises grant restriction and upstream routing.

The two architecture choices made in the discussion are fixed:

- Add a generic managed invocation-operation facility to `engulf-api` and `engulf`.
  Core owns activation, attribution, invocation lifetime, and cross-callback lock
  rules. Optional services packages own capabilities, codecs, routing, resource
  scopes, and transport.
- Support synchronous acyclic provider call chains, including A → B → C. Reject
  recursive activation and dependency cycles before invoking the target.

This replaces v2's exclusions of core API changes, plugin callers, and nested
provider calls. It also replaces its goal-only session lifetime, reverse-first-use
cleanup, and failure latch owned solely by a goal helper.

Keep one outstanding request per transport connection, explicit descendant proxying,
bounded buffers, and no automatic retry or reconnect. Network listeners, asynchronous
providers, streaming RPC, remote callbacks, forced cancellation of Python callbacks,
automatic plugin activation, and automatic upstream discovery remain outside v1.

Normal plugins remain trusted in-process code with the application's OS authority.
Service grants constrain managed requests; they are not OS isolation. Preserve the
existing goal privilege opt-in and plugin elevation checks. Add no separate approval
or elevation flow.

## 2. Source evidence and architectural consequences

| Current source | Finding and consequence |
| --- | --- |
| [`InvocationAPI`](../../../engulf-api/src/engulf_api/plugin_api.py#L37) and [`GoalAPI.dispatch`](../../../engulf-api/src/engulf_api/plugin_api.py#L143) | Ordinary plugin callbacks have no dispatch capability. A goal-owned helper cannot support `before_goal` consumers without a new sanctioned core entry point. |
| [`_PhaseDispatcher`](../../../engulf/src/engulf/_dispatch.py#L224) and [`_InProcessPluginEndpoint`](../../../engulf/src/engulf/_plugin_execution.py#L81) | Dispatch activates the owner and invokes its endpoint. Managed operations must reuse this path instead of retaining implementations. |
| [`Application._invoke`](../../../engulf/src/engulf/application.py#L750) | A `before_goal` result can skip `achieve`; termination can skip ordinary after hooks. Core must finalize invocation operations in a `finally` before state destruction and API closure. |
| [`_ActivationState`](../../../engulf/src/engulf/_capabilities.py#L66) and [`_LockCoordinator`](../../../engulf/src/engulf/_capabilities.py#L245) | Existing guards do not establish operation-client thread affinity or coordinate lock acquisition across a nested participant stack. Add those checks in core. |
| [`PluginCallbackError`](../../../engulf-api/src/engulf_api/errors.py#L13) and [`_dispatch.py`](../../../engulf/src/engulf/_dispatch.py#L230) | Current errors identify one callback; ordinary wrapping can misattribute a nested failure to its caller. Preserve the originating provider and chain, and track cleanup participation explicitly. |
| [`LabRegistry` contract](../../../../engulf-clab/plugins/engulf-clab-lab-registry-api/src/engulf_clab_lab_registry_api/contract.py#L49) and [`SessionLabRegistry`](../../../../engulf-clab/plugins/engulf-clab-lab-registry/src/engulf_clab_lab_registry/storage.py#L16) | The shared object intentionally contains a capability-free snapshot and pending intents. This is not an expired-state-handle defect, but its methods bypass managed provider activation and acknowledge only an in-memory update. |
| [`registry.after_goal`](../../../../engulf-clab/plugins/engulf-clab-lab-registry/src/engulf_clab_lab_registry/plugin.py#L91) and [`sleep.execute_sleep`](../../../../engulf-clab/plugins/engulf-clab-sleep/src/engulf_clab_sleep/command.py#L148) | Persistence follows Docker deletion today, despite sleep's persistence-before-deletion contract. A registry service must acknowledge a completed write before deletion starts. |
| [`consumption.before_goal`](../../../../engulf-clab/plugins/engulf-clab-consumption/src/engulf_clab_consumption/plugin.py#L91) and [`sleep.before_goal`](../../../../engulf-clab/plugins/engulf-clab-sleep/src/engulf_clab_sleep/plugin.py#L105) | Both commands can finish before the goal runs. Local services must already work here, without opening a child transport. |
| [`PROVIDE_IMAGE_PHASE`](../../../../engulf-clab/plugins/engulf-docker-image-api/src/engulf_docker_image_api/contract.py#L381) and [`DockerImageGoal`](../../../../engulf-clab/plugins/engulf-docker-image-core/src/engulf_docker_image_core/goal.py#L39) | The standalone image goal already dispatches provider logic in the owner's activation. Preserve that adapter and execution shape. |
| [`image-build.prepare_call`](../../../../engulf-clab/plugins/engulf-clab-image-build/src/engulf_clab_image_build/plugin.py#L227) and [`registered_provider_lookup`](../../../../engulf-clab/plugins/engulf-docker-image-core/src/engulf_docker_image_core/resolver.py#L74) | The wrapper path retrieves live providers from context and directly calls `registered.provider.provide(requirement)`. Replace this parallel path with managed offer requests. |
| [`ExecutableWrapperGoal`](../../../engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py#L375) | Transport opens after veto resolution and before preparation. Local services have the wider invocation lifetime. Preserve preparation's existing per-plugin unwind. |
| [`_execute`](../../../engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py#L837) | Existing broad spawn handlers can misclassify an `OSError` after spawn. Repair this independently before adding the pump. |
| [`edition()`](../../../engulf/src/engulf/application_definition.py#L106) and [CI](../../../.github/workflows/ci.yml#L27) | Editions preserve the base factory, so it installs integration. Also repair the existing CI omission of the encryption core dependency before using examples as validation. |

The actual sibling package directories are `plugins/engulf-clab-lab-registry`,
`plugins/engulf-clab-consumption`, and `plugins/engulf-clab-sleep`. Their API packages
remain separate from runtime implementations.

## 3. Generic managed invocation operations

### Public interfaces and ownership

Add these portable contracts to `engulf-api`, with runtime implementations in
`engulf`. They contain no service, socket, executable-wrapper, or capability schema
dependencies.

| Proposed interface | Contract |
| --- | --- |
| `GoalSetupAPI.register_operation(definition)` | Register a goal-owned operation during setup. Duplicate operation IDs and registration outside setup fail. |
| `InvocationOperation` | Immutable definition containing a stable operation ID, request/response types, permitted invocation phases, and a handler factory. |
| `InvocationAPI.operations` | Return an `OperationClient` bound to the current participant and activation generation. Available to the goal and lifecycle/phase callbacks. |
| `OperationClient.request(operation_id, request)` | Synchronously execute a registered operation after core checks. Caller identity comes from the runtime, not from the request. |
| `OperationHandler.handle(request, api)` | Handle one request using a fresh restricted `OperationAPI`; return the declared response type. |
| `OperationHandler.close(api)` | Mandatory, once-per-invocation finalization, including invocations that never enter `achieve`. |
| `OperationAPI` | Expose runtime-derived caller metadata, dispatch restricted to the operation's registered phases, and framework-failure reporting. It is valid only for the current handle/close window. |

The goal registers immutable definitions during setup. Core constructs fresh handler
instances before `before_goal`. Factories initialize invocation-local bookkeeping;
they do not execute providers or retain setup/plugin APIs. If construction partly
fails, close every handler already created and preserve the primary failure.

Each service operation dispatches through the existing dispatcher and execution
endpoint. The helper stores IDs, descriptors, codecs, and invocation bookkeeping;
it never obtains a live plugin implementation. The restricted bridge can dispatch
only its declared phases to selected participants. It does not grant arbitrary
`GoalAPI` dispatch to plugins or revive removed edit-capability APIs.

Core validates operation registration, request/response types, owner thread,
activation generation, permitted phase, target selection, and invocation lifetime.
Capability compatibility and service grants remain in the optional handler.

A client captured in callback generation N cannot be used in generation N+1, even
if the same runtime API object is active again. A typed service handle inherits this
restriction. Providers obtain a fresh client in each callback. Repeated application
invocations share setup definitions but never handlers, scopes, or active handles.

### Call chains, attribution, and failures

Maintain an invocation-owned participant stack. Validate readiness, access, thread,
lifetime, lock rules, and cycles before activating a target. For A → B → C, each
provider receives its own API. Ancestor activations and held resources remain intact
while descendants execute; descendant deactivation releases only descendant locks.

Reject self-calls and calls to any active ancestor with a typed cycle error naming
the path. Set maximum call depth to 32. A single top-level request may contain
sequential nested calls; this does not introduce transport pipelining or concurrent
provider execution.

Declared domain errors are translated inside the provider callback into structured
service errors. They remain recoverable and do not create framework diagnostics.
Unexpected exceptions or invalid provider replies record the originating provider,
phase, and full call chain exactly once. Dispatch and hook runners preserve that
origin as the error passes through callers; they must not relabel C's failure as B's
or A's callback failure.

Core owns an invocation-wide framework-failure latch. Catching a request error,
returning a successful goal result, or transforming a result in `after_goal` cannot
erase it. After ordinary hooks and mandatory cleanup, a latched failure forces
framework status and exit 70 while retaining an existing result value, including the
real child outcome. Use the direct `GoalResult` constructor when preserving a value;
the current `framework_failed()` helper has no value parameter.

Expected request errors such as unavailable providers, rejected domain work, access
denial, cycle detection, and invalid caller input do not themselves latch framework
failure. Invalid provider output and internal routing defects do. `SystemExit`,
`KeyboardInterrupt`, and other termination exceptions propagate after mandatory
cleanup. Preserve the first termination exception over ordinary errors, and the
first ordinary failure over later ordinary cleanup failures; report secondary errors.

### Lock ordering across participants

Extend lock coordination to consult the complete active operation stack:

- Reject a service dispatch when any ancestor holds a state transaction.
- If an ancestor holds external-resource leases, descendants may read state and
  perform short transactions in their own namespaces, but may not acquire any
  additional external lease, including the same lease under a new participant.
- With no ancestor lease, a descendant may acquire leases under the existing
  sorted acquisition and finite-timeout rules. Its own descendants then inherit
  the restriction while those leases remain held.
- Do not transfer lease ownership, silently reacquire caller locks, or release
  ancestor resources when a descendant callback ends.

This permits sleep to retain `eclab-sleep:docker` while the registry commits through
its own state API, while preventing cross-participant lock inversion. Keep the
existing transaction, atomic-write, and leaked-lock cleanup guarantees.

## 4. Optional packages, registration, and readiness

Add three typed distributions, initially `0.1.0`, each shipping `py.typed`:

| Distribution | Owns | Dependencies |
| --- | --- | --- |
| `engulf-services-api` | Capability/method descriptors, codecs, immutable requests/replies, errors, participant interfaces, and typed client facades including `services(api)`. | `engulf-api` |
| `engulf-services` | Managed operation handler, directory, local routing, resource scopes, Python transport client, protocol, proxies, and integration helpers. | `engulf-api`, `engulf-services-api`; optional wrapper extra adds wrapper-api. |
| `engulf-plugin-services` | Selectable wrapper broker adapter returning immutable transport configuration. | `engulf-api`, `engulf-services-api`, `engulf-executable-wrapper-api` |

Neither core nor wrapper-api imports service packages. Provider and consumer wheels
depend on API packages, not service runtime implementations. A capability API can
belong to a goal, application, or third party and contains no provider implementation.
The Python child's installation closure includes services, services-api, dependency-
free engulf-api, and its capability API; it does not require `engulf` or the wrapper.

Keep service API, client, and local routing imports portable. Load POSIX modules only
when opening transport. Wrapper imports live in
`engulf_services.executable_wrapper`. Unsupported Windows transport raises
`UnsupportedTransportError`; local managed services remain usable on Windows.

`ServiceProviderParticipant` and `ServiceBrokerParticipant` are independent API
mixins, combined with the relevant goal plugin base. Phase adapters are module-level
forwarders. Plugins implementing neither remain valid and contribute nothing to
service registration. The broker's wrapper catalog ID is
`org.engulf.services.broker`; no new discovery catalog or wildcard goal adapter is
introduced. Its module imports no runtime helper and allocates no transport.

The base goal factory installs services integration. For a wrapper, the generic
`execution_support` helper also installs the managed operation definition in setup.
Local services work whether or not the broker is selected. Broker absence disables
only child transport. Zero broker contributions means no transport, one enables it,
and more than one is a setup error. The application can require the broker through
`required_plugin_ids` or `edition(require_plugins=...)`. Installing a wheel alone
does not retrofit a goal; editions retain the base factory.

### Setup and directory

The goal owns immutable `ServicesConfiguration`: accepted capability descriptors,
provider defaults, explicit required services, local participant access, child
grants, permitted broker IDs, and resource upper bounds. Child grants are explicit;
the default grants no child access. Broker policy can lower limits but cannot expand
application grants. `permitted_broker_ids` defaults to
`("org.engulf.services.broker",)`.

Use broadcast setup phases `org.engulf.services.configure` and
`org.engulf.services.register`, constructed with keyword arguments in preprocessing
order. Provider registration runs whenever local services are installed, independently
of transport configuration. Validate all contributions after dispatch completes.
Derive provider IDs from `AttributedContribution.plugin_id`, never declarations.

Freeze a directory containing only immutable descriptions and attributed IDs. Setup
does not allocate provider resources, store callbacks, discover additional plugins,
or retain registration APIs. Setup registration does not mean the provider is ready
to execute.

Distinguish selected, registered, and ready. Ordinary service requests require the
target to have successfully completed `before_goal`. Operation-specific preparation
can impose a later readiness condition. An image provider whose request map is
prepared in `prepare_call` must not serve offers before that preparation completes;
return a typed `ProviderNotReady` error. Never run its lifecycle early to satisfy a
lookup. Preserve packaging dependencies for initialization and preparation ordering.

Readiness remains available through ordinary after hooks until the corresponding
service scope closes. Providers keep scoped service resources valid for that
lifetime. Existing phase rules still apply: an analyzer cannot use a service call
to perform work forbidden by its side-effect-free contract.

### Capability compatibility, selection, and access

`CapabilityKey` is `(capability_id, api_major)`. The major is an exact positive
integer, not `bool`. Reuse `validate_global_identifier` for lowercase dot-qualified
capability IDs and full wire method IDs. A provider can advertise several majors;
duplicate provider/key declarations fail setup.

The canonical descriptor defines required methods, optional methods, explicit
request/result codec identities, and declared error schemas. Validate declarations
against the application's accepted descriptors. Shared method descriptions and the
required method set must agree; compatible optional subsets are allowed. Missing
required methods or conflicting shared methods fail setup. An absent optional
method returns `unsupported_method`.

The API-only facade uses `api.operations`, never a context-published runtime session:

```text
services(api).providers(capability) -> immutable descriptions sorted by plugin_id
services(api).require(capability, provider_id=None) -> typed provider handle
provider_handle.<method>(request) -> decoded result or typed service error
```

Resolve an explicit compatible, permitted provider first, otherwise the configured
default, otherwise the sole available provider. Zero means `missing_provider`;
several without a default means `ambiguous_provider`. Generic plugin priority never
selects a service. Validate defaults and explicit required services at setup; an
invalid default has no fallback. Ordinary ambiguity is a lookup error, not a setup
failure. Availability for execution additionally requires readiness.

Local requests are checked against application configuration and the current
participant's access. Child directories expose only granted capability/major/provider
triples and their advertised methods. Revalidate launch requirements after filtering;
omit defaults whose providers are absent rather than inventing replacements. A
request outside the grant returns `not_granted` without revealing other metadata.
Method-level sub-grants are outside v1.

A provider serving a child can call its own permitted dependencies. That does not
grant the child direct access to those dependencies. Caller identity for the nested
request is the provider; resource lifetime still follows the initiating child scope.

`org.engulf.services.call` addresses exactly one established provider through a
preprocessing invocation phase. Its immutable event carries a validated request
and opaque resource-scope identity. One `ServiceReply` is required; `None`, multiple
contributions, and malformed output are contract failures. Capability adapters decode
input, invoke owned implementation logic, encode output, and translate declared
errors inside the owner's activation. Wire codec names never trigger imports.

## 5. Lifetimes, dependency ordering, and cleanup

The managed facility spans `before_goal`, goal execution and wrapper preparation,
`after_call`, `after_goal`, and mandatory finalization. Core closes every handler in
an invocation `finally`, before queued workspace destruction and API closure. This
runs when an outer hook handles the command, setup succeeded but `achieve` is skipped,
or a termination exception bypasses ordinary after hooks.

Separate two resource lifetimes:

| Resource scope | Created and used | Closed |
| --- | --- | --- |
| Invocation | Local requests from goal/plugin callbacks; available before the goal and through after hooks. | During core mandatory finalization. |
| Child | Requests originating from a launched child and its explicit proxies. | After transport revocation and before wrapper `after_call`. |

Nested requests inherit their initiating scope. Closing the child scope does not
disable later local calls or close invocation resources. A provider can own separate
resources in both scopes; an invocation resource cannot depend on a shorter-lived
child resource. Scope identities and caller identity come from trusted runtime
bookkeeping, not wire claims.

Record a provider as touched immediately before dispatch, including a first call
that partly fails. Maintain a caller → callee dependency graph per resource scope.
Reject an edge that would create a scope dependency cycle, even when the earlier
calls have already returned. This supplements active-stack cycle detection and makes
cleanup ordering well-defined.

For A → B, clean up A before B so A can finish using B. Use dependency order, with
stable plugin-ID ordering for unrelated providers. This replaces v2's reverse
first-use traversal. During close, allow calls only along already established
dependencies in the same scope; do not add edges, admit new providers, reopen closed
resources, or resurrect another scope. Dependencies remain available until their
consumers finish closing.

Close providers individually through `org.engulf.services.close`, a postprocessing
phase with ordinary error propagation. The provider mixin supplies an idempotent
no-op default. Catch `BaseException` around each close dispatch and attempt every
touched provider. Do not rely on `isolate_failures=True` to collect failures or
continue after termination exceptions. Report secondary failures and always invalidate
scope/client/dispatch handles, even if every cleanup callback fails. Repeated close
does not invoke providers twice.

Partial acquisition belongs in the provider's current callback:
`except BaseException: release_partial_work(); raise`. A later cleanup callback
reacquires its own finite leases subject to the stack rules. Never retain active
APIs, loggers, transactions, or lease contexts between callbacks. Service cleanup is
not a deferred commit mechanism and does not guarantee rollback of completed writes.

Capabilities that create persistent external resources define ownership tokens,
managed recovery records, and idempotent recovery separately. No cleanup notification
is promised after process death or SIGKILL. A lost response can follow a completed
side effect; the protocol never retries it automatically.

## 6. Engulf-clab migrations

### Lab registry capability

Keep provider ID `engulf_clab.lab_registry`, its existing user-state namespace,
`labs.json` format/version, and record identity. Replace the shared operational
registry object with a capability owned by the registry API package:

```text
records() -> immutable current persisted records
commit_observations(records) -> acknowledgement after the transaction/write completes
```

Each call reads or writes with the registry provider's fresh API. `records()` reads
current persistent inventory instead of an invocation-start snapshot.
`commit_observations` validates the entire request, opens a transaction, rereads,
merges, and writes before acknowledging. Reuse the existing storage implementation's
locking and atomic-write protections. Do not acknowledge only a queued update.

Preserve the `(name, canonical directory)` key, known topology when an update lacks
one, and `ever_deployed` history. Replace image IDs only with a complete observation;
an incomplete measurement must not erase preserved ownership data. Codecs represent
absolute paths and sets explicitly and return immutable `LabRecord` values, never
state handles or mutable storage objects.

A missing inventory file means a complete empty inventory. Corrupt or unreadable
inventory means explicitly unavailable, never authoritative empty. A failed write
returns a declared persistence error. Remove the degraded `persistent=False` behavior
that can accept and later discard writes. No service promises an atomic transaction
covering both inventory writes and Docker mutations.

Automatic successful deploy/redeploy observation remains best effort. The registry
uses its own active API and storage logic for that work, without calling itself
through services. Expected tracking failure produces a warning and preserves the
wrapped command result. Unexpected implementation defects follow framework failure
rules. The deferred pending-update queue is no longer the consumer write path.

### Consumption

Keep consumption in `before_goal` and replace context lookup with its typed registry
client. On every two-second reporting iteration, read fresh inventory, make the
existing read-only Docker/filesystem observations, and commit complete observations.
A declared commit error is a warning; measurement can continue.

Preserve image deduplication, state classification, retained-image accounting, and
N/A semantics. Registry unavailability must be explicit. A degraded Docker-only view
can be shown, but values whose completeness depends on registry history remain N/A;
it must not silently treat unavailable history as empty. No Docker mutation is added.

### Sleep

Keep sleep in `before_goal` and retain `eclab-sleep:docker` across discovery,
planning, registry commit, and Docker deletion. Read authoritative inventory, build
the complete preservation/deletion plan, and commit its preservation records through
the registry service. Start deletion only after a successful persistence
acknowledgement. Registry unavailability or commit failure means zero deletions.

After acknowledgement, preserve independent container/image deletion attempts and
existing partial-failure reporting, stopped/all selection, outside-owner image
preservation, and workspace preservation. Do not introduce broad pruning or forced
image deletion. The transaction ends before Docker deletion; this is a persistence
barrier, not an atomic database-and-Docker transaction.

Add an integration test using the real registry provider and managed invocation
boundary. At the first fake Docker deletion, inspect persisted inventory through an
independent read and prove the preservation records already exist. The current test
that orders fake `upsert` and deletion events cannot verify this guarantee.

### Image offer capability

Remove the wrapper path's `IMAGE_PROVIDER_CONTEXT` registry of live callables.
Wrapper provider adapters expose an image-offer capability through
`ServiceProviderParticipant`. Its result is an explicit immutable union:
`Offer`, `Reject`, or `NoOpinion`. `NoOpinion` is a successful value, not a missing
service-phase contribution.

In image-build's `prepare_call`, enumerate compatible provider descriptions, issue
managed offer requests, and supply the collected responses to the image core's
existing `provider_lookup` seam. The owner adapter receives its own fresh API and
accesses its own prepared state. No direct call to a context-registered foreign
implementation remains in the wrapper workflow.

Keep authority ranking, terminal rejection, domain preference, deterministic ties,
dependency graph resolution, conflict handling, default pull, candidate fallback,
and failed-build exclusion in Docker image core. Generic service enumeration sorts
by plugin ID. Image preference/priority is explicit capability metadata consumed by
the image resolver; the service broker does not select the winning recipe.
Trying another declared image candidate is domain behavior, not an RPC retry.

Retain all real preparation dependencies. Archive, vrnetlab, and other providers
prepare their request maps before image-build requests offers. Setup declarations
do not make these maps ready. Clear invocation/scoped provider state through its
own failure and cleanup paths, and return `ProviderNotReady` before preparation.

Use the active wrapper adapter's attributed plugin ID for wrapper calls. Preserve
the separate DockerImageGoal catalog adapters and its existing
`PROVIDE_IMAGE_PHASE`; unrelated goal identities are not interchangeable.

Define explicit codecs for requirement parameters and each supported recipe kind,
including paths, authority, rejection, and fallback metadata. Applications install
the recipe codec bindings they accept; a wire recipe kind never imports code.
Provider callbacks run synchronously on the invocation owner thread. Existing build
workers receive resolved data and do not receive APIs or dispatch service calls.

### Shared context and compatibility

Remove operational registry/provider objects and their context declarations after
all direct consumers migrate. Keep legitimate immutable data sharing, image graph
contributions, schema data, and unrelated topology editing contracts. This plan does
not convert every context value into a service.

Migrate each producer/consumer set coherently. Do not provide a runtime fallback to
raw provider callbacks or deferred registry writes: it would restore the behavior
being removed. Mixed incompatible installations fail clearly. Preserve state file
compatibility, plugin IDs, and existing packaging order edges; dependency floor
changes accompany a separately authorized release.

## 7. Executable-wrapper integration

Add optional `execution_support=None` with service-independent contracts in
wrapper-api. They are local-execution contracts, not transportable goal events.

| Interface | Contract |
| --- | --- |
| `ExecutionSupport.setup(GoalSetupAPI)` | Run after `_COLLECT_HELP` and before setup completes; register immutable configuration and managed operations. |
| `ExecutionSupport.environment_removals` | Immutable helper-owned names scrubbed from every launch, including disabled/help launches. These are fixed after setup but unknown to a bootstrap process before inspection. |
| `ExecutionSupport.open(PreparedCallEvent, GoalAPI)` | Open a child execution session after veto resolution and before preparation, or return `None` when transport is disabled. Unwind partial acquisition on `BaseException`. |
| `ExecutionSession.launch` | Immutable environment additions and explicit `pass_fds`. |
| `ExecutionSession.spawned(pid)` | Close redundant parent copies of child endpoints and record launch; never receive `Popen` or a reaping handle. |
| `ExecutionSession.interests()` | Return descriptor readiness interests for the wrapper-owned selector. |
| `ExecutionSession.step(ready)` | Perform bounded incremental I/O and at most one top-level provider dispatch; return immediately after it so the wrapper polls before writing the reply. Empty readiness still advances deadlines. |
| `ExecutionSession.stop(reason)` | Idempotently revoke transport and admit no new work; perform no provider callbacks. |
| `ExecutionSession.close(end)` | Idempotently close child-scoped provider resources through the managed facility, release descriptors, and report failures. Leave invocation services available. |

The end value distinguishes preparation failure, spawn failure, child exit,
infrastructure failure, and termination; it carries the actual outcome when one
exists. One optional support helper is sufficient. No helper registry or merge of
live plugin objects is introduced.

Preserve internal help/completion handling and all analyzers. Preemption opens no
child transport. A disabled session keeps ordinary blocking process waiting; local
managed services can still operate in hooks. For viable execution, open support
before preparation so transport-allocation failure occurs before preparers acquire
resources. Preserve reverse successful-preparer unwind and the original exception
on preparation failure; do not dispatch `after_call` for that path.

Narrow 127/126 translation to executable resolution and `Popen`. After successful
spawn, notification, selector, provider, and cleanup failures are framework failures,
not `SPAWN_FAILED`. The wrapper owns the same `Popen` for all polling and reaping;
service code never calls `waitpid` or owns process-group policy.

Poll child state before and after each bounded pump step, with selector waits capped
at 100 ms. Pending replies request an immediate iteration/write readiness, not a
full poll-delay sleep. On observed child exit, stop transport, discard unstarted
requests and unsent replies, finish reaping, restore handlers, and close the child
scope before `after_call`. A callback already running returns cooperatively; poll
before sending its reply. Invocation-scope services remain usable in after hooks.

Keep shell-free execution, inherited standard streams/cwd/controlling terminal, and
the wrapper's process group. Retain wrapper-PID signal forwarding. The existing
wait-only `KeyboardInterrupt` behavior may forward SIGINT and report child status;
do not wrap provider dispatch in that special handler.

An ordinary post-spawn infrastructure/provider failure latches framework failure,
revokes transport, and continues normal waiting with signal forwarding. It does not
automatically kill the child. A child that ignores channel closure may keep running.
Normal postprocessing receives its real outcome; core ultimately enforces exit 70.

A termination exception from provider/helper execution triggers exceptional direct-
child cleanup: SIGTERM, wait up to one second, SIGKILL if necessary, and reap using
`Popen`, then propagate the first termination exception after mandatory cleanup.
Do not signal the shared process group or recursively kill descendants. An
uninterruptible kernel wait remains an OS limit on reaping.

Infrastructure diagnostics name the configured broker and stage through managed
goal diagnostics. Do not forge a plugin callback or replace provider-origin records.
Update the wrapper README's environment and outcome guarantees with this integration.

## 8. Transport, inheritance, and proxies

Use private `AF_UNIX` stream socket pairs. Parent endpoints are nonblocking and
non-inheritable; only the intended child endpoint is included in `pass_fds`. Close
the parent's redundant endpoint immediately after spawn or on launch failure. There
is no filesystem listener, public socket, PID-based authorization, or global broker.

`ENGULF_SERVICES_ENDPOINT` holds a small versioned descriptor containing the fd and
expected `st_dev`/`st_ino` as decimal strings. Before traffic, validate fd range,
`fstat`, socket type/family, connected state, and identity; mark the accepted fd
non-inheritable. Reject stale descriptors without closing unrelated reused fds.
Unsupported identity verification fails explicitly. This is descriptor hygiene,
not authentication against code with the same OS authority.

Build launch environments from fresh `dict(os.environ)`, remove helper-owned names,
then add the intended endpoint. Do not pass normalized invocation-only environment
overlays to the executable. Validate reserved/duplicate launch metadata before
preparation. Apply removal policy when transport is disabled and for help launches.

Pass removal metadata through private completion `describe` output into generated
Bash/Zsh/Fish normalization/completion subprocess commands. Bootstrap inspection
cannot know helper-specific names in advance; it uses `close_fds=True`, no service
session, and endpoint validation. Do not mutate the interactive shell environment.

Absent endpoints raise `ServicesUnavailable`; malformed endpoints raise a distinct
validation error. Neither triggers discovery. An optional client can continue
without services when no session was established, but must not silently recover
from losing an established request channel.

Explicit parent proxies give descendants fresh pairs and subsets of upstream grants.
Never share one upstream fd among processes. Each connection has one reader and one
serialized writer. Proxies remap request IDs only on their upstream leg and restore
each downstream ID on its response. Serialize parent and descendant upstream calls,
filter directories/defaults, apply bounded fair admission, and decrement remaining
deadlines. A proxy I/O thread handles encoded remote traffic only; it never dispatches
local providers off the invocation thread.

Nested Engulf applications keep separate local directories. Upstream use requires
an explicit separate client/proxy and does not merge providers. Launch helpers scrub
endpoints from unrelated subprocesses and install only the newly granted endpoint.

Direct-child exit revokes all child/descendant access, not the outer invocation's
local facility. Peer/proxy loss closes its downstream sessions. Discard replies for
disappeared peers and never retry an upstream call that may already have executed.
Child close and core finalization coordinate scope state so providers are not closed
twice for the same scope.

## 9. Protocol version 1 and local equivalence

Write the normative protocol and language-neutral conformance vectors in
`engulf-services/protocol/` before transport implementation. Apply the same service
envelope validation and capability codecs to local and remote requests. Local nested
calls do not add wire pipelining.

### Framing and handshake

Frames contain a four-byte unsigned network-order length followed by exactly that
many UTF-8 JSON bytes. Zero/excessive length, truncated EOF, invalid UTF-8/JSON,
duplicate keys, and invalid top-level shape close the connection. Envelopes are
objects with explicit required/optional fields; reject unknown envelope fields.

The first frame is `hello`, listing supported versions and the client receive limit.
Its bootstrap payload limit is 4 KiB. The minimum legal receive limit is 4 KiB.
Select v1 and reply `ready` with an opaque session ID, effective limits, sorted
granted provider/method directory, and filtered defaults. `ready` must fit the
negotiated frame bound; reject an unadvertisable directory. Use the lower peer limit
in both directions and a five-second handshake deadline. Nothing in handshake
imports or activates plugins.

Calls carry `version: 1`, `type: "call"`, a positive connection-scoped integer `id`,
capability ID, API major, explicit provider ID, qualified method ID, and `input`.
Optional `remaining_timeout_ms` is a positive integer at most 86,400,000; absence
means 30,000. Replies echo version/ID and contain exactly one `result` or `error`.
The server revalidates the exact grant and advertised method.

IDs strictly increase and never repeat. Keep only the last accepted/current ID, not
an unbounded history. There is one outstanding request per connection. Cap waiting
callers at 16 per client with deadline-aware admission. Proxies serialize upstream
work. Notifications, unsolicited responses, remote callbacks, and cancellation
messages are not supported.

After handshake, a valid new correlation ID with invalid request fields receives a
correlated error and can leave the connection usable. Missing/repeated/invalid IDs,
incorrect ordering, unsupported message types, and mismatched response IDs/shapes
close the session.

### Values, codecs, and errors

Allow null, exact booleans, Unicode scalar strings, finite numbers, arrays, and
string-keyed objects. Reject NaN/infinity, lone surrogates, duplicate keys, cycles,
and implicit conversion of arbitrary Python values. Integer tokens are restricted
to `-(2**53 - 1)` through `2**53 - 1`. Decimal/exponent forms use finite binary64.
Integer `-0` normalizes to zero; floating signed zero is preserved where permitted.
Thus `1` is integer, `1.0` and `1e0` are floating forms, and `1e400` is invalid.
Go uses `json.Number` and explicit validation instead of default float coercion.

Capability codecs explicitly represent paths, sets, bytes, decimals, large integers,
and domain objects. Recursively freeze decoded mappings/sequences before provider
events. Local calls perform the complete envelope encode/validate/decode round trip,
including request/result codecs and limits, so mutable aliases and implementation
identity do not become observable. Codec identifiers in directories are data only;
trusted installed capability packages supply executable bindings.

Errors contain a stable kind/code, safe message, optional validated JSON data, and
validated capability/provider/method attribution when available. Shared error cases
include invalid request, missing/ambiguous/not-ready provider, access denial,
unsupported method, call cycle/depth, provider failure, broker failure, closure,
resource admission failure, and deadline expiry. Domain errors use capability-owned
codes. Connection loss and local validation also have typed client exceptions.
Never send unexpected tracebacks, arbitrary exception text, or Python objects over
the wire; retain full origin and chain in managed diagnostics.

### Limits, deadlines, and responsiveness

| Limit | Default and behavior |
| --- | --- |
| Frame payload | 1 MiB; check before allocating payload and incrementally during encoding. |
| JSON depth / value nodes | 64 levels / 65,536 nodes, including local requests and replies. |
| Proxy downstream connections | 16 maximum; the wrapper has one direct-child connection. |
| Outstanding work | One request per connection, one upstream request per proxy, one top-level provider request in the wrapper; local call chains execute synchronously within it. |
| Buffered frames | One bounded input and one bounded output per connection; no unbounded decoded/request queue. |
| Aggregate transport/parser storage | 32 MiB per broker/proxy, including conservatively charged decoded values; admission stops before exceeding it. Trusted provider/native codec allocations are outside this accounting. |
| Work per pump turn | At most 64 KiB read and 64 KiB written in aggregate, round-robin admission, at most one top-level provider request. |
| Handshake / incomplete frame / blocked output | 5 / 30 / 30 seconds from operation start, without resetting deadlines for tiny progress. |
| Local call depth / waiting remote callers | 32 / 16 per client. |

Reserve bounded error-response capacity before dispatch. Stop reading while a reply
is unfinished. Charge decoded storage before admission; do not assume sixteen
maximum-sized request/reply pairs plus parser objects all fit the aggregate cap.
Reject or defer admission at capacity without allocating past it. A stalled
downstream reader must not block unrelated proxy peers.

Remote deadlines cover queueing, encoding, send, provider wait, and decoding.
Proxies subtract their own elapsed time and reject expired work before forwarding.
The server checks the remaining budget before dispatch and cooperatively after the
callback; elapsed time does not preempt provider execution. Before any request bytes
are sent, timeout means no provider execution. Once transmission begins, expiry
closes that client session and reports outcome unknown. Never reconnect, retry,
reuse late responses, or imply that timeout cancels side effects.

Local deadlines are cooperative before/after checks. Providers use finite lease and
external-I/O waits and document operation duration; a synchronous call chain can
delay polling beyond a transport turn's byte budget. Forced provider deadlines need
another execution model and are outside v1.

Normal EOF/reset and malformed peer frames close the affected channel without
automatically latching framework failure. Internal selector/descriptor/router
defects and provider contract failures latch it. Distinguish these cases instead
of classifying every `OSError` as broker failure.

## 10. Implementation sequence and acceptance tests

Implement local services and the actual plugin migrations before transport. Each
stage is independently reviewable and preserves applications without integration.

| Stage | Deliverable | Acceptance gate |
| --- | --- | --- |
| 0. Baseline repairs | Narrow wrapper spawn-error handling and document outcome mapping; repair CI example dependency/plugin coverage; correct stale `completed_plugin_ids` documentation. | Existing 127/126/signal behavior passes; post-spawn `OSError` retains `process_started=True`; both encryption example packages install together. |
| 1. Generic managed operations | API definitions, setup registration, invocation-owned handlers, restricted dispatch, activation/thread guards, failure origin/latch, acyclic chains, lock-stack checks, mandatory close. | Core/API tests cover early outer-hook completion, nested ownership, retained handles, cycles, locks, termination, and repeated invocations on supported platforms. |
| 2. Portable services | Three package skeletons, API-only facade, registration, canonical descriptors, readiness, routing, scopes, dependency cleanup, protocol specification/vectors. | Two-provider local example; no broker required, no unselected imports, full codec equivalence, correct errors and final framework status. |
| 3. Registry consumers | Real registry service, consumption refresh/commit, and sleep persistence barrier, with coherent package dependencies. | Real persisted state is visible before the first deletion; unavailable/read/write failure performs zero deletions; polling sees another invocation's committed changes. |
| 4. Image providers | Managed wrapper offers, explicit no-opinion/rejection values, codecs, readiness, domain lookup integration, removal of live-provider context use. | Existing authority, graph, conflict, pull, fallback, preparation, and parallel-build behavior pass with provider-owned API attribution. |
| 5. Child transport and interoperability | Generic wrapper seam, private pairs, incremental pump, endpoint/env handling, Python client, explicit proxies, Go reference client/example. | Real Python/Go traffic, grant restriction, deadlines/backpressure, signals/PTY, outcome preservation, descendant revocation, and invocation services after child close. |
| 6. Packaging and documentation | Owning READMEs, examples, root commands, build/type/docs checks, CI, and coherent dependency validation. | All existing/new suites pass; eight public distributions build wheels/sdists and pass Twine; clean installations run both examples and direct consumer tests. |

Use a small side-effect-free capability with distinguishable providers for
`examples/services-python/` and `examples/services-go/`. Reuse the script-free
core/factory/edition pattern without coupling encryption to services. Add a separate
resource-owning test provider. The Go client/example and shared vectors demonstrate
interoperability; this plan does not authorize publishing a separate Go SDK.

Required deterministic scenarios:

- **Registration and access:** selected/registered/ready distinctions, broadcast
  attribution, absent/duplicate/required brokers, editions using the same factory,
  invalid defaults, explicit ambiguity, several majors, compatible optional methods,
  rejected incompatible descriptors, no lookup-driven activation, and no imports of
  unselected providers. New applications observe fresh installed metadata.
- **Activation and chains:** A → B → C receives distinct owner APIs, namespaces,
  loggers, and fresh capabilities; ancestor resources survive descendant return;
  old clients fail on a later activation; wrong-thread calls fail before dispatch;
  self/active-stack/scope-graph cycles and depth overflow are rejected.
- **Locks:** calls from an active transaction fail; caller lease plus callee state
  commit succeeds; descendant external acquisition under an ancestor lease fails;
  partial failures and deactivation release only the correct participant's locks.
- **Failures and lifetime:** C's defect is reported as C through B/A and outer hooks;
  caught errors and successful after hooks cannot erase framework 70; early
  `before_goal` completion and termination still finalize; child close preserves
  invocation services; repeated invocations share no active scope or resources.
- **Dependency cleanup:** A closes before dependency B; cleanup can use established
  dependencies but cannot add/reopen them; all providers are attempted after failures;
  first termination/ordinary errors survive secondary failures; no double close.
- **Registry workflows:** complete empty versus unavailable inventory, malformed
  storage, transaction/write failure, merge/topology/history/image semantics,
  concurrent commit visibility, degraded consumption N/A, and the real sleep
  persistence barrier. Test multiple calls in one invocation and no delayed writes.
- **Image workflows:** offer/no-opinion/rejection, terminal authority masks,
  deterministic domain priorities, DAG cycles/conflicts, default pull, failed
  candidate fallback, preparation readiness, separate goal adapter identities,
  supported recipe codecs, and workers receiving data only.
- **Protocol/resources:** shared local/Python/Go vectors, invalid Unicode/numbers,
  duplicate keys, depth/nodes/bytes, partial frames, unknown fields, request/response
  ID errors, no pipelining, oversized directories/results, queue admission, deadline
  before/after send, stalled writes, aggregate accounting, and no retry after loss.
- **Processes:** direct-child exit during a frame/callback, queued work discarded,
  failure followed by child exit zero, post-spawn notification failure, stale/reused
  fd safety, endpoint closure/inheritance, proxy parent loss and narrowed grants,
  nested application separation, real child environment, completion scrubbing,
  signals/process groups, and an actual PTY/controlling-terminal test.
- **Portability:** API/client imports without runtime/wrapper packages, local services
  on Windows, explicit unsupported transport, and a real Go toolchain in Linux CI.

Use pipes, barriers, and readiness notifications rather than timing-only sleeps.
Tests must exercise the real dispatcher and persistence boundary where the guarantee
depends on them, not merely mirror a fake method-call order.

## 11. Documentation, validation, and version policy

Update core/API documentation for managed operations, activation lifetime, nested
failure attribution, stack lock rules, and mandatory finalization. Update wrapper
API/runtime docs for execution support, actual environment inheritance, outcome
precedence, child-scope cleanup, completion, and signals. Update registry/consumption/
sleep/image owning docs and migration tests in the sibling repository.

Extend Makefile package mappings, install/build/check targets, mypy paths, editable
installation commands, documentation export coverage, and CI for the three new
distributions. Include both new top-level directories in lint/format targets; keep
plugin/example coverage. Correct the existing encryption core installation omission.
Update root package tables/counts from five to eight and coordinate setup insertion
and build-count references with [goal-owned-cli-parser.md](../../goal-owned-cli-parser.md).

Run the workspace checks required by AGENTS.md at implementation completion:

```console
python3.14 -m venv --upgrade-deps .venv
.venv/bin/python -m pip install --group dev
PYTHONPATH=engulf-api/src .venv/bin/python -m unittest discover -s engulf-api/tests -v
PYTHONPATH=engulf-api/src:engulf-executable-wrapper-api/src .venv/bin/python -m unittest discover -s engulf-executable-wrapper-api/tests -v
PYTHONPATH=engulf-api/src:engulf/src .venv/bin/python -m unittest discover -s engulf/tests -v
PYTHONPATH=engulf-api/src:engulf/src:engulf-executable-wrapper-api/src:engulf-executable-wrapper/src .venv/bin/python -m unittest discover -s engulf-executable-wrapper/tests -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ruff check engulf-api engulf engulf-executable-wrapper-api engulf-executable-wrapper plugins examples
.venv/bin/python -m ruff format --check engulf-api engulf engulf-executable-wrapper-api engulf-executable-wrapper plugins examples
.venv/bin/python -m mypy
```

Also run every new package suite, shared Go vectors/interoperability, and the directly
affected sibling registry, consumption, sleep, and image suites. Read and follow each
owning README and repository's test instructions before implementation. After package
metadata changes, build the coherent wheel/sdist set and run Twine checks through
the workspace build tooling. Do not hand-edit archives.

Existing package versions, `PLUGIN_API_MAJOR`, and the wrapper goal API major remain
unchanged under current workspace instructions. New distributions begin at `0.1.0`;
services API major and wire version begin at 1. Before a separately authorized
release, verify hosted artifacts and raise dependency floors coherently for the new
core/wrapper interfaces and migrated consumers. Broad existing dependency ranges do
not guarantee a compatible mixed installation.

## 12. Disposition of earlier decisions

| Earlier finding or decision | V3 disposition |
| --- | --- |
| B1/R1/R3: dispatch boundary and goal integration | Sections 3–4 add a generic registered-operation bridge; every provider still goes through managed dispatch/endpoints. No live implementation registry. |
| B2/S7: package boundaries | Section 4 retains three optional distributions and API-only plugin dependencies; core adds generic lifecycle machinery only. |
| B3/B4/R4: process ownership and errors | Sections 7–8 preserve wrapper-owned reaping and repair spawn classification; real outcomes survive framework failure. |
| B5/R5/R6: protocol, codecs, bounds | Sections 8–9 retain serial transport/proxies and make bootstrap, numeric, deadline, caller, and node bounds explicit. |
| B6/R2: failures and cleanup | Sections 3 and 5 move the latch/finalization guarantee into core and preserve nested origin and termination precedence. |
| S1/S2: environment and endpoint lifetime | Sections 7–8 retain explicit fd identity/inheritance and fresh process-environment overlays with launch/completion scrubbing. |
| S3/S4: responsiveness and resource ownership | Sections 5 and 7–9 distinguish invocation/child lifetimes, cooperative callbacks, revocation, dependency cleanup, and external recovery. |
| S5: provider ambiguity/defaults | Section 4 retains explicit defaults and setup validation; image offer ranking stays in its domain resolver. |
| S6: caller/reentrancy restrictions | Replaced by the agreed plugin-call support and synchronous acyclic chains, with activation, thread, readiness, depth, and lock guards. |
| S8/S10: authority and versions | Sections 1 and 11 preserve existing privilege policy and no-bump instructions; no publishing authorization is implied. |
| R10/R11/R12: identifiers, nested apps, compatibility | Sections 4 and 8 retain canonical identifiers, separate nested directories, and required/optional method compatibility. |
| S9/R7/R8/R13: evidence and acceptance | Sections 2 and 10–11 tie implementation to inspected source, real plugin migrations, and package/process/interoperability checks. |
| R9: historical plans | This file is the complete v3 successor saved beside v2; earlier plans and critiques are preserved. |
| Registry snapshot/deferred persistence | Section 6 replaces foreign operational context with owner-dispatched reads and acknowledged commits; sleep verifies actual persistence before deletion. |
| Image provider context bypass | Section 6 uses managed offer calls while preserving `PROVIDE_IMAGE_PHASE` for its existing goal and domain resolution policy. |

These dispositions describe the intended implementation. They do not claim that
the APIs, migrations, runtime behavior, or acceptance tests already exist.
