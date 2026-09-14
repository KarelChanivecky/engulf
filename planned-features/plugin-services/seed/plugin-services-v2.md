# Optional plugin services: implementation plan v2

Status: proposed implementation plan; implementation has not started.

This is the successor to [plugin-services.md](plugin-services.md), informed by the
[critique](plugin-services-critique.md), the
[synthesis](plugin-services-critique-synthesis.md), and the
[synthesis review](plugin-services-synthesis-review.md). Those documents remain
historical inputs. Where they disagree, the decisions below define this plan.
“v2” identifies the plan revision; the proposed service protocol is version 1.

Source baseline: `4bac606f1aeb3547ad64febfd1fd8068dcd994d4`. Source anchors below
refer to that commit. Public names introduced here are proposed names, not existing
APIs. This document plans implementation; it does not authorize publishing packages.

## 1. Outcome and scope

An application can expose selected active plugins as typed service providers to its
goal and, with explicit integration, to a child executable. A portable Python goal
and a wrapped Go executable will exercise the same capability with two interchangeable
providers. Provider selection, callback attribution, state, context, leases, and
diagnostics continue to use existing Engulf facilities.

Keep `engulf-api` and `engulf` free of service-specific changes. Add portable service
contracts and a service runtime, an optional executable-wrapper broker adapter, and
a service-independent execution-support interface in wrapper-api. All actual plugin
callbacks continue through `GoalAPI.dispatch()` and execution endpoints.

Version 1 deliberately supports synchronous calls from the goal and its launched
processes. It has one outstanding request per connection, explicit descendant
proxying, bounded transport buffers, and no automatic retry or reconnect. Plugin
callers, provider-to-provider calls, network listeners, asynchronous providers,
streaming RPC, cancellation, automatic plugin activation, and automatic discovery of
upstream services are outside this version.

The service broker coordinates trusted code with the application's OS authority.
It is not a privilege-separation broker. An endpoint grants access to provider
operations; grants constrain this protocol, not arbitrary communication or resource
access by participating code. Retain the existing goal privilege opt-in and plugin
elevation checks. This work adds no separate elevation gate or per-launch approval
flow. Applications deliberately configure which services they expose to a child.

## 2. Source findings that determine the design

| Evidence at the baseline | Consequence |
| --- | --- |
| [`GoalSetupAPI.dispatch`](../../../engulf-api/src/engulf_api/plugin_api.py#L125), lines 125–136, has an active ID snapshot but no targeted selection; [`AttributedContribution`](../../../engulf-api/src/engulf_api/goals.py#L218), lines 218–226, supplies provider identity. | Broadcast immutable setup declarations and validate attributed results. Do not extend core setup dispatch. |
| [`GoalAPI.dispatch`](../../../engulf-api/src/engulf_api/plugin_api.py#L143), lines 143–156; [`_PhaseDispatcher`](../../../engulf/src/engulf/_dispatch.py#L224), lines 224–265; [`_InProcessPluginEndpoint`](../../../engulf/src/engulf/_plugin_execution.py#L81), lines 81–87. | Route each established provider through a targeted invocation phase. Never retain a live plugin implementation in the helper. |
| [`edition()`](../../../engulf/src/engulf/application_definition.py#L106), lines 106–133, preserves `goal_factory`. | The base factory installs optional support; broker selection activates it. Installing a broker wheel alone cannot retrofit an unrelated goal. |
| [`_ActivationState`](../../../engulf/src/engulf/_capabilities.py#L88), lines 88–116, checks activation but not thread identity; activation precedes the attributed callback `try` in `_dispatch.py:226`. | Enforce service session thread affinity and reentrancy in the service runtime. Do not pump providers while a broker callback remains active. |
| [`Application._invoke`](../../../engulf/src/engulf/application.py#L798), lines 798–845, skips ordinary after hooks when a termination exception escapes; [`RuntimePluginAPI`](../../../engulf/src/engulf/plugin_api.py#L79), lines 79–91, releases callback locks. | Own session cleanup inside `achieve`; reacquire provider leases in cleanup callbacks. Outer hooks are insufficient. |
| [`PluginCallbackError`](../../../engulf-api/src/engulf_api/errors.py#L13), lines 13–20, has no completed-provider list; [`_dispatch.py`](../../../engulf/src/engulf/_dispatch.py#L230), lines 230–240, catches only `Exception` and hides isolated failures from its return. | Track touched providers explicitly and collect close failures through individual targeted dispatches. Do not rely on stale `completed_plugin_ids` examples. |
| [`ExecutableWrapperGoal.achieve`](../../../engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py#L375), lines 375–415, resolves vetoes before preparation; preparation tracks each successful plugin at lines 433–475. | Open transport after veto resolution and before preparation, inside a scoped guard. Preserve preparation's existing unwind path. |
| [`ExecutableWrapperGoal._execute`](../../../engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py#L837), lines 837–904, puts signal setup and waiting inside spawn-error handlers. | Fix the existing error boundary first. An `OSError` after successful spawn must never become `SPAWN_FAILED`. |
| [`goal.py`](../../../engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py#L851), lines 851–868, owns `Popen`, inherited process groups, and a special `KeyboardInterrupt` wait path. | The wrapper alone reaps the child; preserve signal behavior and distinguish provider termination exceptions. |
| [`normalize_invocation`](../../../engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py#L335), lines 335–344, overlays callback environment; `Popen` at line 854 inherits the process environment. | Build launch overlays from fresh `os.environ`, never from `Invocation.environment`. |
| [CI](../../../.github/workflows/ci.yml#L27), lines 27–34, installs the launcher with `--no-deps` without its core example package. | Repair an existing CI omission before using that example for service validation. An isolated launcher import reproduces `ModuleNotFoundError: engulf_encryption_example_core`. |

The broad spawn handler is an existing defect exposed by the proposed pump, not a
new service feature. The CI omission was also verified independently of services.
Neither requires changing service contracts to resolve it.

## 3. Package ownership and activation

Add three typed distributions, each starting at `0.1.0` and shipping `py.typed`:

| Distribution / directory | Owns | Required dependencies |
| --- | --- | --- |
| `engulf-services-api` / `engulf-services-api/` | Capability and method descriptors, codecs, immutable service events/replies/configuration, errors, provider and broker participant interfaces. | `engulf-api` |
| `engulf-services` / `engulf-services/` | Local sessions, directory validation, Python client, protocol implementation, POSIX transport, proxies, goal integration helpers. | `engulf-api`, `engulf-services-api`; optional `executable-wrapper` extra adds wrapper-api. |
| `engulf-plugin-services` / `plugins/engulf-plugin-services/` | The selectable executable-wrapper broker adapter and its immutable configuration contribution. | `engulf-api`, `engulf-services-api`, `engulf-executable-wrapper-api` |

Dependency arrows below mean “depends on”:

```text
engulf-services-api --------------------------> engulf-api
engulf-services -----------------------------> engulf-services-api
engulf-services -----------------------------> engulf-api
engulf-services[executable-wrapper] ----------> engulf-executable-wrapper-api
engulf-plugin-services ----------------------> engulf-services-api
engulf-plugin-services ----------------------> engulf-api
engulf-plugin-services ----------------------> engulf-executable-wrapper-api
provider wheel ------------------------------> its goal API + capability API
engulf-executable-wrapper --------------------> wrapper-api + engulf
```

There is no wrapper-api dependency on services-api, and no core dependency on a
service distribution. Provider wheels depend on API packages, not the service or
wrapper runtimes. A capability API may be owned by a goal, application, or third
party and depends on services-api. It contains no provider implementation.

Within `engulf-services`, keep `client`, local routing, and public imports portable.
Load POSIX modules only when opening transport. Keep wrapper-specific imports in
`engulf_services.executable_wrapper`; only applications using that module install
the extra. The Python child needs services plus its capability API, not `engulf`,
wrapper-api, or the broker plugin. A Windows transport entry point raises
`UnsupportedTransportError` without importing POSIX-only modules; local sessions
remain usable on Windows. The wrapper itself remains Linux-specific.

`ServiceProviderParticipant` and `ServiceBrokerParticipant` are separate API mixins,
neither a subclass of `Plugin`. A wrapper provider combines
`ExecutableWrapperPlugin` with `ServiceProviderParticipant`; another goal combines
its own plugin base with that participant. A normal plugin implementing neither
interface remains valid and contributes nothing to service phases.

The broker combines `ExecutableWrapperPlugin` with `ServiceBrokerParticipant` and
publishes ID `org.engulf.services.broker` under the existing wrapper goal catalog.
It returns configuration; it does not own sockets or run a provider dispatch loop.
Its entry-point module imports no runtime helper and does no machine inspection.
Other goals may publish their own broker adapters with distinct IDs; there is no
wildcard goal adapter or new discovery catalog.

For wrapper applications, the base factory always constructs
`ExecutableWrapperGoal(..., execution_support=WrapperServicesSupport(...))` when
editions should be able to enable services. The helper exists whether or not the
broker is selected. With zero broker contributions it is disabled; with one it is
enabled; more than one is a setup error. An application requiring child services
uses `required_plugin_ids` or `edition(require_plugins=...)` for the broker. An
edition may include providers without changing the factory.

Broker-free local routing is supported for Python goals through the same directory
and provider phases. Transport activation remains optional. Neither mode discovers
or activates additional plugins during service lookup. Do not add plugin dependency
edges merely to express service preference: required IDs and application policy
handle presence, while real callback ordering dependencies remain packaging metadata.

## 4. Setup, directory, and provider call contracts

### Setup and configuration

The goal owns immutable `ServicesConfiguration`: accepted capability descriptors,
configured provider defaults, explicit required services, launch grants, and upper
resource limits. Broker configuration may lower limits but cannot expand goal
grants. Defaults are construction configuration, not environment variables or
priority rules. An edition inherits them with the factory; selection changes do
not implicitly rewrite them. A differently configured factory requires constructing
or replacing an application definition with that factory; `edition()` and `fork()`
both preserve the existing `goal_factory`.

The helper runs two module-level setup phases, constructed with keyword arguments:

1. `org.engulf.services.configure` in preprocessing order broadcasts a frozen setup
   event to broker participants and returns `BrokerConfiguration` contributions.
   `ServicesConfiguration.permitted_broker_ids` defaults to
   `("org.engulf.services.broker",)`; validate those IDs and cardinality after
   dispatch completes.
2. When enabled, `org.engulf.services.register` broadcasts a frozen registration
   event to provider participants and returns `ServiceDeclarations` containing only
   immutable descriptions. A local-only goal uses the registration phase directly.

Derive provider IDs exclusively from `AttributedContribution.plugin_id`. Validate
all contributions before freezing the directory. Keep only descriptors and IDs;
never store callbacks, implementation objects, plugin APIs, or setup APIs in it.
Setup performs no transport allocation or provider resource work. The runtime
closes setup APIs at [`application.py:623–665`](../../../engulf/src/engulf/application.py#L623).

### Capability compatibility and resolution

`CapabilityKey` is `(capability_id, api_major)`. `api_major` is an exact positive
`int` (never `bool`). Reuse
[`validate_global_identifier`](../../../engulf-api/src/engulf_api/identifiers.py#L9) for
capability IDs and lowercase, dot-qualified full wire method IDs. Typed methods
may have short Python names but carry qualified wire IDs. One provider may publish
multiple majors; each is registered independently. Duplicate declarations by the
same provider for the same key are setup errors.

A capability descriptor contains a frozen method table. Each method names explicit
request/result codec identities and declared error schemas. Providers implementing
the same capability major must agree on each shared method's descriptor and on the
major's required method set. The capability package may add optional methods within
a major; providers advertise which they support. Reject incompatible overlapping
descriptors and missing required methods during setup. Different optional subsets
are valid; calls to an absent optional method return `unsupported_method`. Never
require identical complete method sets as a substitute for this compatibility rule.

An invocation-scoped `ServicesSession` provides:

```text
providers(capability) -> immutable provider descriptions sorted by plugin_id
require(capability, provider_id=None) -> typed provider handle
provider_handle.<typed method>(request) -> decoded result or service error
```

Resolve an explicit compatible, granted provider first; otherwise use the configured
default; otherwise use the sole available provider. Zero providers means
`missing_provider`; multiple providers without a default mean `ambiguous_provider`.
Plugin priority never chooses a provider. Validate every configured default at
setup, even if a caller later supplies explicit IDs. An inactive or incompatible
default is an error with no fallback. Resolve explicitly declared required services
at setup as well. Multiple providers alone do not fail setup.

Child directories contain only granted `(capability_id, api_major, provider_id)`
triples. A grant covers that provider's advertised methods for the capability; method
sub-grants are outside v1. Revalidate launch-required services after filtering.
Filter out defaults whose provider is absent from a restricted child/proxy directory;
do not replace them with a priority-selected provider. An explicit lookup outside
the grant receives `not_granted`, without revealing other provider metadata.

### Calls and error translation

`org.engulf.services.call` is a preprocessing invocation phase addressed to exactly
one provider from this session's frozen directory. Its event contains an opaque
session ID and a validated immutable request envelope. It returns one `ServiceReply`.
`None`, multiple replies, and an invalid reply are provider contract failures.
The goal creates a fresh session route set from the setup directory on each
invocation, and validates the selected provider against it before dispatch.

The module-level phase adapter only checks the participant interface and forwards.
The API's provider adapter performs capability codec decoding, invokes the provider's
implementation, encodes its result, and translates declared service exceptions
inside the callback. Invalid input is converted to a structured request error before
calling business logic. Unexpected exceptions and invalid encoded output escape
the adapter as callback failures. `PluginPhaseError` or selection `ValueError` from
the dispatch bridge becomes an unattributed typed broker infrastructure failure;
`BaseException` still stops the session and propagates unchanged. Implementations
and method bindings stay inside the provider; they are not registration
contributions.

The router converts an attributed `PluginCallbackError` into `provider_failure`
for the client, records the provider ID, and latches a framework failure for the
invocation. It attempts the error response within the normal write budget, then
revokes the session. A caller cannot turn that framework defect into success by
catching the request error: the `ServicesSession` context-manager exit always closes
the session and raises a typed latched-framework error after cleanup. Router-detected
`None`, multiple, or invalid replies take the same latch path even though core
dispatch cannot attribute them. Declared domain errors and valid rejected requests
are recoverable request results and do not latch framework failure. This distinction
is explicit: dispatch diagnostics alone do not force the final result to fail.

Provider callbacks receive only their own active `InvocationAPI`. Context checks,
state namespaces, logging, and callback lock release follow existing runtime
behavior. The bridge holds the current `GoalAPI` only inside the session scope and
clears it on close. Do not expose sessions through plugin events or context.
Record the owner thread and reject wrong-thread use, use after close, and nested
calls with service errors before dispatch. A goal must use the session as a context
manager (or call its equivalent `finish()` guard) so a latched framework error is
raised after cleanup even when goal code catches an individual request error. Goal sessions are single-threaded;
remote clients may serialize calls from multiple caller threads through one owner.

## 5. Generic executable-wrapper support

Add optional `execution_support=None` to the wrapper goal. Its protocols and frozen
launch/readiness/end values belong in wrapper-api and mention no service types:

| Proposed interface | Contract |
| --- | --- |
| `ExecutionSupport.setup(GoalSetupAPI)` | Runs after `_COLLECT_HELP` and before `_setup_complete` in the setup window at `goal.py:322–333`; stores immutable configuration only. |
| `ExecutionSupport.environment_removals` | Frozen names to strip from every executable launch using this helper, including launches with no session. |
| `ExecutionSupport.open(PreparedCallEvent, GoalAPI)` | Returns a fresh `ExecutionSession` or `None` when disabled; cleans partial acquisition itself on `BaseException`. |
| `ExecutionSession.launch` | Frozen environment additions and explicit `pass_fds`; session owns these descriptors until transfer/close. |
| `ExecutionSession.spawned(pid)` | Records successful launch and closes the parent's redundant child endpoints; receives no `Popen` or wait handle. |
| `ExecutionSession.interests()` | Frozen descriptor/read/write interests for the next wrapper-owned selector iteration. |
| `ExecutionSession.step(ready)` | Incremental nonblocking I/O with the configured work budget; at most one synchronous provider call. It returns immediately after that callback, deferring the response write until the next turn so the wrapper polls child state first. A timed selector wakeup calls `step(())` so silent-peer deadlines expire. |
| `ExecutionSession.stop(reason)` | Idempotently revokes transport and prevents new work; no provider callbacks. |
| `ExecutionSession.close(end)` | Idempotently completes provider cleanup while the goal API is active, releases remaining resources, invalidates the bridge, and reports cleanup failure. |

`end` distinguishes preparation failure, spawn failure, child exit, infrastructure
failure, and termination; it carries the actual call outcome when one exists.
These descriptor-bearing values and callback bridges are **local-execution
contracts**, following wrapper-api's existing terminology. Their portability as
Python imports does not promise remote execution or usable Windows descriptors.

A single helper is sufficient for v1. No helper registry, contribution merge across
several execution supports, or direct live-plugin access is introduced.

### Execution sequence

1. Preserve internal completion/install handling and run existing analyzers. Merge
   arguments and resolve all vetoes. Help and preemption open no service session.
2. For viable normal execution, open support before `_prepare`. Validate launch
   metadata and allocate private transport now, but dispatch no service requests.
   Failure here occurs before any preparer acquires resources.
3. Inside the same scoped guard, run existing per-plugin preparation. If it fails,
   preserve reverse preparation unwind and the original exception, then close
   support. Do not invent a failed-preparer ID or call `after_call` for this path.
4. Resolve and spawn the executable. Narrow 127/126 exception translation to
   executable resolution and the `Popen` operation. Signal setup, logging,
   post-spawn notification, pumping, and cleanup failures are framework errors.
5. Notify support, then enter the wrapper-owned wait/pump loop. Even if notification
   raises, close redundant endpoints and retain ownership of the spawned child.
6. On observed child exit, stop transport immediately. Finish reaping through the
   same `Popen`; restore inherited signal handlers; close the service scope before
   `after_call`. Send the real child/spawn outcome to normal postprocessing.
7. Return the actual goal result unless a framework failure was latched. In that
   case return the direct `GoalResult(status=FRAMEWORK_FAILED, exit_code=70,
   value=outcome, error=...)` constructor (the existing `framework_failed()` helper
   has no `value` parameter), retaining the true outcome when available. No service
   phase lets a `PluginCallbackError` escape `achieve`; close traversal converts its
   failure into the same latched framework result.

A support-open failure must unwind its own partially allocated resources. Opening
only after successful preparation is rejected: it creates an extra failure point
after preparers acquired resources without a legitimate preparation-failed event.

### Waiting, signals, and result precedence

The wrapper owns the selector, `Popen.poll()`/`wait()`, and every reaping operation.
No service code calls `waitpid`, consumes an exit status, or owns a process-group
signal policy. Poll before and after each bounded transport step; limit selector
waits to 100 ms. A selector timeout still invokes `step(())`, so handshake,
incomplete-frame, and blocked-output deadlines expire on silent peers. Buffered work
requests an immediate iteration so already-read frames do not depend on another
readiness edge. Version 1 requires no `pidfd`.

Keep execution shell-free, inherit standard streams, cwd, terminal access, and the
wrapper process group. Forward wrapper-PID signals through the existing forwarder.
Do not create a session or process group for the child. The existing wait-only
`KeyboardInterrupt` path may continue forwarding SIGINT and reporting child status;
do not wrap provider dispatch in that special handler.

On an ordinary infrastructure failure after spawn, latch the first error, revoke
transport, and continue ordinary waiting/reaping with signal forwarding. Do not
automatically terminate an otherwise running child on this path. Supported clients
must treat channel loss as fatal to their affected invocation; an arbitrary child
that ignores closure can continue running, just as an ordinary wrapped process can.
Document this limit rather than implying socket closure guarantees its exit.

An escaping `SystemExit`, `KeyboardInterrupt` from provider/helper execution, or
other termination `BaseException` stops services and triggers exceptional child
cleanup, then propagates unchanged. For this path only, send SIGTERM to the direct
child, wait up to one second, send SIGKILL if still running, and reap it with `Popen`.
Do not signal the shared process group. Continue mandatory cleanup if another
exception arrives, preserving the first termination exception; a child stuck in an
uninterruptible kernel wait remains an OS-level limit on reaping. Descendants lose
broker access but are not recursively killed.

After ordinary infrastructure failure, `after_call` still receives the actual child
outcome with `process_started=True`; child exit zero cannot erase the latched failure.
Preserve the first ordinary failure ahead of later close/postprocessing errors,
reporting each secondary error. A termination exception takes precedence over an
ordinary failure and may skip ordinary `after_call`/`after_goal`. These are wrapper
result rules; existing outer plugins still retain their documented result-transform
contract. Do not introduce a synthetic `FRAMEWORK_FAILED` `CallOutcome`.

Genuine plugin callback failures already receive managed plugin attribution. A
goal-owned transport failure uses a typed infrastructure error carrying the broker
ID and stage and logs through the goal's active logger. Name the broker explicitly;
do not forge reserved plugin logging fields or pretend helper execution was a
broker callback.

## 6. Transport, inheritance, and descendant proxies

Use private `AF_UNIX` stream socket pairs. The parent endpoint is nonblocking and
non-inheritable. Pass only the child endpoint through explicit `pass_fds`, preserving
normal close-on-exec behavior for all other descriptors. Close the parent's copy of
the child endpoint immediately after launch or on any launch failure. No public
listener, filesystem socket name, claimed-PID authorization, or global broker exists.

Reserve the public child-process variable `ENGULF_SERVICES_ENDPOINT` (distinct from
the existing `ENGULF_INTERNAL_*` wrapper-control variables) for a small versioned
endpoint descriptor containing
the fd and expected socket identity (`st_dev`/`st_ino` encoded as decimal strings).
Before reading or writing, the client checks the fd range, `fstat`, socket type,
address family, connected state, and identity, then marks it non-inheritable. Reject
a stale descriptor before protocol traffic; never close an unrelated descriptor
when validation fails. Unsupported identity verification fails explicitly.
Endpoint identity is hygiene against descriptor reuse, not authentication of code
running with the same authority.

Build each executable environment from `dict(os.environ)` at spawn time. Remove
helper-owned endpoint variables first and then add this launch's fresh endpoint.
Do not pass normalized invocation-only environment option values to the child.
Reject duplicate/reserved launch metadata at support-open time. The helper's removal
policy also applies when its broker is disabled or the child is being run for help.
When helper metadata is available, completion generation passes `environment_removals`
through the private `describe` response into `render_completion_script`, and the
generated normalize/complete subprocess commands scrub those names. The standalone
completion CLI's bootstrap inspection runs with `close_fds=True` and no service
session, so it cannot know dynamic removal names in advance; stale endpoint
validation and noninheritability remain its protection. Interactive shell
environments are never modified.

Missing endpoints yield `ServicesUnavailable`; malformed endpoints yield a distinct
validation error. Neither case falls back to discovering services. A client that
requires services exits its affected invocation nonzero with a concise diagnostic.
An optional client may deliberately continue without using services only when no
session was established; it must not silently resume after losing one mid-call.

A descendant receives a fresh pair from its immediate parent's explicit proxy.
Never pass the upstream fd to several processes: each connection has one reader and
one serialized writer. A proxy takes a subset of its upstream grants, filters the
directory/defaults, and allocates a new ID only on its upstream leg; it preserves
each downstream client's request ID in the downstream response while rewriting the
upstream correlation ID.
The proxy serializes local and descendant upstream calls and fairly schedules bounded
downstream work. Its I/O worker may run on a dedicated thread because it handles
encoded remote calls only; it never calls a local goal's dispatch bridge off-thread.

Nested Engulf applications keep their own application/provider directory. They do
not merge upstream providers. Relaying upstream access requires explicit proxy
construction and a separate client session. Client/proxy launch helpers scrub the
upstream endpoint variable from unrelated subprocess environments and install only
the intended new endpoint when forwarding access.

Direct-child exit revokes the whole wrapper session, including descendant access.
Discard queued/unstarted requests and unsent replies. A synchronous callback already
running cannot be forcibly cancelled; once it returns, poll child status before
accepting more work and discard its reply if the session ended. A disappeared
downstream peer's reply is discarded without retry. Parent/proxy loss closes its
downstream sessions. An upstream call already sent may have executed even when its
downstream client disappeared: report uncertain outcome, never retry it.

## 7. Protocol version 1

Write the normative protocol document and language-neutral conformance vectors in
`engulf-services/protocol/` before implementing the transport. The following choices
are fixed for that document, not open implementation questions.

### Framing, handshake, and request ordering

Each frame is a four-byte unsigned network-order payload length followed by exactly
that many bytes. Payloads are strict UTF-8 JSON objects. Length zero, excessive
length, truncated EOF, invalid UTF-8/JSON, duplicate keys, or invalid top-level shape
closes the connection. Closing on invalid JSON is a v1 policy; intact frame lengths
could otherwise permit recovery.

The first client frame is `hello` with supported protocol versions and its receive
limit. Both implementations know a fixed bootstrap frame bound and minimum legal
limit; reject a hello too small to encode `ready`. The server selects v1 and replies
`ready` with an opaque session ID, effective limits, the sorted granted
provider/method directory, and filtered defaults. Use the minimum of the client and
server message limits in both directions. Reject version mismatch or an
unadvertisable directory before accepting calls. No discovery operation imports
plugins. Handshake messages themselves obey the bootstrap bound and a fixed
handshake deadline.

Every call includes `version: 1`, `type: "call"`, a connection-scoped positive
integer `id`, `capability_id`, `api_major`, an explicit `provider_id`, a qualified
`method_id`, and `input`; it may include bounded `remaining_timeout_ms`. The client resolves defaults against `ready`; the server
revalidates the exact grant and advertised method. IDs strictly increase within a
connection and never repeat; establish a new invocation before exhausting their
integer range. A response echoes version/id and has exactly one `result` or `error`.

Only one request may be outstanding per connection. Clients serialize callers and
proxies serialize their upstream traffic; local waiting callers are capped and use
deadline-aware admission rather than an unbounded library queue. IDs detect
mismatches and support proxy remapping; they do not imply pipelining. Do not retain
an unbounded ID history; the last accepted ID and current request are sufficient. No
unsolicited messages, notifications, remote callbacks, or transport cancellation
are supported.

After handshake, syntactically valid envelopes with a usable new ID but invalid
request fields receive a correlated error and remain usable. Missing/invalid IDs,
repeated IDs, wrong protocol ordering, or unsupported message types close the
connection. Unexpected response IDs or response shapes close the client session.
The normative schema must explicitly define required/optional fields and reject
unknown envelope fields so both implementations make the same decision.

### JSON and codec equivalence

Allow null, exact booleans, strings containing Unicode scalar values, finite numbers,
arrays, and objects with string keys. Reject duplicate keys, NaN/infinity, lone
surrogates, cycles, and implicit conversion of unsupported Python values. Limit JSON
nesting to 64 levels. Integer values are limited to
`-(2**53 - 1)` through `2**53 - 1`; this is a deliberate interoperability policy,
not a limitation inherent in Python or Go. Use explicit capability codecs for larger
integers, bytes, decimals, and domain objects. Go decoding must use `json.Number`
and validate numbers instead of silently accepting default `float64` coercion.
Floating values use finite binary64 semantics; capability schemas specify whether a
particular field accepts integer and/or floating forms. Define lexical handling in
the vectors: `1` is an integer, `1.0` and `1e0` are finite numbers, `-0` preserves
its numeric sign where the codec permits it, and `1e400` is rejected as non-finite;
safe-range checks apply after parsing the agreed JSON number grammar.

Local calls traverse the same full envelope encode/validate/decode path, size/depth
limits, and request/result codecs as remote calls. The decoder recursively freezes
objects into immutable mappings and arrays into immutable sequences before creating
events; the encoder thaws only at the JSON boundary. This prevents implementation
object identity or mutable aliasing from becoming observable service behavior. A
typed codec may intentionally map a tuple to an array; generic serialization must
not do so implicitly. Byte-for-byte object key order is not significant, but accepted
values and errors must agree. Codec IDs and schemas in the directory are data only;
trusted capability packages supply executable local codec bindings, and no wire ID
ever triggers an import. Provider declarations must match the goal's accepted
canonical descriptors, not merely agree with one another.

The service codec format is a service contract. It is not a generic codec for
`GoalPhase`, retained APIs, or descriptor-bearing execution support. A future
goal-owned execution codec may reuse service payloads without implying arbitrary
existing phases are transportable.

### Errors, deadlines, and resource bounds

`error` contains `kind`, `code`, a safe `message`, optional JSON `data`, and the
validated capability/major/provider/method attribution when available. Declared
domain errors use capability-owned codes. Define shared codes for
`invalid_request`, `missing_provider`, `ambiguous_provider`, `not_granted`,
`unsupported_method`, `provider_failure`, and `broker_failure`. Connection loss,
session closure, local validation, and deadline expiry also have typed client
exceptions because a dead connection cannot reliably deliver an error frame.
Never put unexpected provider tracebacks, arbitrary exception text, or raw Python
objects on the wire; retain full details in managed diagnostics.

A remote client deadline covers queueing, encoding, send, provider wait, and response
decoding. Default call deadline is 30 seconds, configurable by the caller; the
request carries a bounded `remaining_timeout_ms` field that proxies decrement for
their own queueing and processing. Expiry before any request bytes are sent is a
local timeout with no provider execution; expiry after transmission begins closes
that client session and reports outcome unknown. Portable local calls perform
cooperative checks before dispatch and after it returns; a synchronous provider
cannot be interrupted by this deadline. There is no reconnect, automatic retry,
late-response reuse, or claim that a deadline cancels provider work. Proxies preserve
the remaining budget and do not retry an expired or interrupted upstream call.

Default limits, configurable downward by broker policy and within goal upper bounds:

| Limit | Version 1 default and behavior |
| --- | --- |
| Encoded frame payload | 1 MiB (`1024 * 1024`, aligned with `DiagnosticIsolationConfig.protocol_limit_bytes`), checked before payload allocation; handshake directory must fit. |
| JSON depth | 64 levels, enforced by both languages and local calls. |
| Active downstream connections per proxy | 16; the wrapper broker itself has one direct-child connection. Refuse new connections at the cap. |
| Outstanding requests | One per connection, one executing provider call in the wrapper, one upstream call in each proxy. |
| User-space input/output buffers | One bounded input and one bounded output frame per connection; no unbounded decoded queue or response list. |
| Aggregate buffering | 32 MiB per broker/proxy for transport/parser-owned storage, including charged decoded-envelope storage; admission stops before allocation would exceed the budget. Trusted provider/codec implementation memory is outside this accounting. |
| Work per pump turn | At most 64 KiB read and 64 KiB written in aggregate, round-robin connections, at most one provider call; return to child polling between turns. |
| Handshake / incomplete frame / blocked output | 5 seconds / 30 seconds / 30 seconds from start of that operation, without resetting on tiny progress; close the stalled peer on expiry. |

Define conservative decoded-value charges and maximum object/member counts in the
normative parser specification so a byte cap cannot hide unbounded object overhead.
Check encoding incrementally, too: do not construct an oversized response first and
only then reject it. Stop reading while a connection has an unfinished response;
kernel backpressure bounds a busy peer without growing a user-space queue. Reserve
room for a bounded error response before invoking a provider. Proxies remove clients
that stop reading without blocking unrelated connections.

Normal EOF and peer reset close the affected session; they are not automatically
broker infrastructure failures. Framing violations are connection errors. Internal
selector/state/descriptor failures and provider contract failures latch framework
failure. The concrete transport must distinguish these cases rather than catch every
`OSError` as a broker defect. A provider may validly finish after its peer disappears;
discard that reply and perform cleanup.

Synchronous callbacks determine responsiveness. Providers must use finite lease and
external-I/O waits, document their maximum operation duration, and clean up failed
operations. Transport budgets do not preempt Python code or interrupt a blocked
provider when the forwarder sends a signal to the child. Enforced provider deadlines
would require another execution model and are outside v1.

## 8. Session cleanup and provider resources

The session tracks a provider as touched immediately before its first dispatched
call, so even a partially failing first call is included. On close, stop transport
first, then send `org.engulf.services.close` with a frozen session ID and close reason
to touched providers in reverse first-use order. The provider mixin supplies a no-op
default close hook. Providers that allocate session-scoped resources implement it
idempotently. No close notification is promised after process death or SIGKILL.

Dispatch each close callback individually through a postprocessing phase with normal
failure propagation, catch `BaseException` around each dispatch, and attempt every
participant. This deliberately implements cleanup traversal in the goal helper:
`isolate_failures=True` alone cannot expose ordinary failure status or continue after
termination exceptions. Preserve the primary termination exception, or the first
ordinary error if there was none, while reporting subsequent failures. Invalidate
the dispatch bridge in an unconditional final cleanup path, even if every close
callback fails. Repeated close does not invoke providers twice.

A provider handles partial allocation in its own call with
`except BaseException: release_partial_work(); raise`. That release assumes any
leases from the current callback are still held. A later session-close callback
acquires fresh finite leases before releasing persisted resources. Never retain
an active API, logger, transaction, or lease context between service calls.

Arbitrary streams, sockets returned by domain APIs, shared memory, external processes,
images, and similar resources remain owned by their capability/provider contract.
Service close is a notification, not generic resource destruction. Resources that
survive a callback require explicit ownership tokens, managed state/recovery records,
and idempotent recovery on a later invocation. A lost reply can mean a completed
side effect whose result was never received. Neither automatic retry nor automatic
transaction rollback is implied. Normal `after_call`/`after_goal` may supplement
cleanup but cannot be its sole path.

## 9. Implementation sequence and acceptance gates

Each stage should be reviewable and keep the existing disabled path working.

| Stage | Work and owning files | Acceptance gate |
| --- | --- | --- |
| 0. Establish the baseline | Fix the spawn-error boundary in wrapper `goal.py`; repair existing CI example installation and missing plugin lint/build coverage; correct the stale `completed_plugin_ids` examples/prose in `engulf-api/README.md` and `AGENTS.md`. | Post-spawn injected `OSError` never reports `process_started=False`; existing 127/126/signal mappings pass; CI launcher imports with both example packages installed; cleanup guidance matches the actual error type. |
| 1. Contracts and spec | Scaffold the three distributions; add capability/participant contracts and `engulf-services/protocol/` specification/vectors. Read each new owning README before further edits. | Strict type/identifier/immutability tests; explicit method compatibility and domain error tests; reviewed request/reply/handshake schemas and numeric/resource limits. |
| 2. Portable local services | Implement registration, directory validation, local sessions, targeted routing, failure latch, and provider close traversal. | Two-provider local Python demo, correct state/context/logger attribution, no unselected imports, defaults and ambiguity, wrong-thread/closed/nested use, failure and repeated-invocation tests on Linux and Windows. |
| 3. Generic wrapper seam | Add wrapper-api execution contracts and wrapper lifecycle support using a fake helper; preserve preparation order and narrow spawning. | Disabled/help/completion/preemption paths create no session; open/prepare/spawn/notify/pump/close failures follow the exact result and cleanup rules above. |
| 4. Direct-child protocol | Implement incremental POSIX frames, client handshake, endpoint validation, budgets, wrapper selector integration, and the broker adapter. | Real child call, partial read/write, stale fd, environment preservation, deadline, provider failure, channel loss, real child status, and no-retry tests. |
| 5. Proxies and interoperability | Implement restricted proxy sessions; add a Go module/client and wrapped demo at `examples/services-go/`. | Shared vectors and real Python↔Go traffic, two providers, restricted descendants, upstream serialization, fair backpressure, parent/proxy crashes, and direct-child revocation. |
| 6. Workspace integration | Finish READMEs, example launchers, build/type/documentation checks, packaging validation, and CI. | Every required workspace/new-package check passes, all eight public distributions build wheels and sdists and pass Twine, and clean-environment installs run both demos. |

Use a small, side-effect-free capability for the first end-to-end demo, with two
providers producing distinguishable results. Reuse the script-free factory and
edition pattern from [encryption-core](../../../examples/encryption-core/README.md) in a
dedicated `examples/services-python/` example rather than making cryptography depend
on services. Add a separate resource-owning test provider to exercise journals and
close hooks. The Go example runs the same capability and includes a restricted proxy
case; raw-socket Python tests supplement it, not replace it.

Deterministic tests must cover:

- **Discovery and construction:** setup broadcast attribution, broker absent/present/
  duplicate, required broker missing, edition activation with the same factory,
  invalid declarations/defaults, explicit multi-provider selection, multiple majors,
  compatible optional method subsets, conflicting shared methods, and no import of
  unselected installed providers. A fresh `Application` sees a fresh directory.
- **Managed calls and cleanup:** provider-owned context/state/logger, leaked lease
  release, declared errors without framework diagnostics, unexpected exceptions and
  malformed replies latching 70, partial self-unwind, all touched providers offered
  close after failures, secondary cleanup failures, preserved `SystemExit` and
  interrupts, stale handles and repeated invocations. Never infer completed calls
  from `PluginCallbackError` attributes that do not exist.
- **Protocol and resources:** local/remote conformance, duplicate keys, Unicode,
  numeric boundaries, depth and object budgets, byte-at-a-time frames, bad length,
  malformed JSON versus valid rejected request, mismatched IDs, no pipelining,
  handshake limits, oversized directory/result, timeout before/after transmission,
  stalled writes, aggregate backpressure, and exactly one provider execution when
  the response is lost.
- **Processes:** child exit while holding a partial frame, exit during a provider
  call, queued work dropped, broker failure followed by child exit zero, post-spawn
  notification failure, parent/proxy loss, stale/reused/wrong-kind fd, redundant fd
  closure, unintended inheritance, explicit narrower proxy grants, and isolated
  nested Engulf directories. Use pipes/barriers/readiness notifications rather than
  timing-only sleeps.
- **Wrapper regressions:** use the readiness harness at
  [`test_goal.py:729–814`](../../../engulf-executable-wrapper/tests/test_goal.py#L729) for
  signal/process-group behavior and add an actual PTY/controlling-terminal test.
  Extend [`test_goal.py:270–306`](../../../engulf-executable-wrapper/tests/test_goal.py#L270)
  to inspect child environment as well as callback overlays. Check completion
  subprocess endpoint scrubbing and no service setup side effects.
- **Portability:** import API/client/local services with wrapper/runtime packages
  absent, exercise local sessions on Windows, and verify the transport stub's clear
  unsupported-platform error. Add a real Go toolchain in Linux CI.

## 10. Build, documentation, and version policy

At implementation time update:

- [`Makefile`](../../../Makefile): add three public distributions and the broker's directory
  mapping; include each in packaging checks, builds, and consumer installation.
- [Root `pyproject.toml`](../../../pyproject.toml): add new public/example paths to mypy and
  any development tools required by the tests. Existing plugin/example entries are
  already present; these changes are additions.
- [`tests/test_documentation.py`](../../../tests/test_documentation.py): add public exports
  and owning READMEs for the new packages.
- [CI](../../../.github/workflows/ci.yml): install both existing encryption example wheels,
  include `plugins/` in Ruff, build `engulf-plugin-list` and the new packages, run new
  suites on the appropriate platforms, and install Go for actual interoperability.
  Build example dependencies as well as their launchers when building examples.
- [Workspace README](../../../README.md), [AGENTS.md](../../../AGENTS.md), and owning READMEs:
  update the package-boundary tables, dependency diagram, documentation map,
  public distribution count from five to eight, editable installation commands,
  capability authors/provider adapters, optional runtime extra, and unsupported
  platform behavior. Update the sibling [goal-owned-cli-parser plan](../../goal-owned-cli-parser.md)
  where it says that five distributions are built.

Keep existing package versions, `PLUGIN_API_MAJOR`, and the wrapper goal API major
unchanged during this work, as the current workspace instructions require. Declare
an independent services API major and wire protocol version, both initially 1.
Do not reinterpret historical release commits as permission to change that policy.
Before any later release, verify hosted artifacts, bump versions as separately
authorized, and raise dependency floors together so a new helper/runtime cannot be
installed with an older wrapper-api lacking execution support. Until that release,
validate the coherent source/wheel set and do not claim existing broad published
dependency floors guarantee the new interfaces.

Run the environment setup and all workspace commands required by AGENTS.md:

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

Extend lint/format targets for the two new top-level directories, run all new package
and Go suites, and run `./build.sh` after package metadata changes. Do not hand-edit
generated archives. Coordinate the setup insertion point and API changes with
[goal-owned-cli-parser.md](../../goal-owned-cli-parser.md); services adds no CLI parser
or endpoint-related user command. Neither plan should bypass the other's existing
argument/environment semantics.

## 11. Review finding disposition

This table closes architecture decisions for implementation without claiming that
the corresponding code or tests already exist.

| Finding | Decision / plan section |
| --- | --- |
| B1, R1, R3 | Sections 3–5: goal-owned helper installed by base factory, selected broker returns data, broadcast setup, targeted provider invocation, no live plugin access or core API extension. |
| B2, S7 | Sections 3–4: three distributions, independent participant mixins, optional wrapper integration import, capability ownership outside core. |
| B3 | Section 5: wrapper exclusively owns `Popen`/reaping; incremental pump and 100 ms polling, no mandatory pidfd. |
| B4, R4 | Sections 5 and 9: fix broad spawn handlers first; real child outcome reaches `after_call`; infrastructure failure remains framework 70. |
| B5, R5, R6 | Sections 6–7: serial protocol with IDs/handshake, JSON/codec rules, explicit safe-integer policy, deadlines, aggregate bounds, backpressure. |
| B6, R2 | Sections 4–5 and 8: declared errors translated within callback; unexpected failures latch 70; termination exceptions preserved after cleanup. |
| S1, S2 | Sections 5–6: endpoint identity and inheritance rules, service-free launch scrubbing, fresh process-environment overlays. |
| S3 | Sections 5–7: bounded transport, finite provider waits, explicit limits on synchronous responsiveness and child termination guarantees. |
| S4 | Sections 6 and 8: direct-child revocation, touched-provider close hook, partial-operation unwind, recovery contracts separate from socket cleanup. |
| S5 | Section 4: validate defaults/declared requirements at setup; permit several providers and defer ordinary unqualified ambiguity to lookup. |
| S6 | Section 4: goal/child callers only, explicit thread/reentrancy/closed guards, no plugin session access. |
| S8 | Section 1: existing privilege opt-in retained; no new approval policy; broker grants are not OS isolation. |
| S9, R13, CI | Sections 9–10: named source test assets, real Go demo/toolchain, existing CI repairs distinguished from new package additions. |
| S10 | Section 10: obey the current no-bump instruction; verify artifacts and floors at a separately authorized release. |
| R7, R8 | Sections 2 and 11: pinned source evidence plus this implementation mapping. |
| R9 | Header identifies the old documents as historical; this new sibling is the complete successor. No previous plan/review is rewritten. |
| R10 | Section 4: reuse qualified identifier validation for capability and wire method IDs. |
| R11 | Section 6: nested application directories stay separate; upstream proxying is explicit. |
| R12 | Section 4: validate required and overlapping method contracts; allow advertised optional-method subsets. |
| Additional source findings | Sections 4 and 8: service runtime enforces thread affinity, records participation itself, and explicitly propagates failure status that diagnostics/isolated dispatch do not supply. |
