# Plugin services v4, plan 2: managed services implementation

Status: proposed implementation plan, independent of the decision to complete
[plan 1: Engulf interface stubs](plugin-services-v4-engulf-foundation.md).
The foundation can be released and used indefinitely without starting this work.
No implementation, metadata update, or publication has been performed by saving
these plans.

This plan carries the functional work from [v3](plugin-services-v3.md), corrected by
the [critique synthesis](plugin-services-v3-critique-synthesis.md). The two v4 plans
replace v3's combined sequencing and version policy. The foundation owns the public
core/wrapper interface definitions; this plan implements their promised behavior
and adds optional service contracts. Where older documents disagree, v4 governs.

Evidence baselines remain Engulf `4bac606f1aeb3547ad64febfd1fd8068dcd994d4` and
engulf-clab `5f3afaec5032133e003e4e5309ab1c690450e284`, read from committed source.
Implementation starts from the actual completed foundation revision and manifest,
not by resetting either repository to those historical evidence commits.

## 1. Outcome and boundary with the foundation

Implement managed calls from goals, plugin lifecycle/phase callbacks, and explicitly
granted children. Each provider executes through the framework endpoint in its own
activation, with its own state, logger, context, and leases. Support synchronous
acyclic call chains and dependency-aware resource cleanup.

The initial production consumers are eclab's registry, consumption, sleep, and image
providers. Portable Python and direct-child Go examples prove a shared capability.
Explicit descendant proxying follows as a separate milestone.

This plan includes the internal `engulf` and wrapper runtime work that turns plan 1's
stubs into working mechanisms. That implementation does not introduce another
mandatory plugin callback, change the existing catalog major, or require unrelated
plugins to adopt services. It does require a later runtime release and raises the
application integration's runtime floor above the stub release.

| Work | Owner in this split |
| --- | --- |
| Core/wrapper public generic definitions, unavailable behavior, first version/floor rollout | Plan 1, completed before this plan depends on them. |
| Invocation handlers, restricted dispatch, nested-call stack, lock checks, origin/latch/finalization | This plan, in `engulf`; honor the foundation API. |
| Execution-support setup, wait/pump lifecycle, child environment and cleanup | This plan, in the wrapper runtime; honor the foundation wrapper-api. |
| Capabilities, codecs, directory, local access, service resource scopes, broker and clients | This plan, in optional services packages. |
| Both eclab constructors and migrated producers/consumers | This plan, in the sibling application/plugin packages. |
| Release-wide unrelated plugin API/catalog transition | Already handled, or shown unnecessary, in plan 1. Do not repeat it here. |

There is no promise that service-adopting plugins need no release: their code and
dependencies change here. The independence is that the foundation and other plugins
do not wait for this implementation or need another blanket compatibility rollout.

## 2. Activate the reserved core mechanism

Implement `GoalSetupAPI.register_operation`, `InvocationAPI.operations`, the handler
factory/lifecycle, and restricted `OperationAPI` in core. Keep state and activation
collaborators in `_capabilities`, traversal/dispatch in `_dispatch`, and invocation
ownership/finalization in `Application`. Core imports no services or wrapper types.

Registration is setup-only. Validate unique operation IDs, types and allowed phases;
retain immutable definitions, not plugin implementations. Construct a fresh handler
per definition before `before_goal`, with the immutable invocation and no retained
setup API. Close every successfully created handler if a later factory fails.

`OperationClient` validates owner thread, active callback generation, operation
registration, request/response type, and permitted dispatch. Provider dispatch is
targeted to selected participants through the existing endpoint. Only a provider
that successfully completed `before_goal` can serve an ordinary operation; core
tracks this readiness from actual hook completion, not priority or declaration.

Use `OperationRequestError` for defined request/readiness/cycle/lock rejections and
the foundation's unavailable error only for an unavailable implementation. The
services handler maps these typed cases to service errors without parsing messages.
No rejected request causes implicit selection, early lifecycle execution, or a
new framework-failure latch by itself.

### Nested activations and locks

Maintain the invocation-owned participant stack. For A → B → C, B and C receive
their own fresh APIs; ancestors stay active while suspended. Descendant deactivation
releases only descendant locks. Reject self/ancestor activation before entering the
target, include the path, and cap call depth at 32. Preserve the foundation's stale-
generation and thread checks for every newly functional handle.

Lift current lease-before-transaction rules across the active stack:

- Do not dispatch another provider while any ancestor holds a state transaction.
- Under ancestor external leases, descendants can perform short own-state reads/
  transactions but cannot acquire another external lease, including reacquiring the
  same name as another participant.
- Without an ancestor lease, acquisition uses the existing sorting, validation,
  partial-release, and finite-timeout policy for service work.
- Never transfer ownership or release ancestor resources on a descendant's return.

Use explicit finite waits in service providers; existing `timeout=None` behavior
elsewhere is unchanged. These rules prevent introduced framework lock inversion,
not arbitrary external deadlocks or indefinite synchronous Python execution.

### Failure origin, result precedence, and finalization

Implement the reserved `OperationFailure` carrier and immutable call frames. Capture
the originating `PluginCallbackError` and chain before unwinding. The phase dispatcher,
both hook runners, and the goal boundary recognize runtime-recorded operation failures
before generic exception wrapping; passing C's failure through B/A does not relabel
or report it twice. Preserve the old `PluginCallbackError` constructor and fields.

Only actual managed-operation/provider defects and infrastructure/cleanup failures
set the new invocation latch. Declared domain errors and request rejections do not.
Registering an unused operation does not make unrelated hook failures sticky. An
application without operation registration keeps its existing result semantics.

Run ordinary after hooks, close handlers in an invocation `finally`, then finalize
workspace destruction and close APIs. This also runs after `before_goal` handles
the command or a termination exception skips ordinary after hooks. A latched
operation failure overrides later successful middleware with framework exit 70,
retaining a real result/child outcome value through the direct `GoalResult`
constructor. Existing workspace-cleanup failure precedence remains in force.

Preserve the first termination exception over ordinary errors, and the first
ordinary failure over later ordinary cleanup failures. Attempt all mandatory
cleanup and report secondary failures. Never wrap termination into a service error
or invent a provider origin for an infrastructure defect.

Set `OperationSupport.implemented=True` only after this complete runtime passes its
real invocation tests. Before optional services exist, exercise a small test handler
through `before_goal`, nested provider calls, early completion, and finalization.

## 3. Implement the generic wrapper seam before migrating eclab

Implement the entire foundation `ExecutionSupport`/`ExecutionSession` contract using
a fake helper as the first consumer. This needs to precede the eclab migrations:
their base goal uses the support helper's setup integration even when no child
broker is selected. Do not try to install that helper into the foundation wrapper,
which deliberately rejects it.

Call support setup after `_COLLECT_HELP` and before setup completion. Preserve the
ordinary blocking wait with `execution_support=None` or an `open` result of `None`.
Resolve analyzers/vetoes first; only then open child support, before preparation.
An open failure unwinds itself before preparers acquire resources. A preparation
failure keeps existing reverse successful-preparer unwind and has no `after_call`.

Narrow 127/126 translation to executable resolution and `Popen`. After spawn, the
wrapper owns the only `Popen`, selector, signal forwarding, polling, and reaping.
Support receives the PID, never a wait handle. Poll before/after each bounded step,
cap selector sleeps at 100 ms, call `step(())` on timer wakeups, and honor
`ExecutionProgress.immediate` before blocking again. Response writes deferred after
a provider call must not incur an artificial full polling interval.

Preserve inherited standard streams, cwd, controlling terminal, and process group.
On child exit, revoke transport, reap, restore signal handlers, close child resources,
and send the real outcome to `after_call`. An ordinary infrastructure failure revokes
transport and latches failure but continues ordinary waiting; it does not kill the
child automatically. Provider/helper termination exceptions instead trigger direct-
child SIGTERM, one-second wait, SIGKILL if needed, and reaping before propagation.
Do not kill the shared process group or swallow provider exceptions in the wrapper's
special wait-only Ctrl-C path.

Build child environments from fresh `os.environ`, scrub helper-owned names, then add
the intended launch values. Keep normalized invocation-only overlays out of the child.
Carry removal metadata through completion describe/rendering; bootstrap inspection
uses `close_fds=True` and endpoint validation. No interactive-shell mutation.

Set `EXECUTION_SUPPORT_IMPLEMENTED=True` only after fake-helper lifecycle, outcome,
failure, signal, environment, and cleanup tests pass. The flag reports a working
generic seam, not an installed services broker or platform-independent transport.

## 4. Optional services packages and local calls

Add three distributions, initially `0.1.0`, with `py.typed`:

| Distribution | Responsibility and dependencies |
| --- | --- |
| `engulf-services-api` | Capability/method descriptors, immutable events/replies, codecs/errors, participant interfaces, API-only `services(api)` facade. Depends on the foundation `engulf-api`. |
| `engulf-services` | Operation handler, local directory/router, resource scopes, protocol/Python client, later transport/proxies. Depends on API packages; wrapper integration imports remain in its optional wrapper module/extra. |
| `engulf-plugin-services` | Selectable wrapper broker returning immutable transport configuration; depends on services-api, core API, and wrapper-api, not runtime implementations. |

Core and wrapper-api stay free of services dependencies. Provider/consumer wheels
depend on API packages. The Python child's closure includes services, services-api,
engulf-api, and its capability API, without the concrete Engulf or wrapper runtimes.
Applications hosting calls declare the later runtime floors themselves; do not add
the Engulf runtime to every child's or provider's installation closure.

Local service integration registers the generic operation through goal setup.
Broker ID `org.engulf.services.broker` enables child transport only. Its absence must
not disable local services. A base factory installs integration so editions can
change selected providers/broker without replacing the factory. Broker modules do
not allocate sockets or run foreign providers.

### Directory, codecs, access, and readiness

Keep v3's attributed broadcast setup: `org.engulf.services.configure` and
`org.engulf.services.register`. Freeze immutable descriptions after all contributions
are collected; derive provider IDs from attribution. Never retain callbacks, APIs,
or implementations in the directory. No lookup discovers or activates more plugins.

Capabilities use qualified IDs plus independent major 1, canonical required methods,
compatible optional subsets, explicit request/result codec identities, and declared
domain errors. Validate against application-accepted descriptors. Defaults and
required services are checked during setup; generic priority never chooses a provider.
Enumeration is stable by plugin ID; explicit selection, configured default, or a sole
compatible provider resolves a handle, otherwise lookup reports missing/ambiguous.

`services(api)` uses the registered generic operation, not shared context. Provider
calls and close notifications use the owner's endpoint and fresh API through the
registered service phases. A call returns exactly one valid reply; explicit domain
no-opinion is a value, never an absent contribution.

Local access is application policy evaluated against the runtime caller. Child
grants default to empty and expose only permitted capability/major/provider triples.
Provider dependencies use that provider's access while retaining the initiating
resource scope; this does not grant the child direct access to the dependency.

Selected, registered, and ready are distinct. Core guards universal `before_goal`
readiness; capability adapters enforce later operation-specific preparation before
business work. Keep real packaging-order dependencies. A caller needing an optional
provider early must have an ordering path for that alternative or move its call;
priority and `ProviderNotReady` are not substitutes for the dependency contract.

### Resource scopes

Local callback calls use an invocation scope; child/proxy initiated calls use a child
scope. Nested calls inherit their initiating scope. Close the child scope before
`after_call` and keep invocation services usable through `after_goal`; core then
finalizes invocation resources before state destruction/API closure.

Track providers before their first dispatch, including partial failure, and maintain
a per-scope caller → dependency DAG. Reject a reverse edge that creates a scope
cycle even after earlier calls returned. This stricter temporal restriction is
part of the chosen model, not merely active recursion detection.

Close A before B when A uses B, with stable ID ordering among unrelated providers.
During close, permit only established same-scope dependencies, no new edges/providers
or reopening. Dispatch each close through the owner, attempt all providers after
failures, and invalidate all handles unconditionally. Scope closure is idempotent.
Provider self-unwind, finite fresh leases for later cleanup, and durable recovery
journals remain capability responsibilities; no implicit retry or rollback is added.

## 5. Application and plugin migrations

First update both eclab goal-construction paths in
[app.py](../../../../engulf-clab/engulf-clab/src/engulf_clab/app.py): `_containerlab_goal`
and `ContainerlabApp.__init__`. Share an application-owned configuration helper,
preserving binary/completion, metadata, plugin policy, and workspace behavior.
Keep imports free of discovery/setup side effects.

Accept canonical registry/image capabilities and installed recipe codecs. Permit
consumption/sleep to call `engulf_clab.lab_registry`, and image-build to enumerate
selected compatible wrapper offer providers. Require registry presence only when
selected consumers need it; keep minimal/custom policies viable. Configure no image
service default and grant Containerlab no child services for these local migrations.
Declare the functional runtime floors and optional services dependencies in the
application. An old foundation runtime must fail compatibility checks before provider
business work, not be mistaken for services support because its stubs are present.

### Registry, consumption, and sleep

Keep registry identity/state namespace, `labs.json`, record keys, canonical paths,
topology retention, deployment history, and complete-observation image ownership.
Replace the operational context object with `records()` returning fresh immutable
persisted inventory and `commit_observations(records)` acknowledging a completed
transaction/write. Missing storage is complete empty inventory; corrupt/unreadable
storage is explicitly unavailable. Do not acknowledge deferred or discarded writes.

Consumption stays in `before_goal`, rereads on each two-second reporting iteration,
commits complete observations, and warns on expected persistence failure. Preserve
read-only measurement, deduplication, and N/A values when inventory completeness is
unknown. Automatic post-deploy registry observation remains best effort for expected
domain failures and uses the provider's own storage directly.

Sleep stays in `before_goal` and holds `eclab-sleep:docker` across planning, registry
commit, and deletion. Its registry call uses the registry's own state transaction.
Delete nothing if inventory is unavailable or commit fails; begin deletion only
after acknowledgement. Preserve existing ownership filters, workspace preservation,
and independent partial-failure reporting. This is a persistence barrier, not a
transaction spanning Docker and the filesystem.

An integration test must read actual persisted records independently at the first
fake Docker deletion. Ordering fake method-call events is insufficient. Test failed
and concurrent writes, repeated calls, fresh polling, and both application paths.

### Image offers

Replace wrapper `IMAGE_PROVIDER_CONTEXT` callables with a managed capability returning
explicit `Offer`, `Reject`, or `NoOpinion`. Image-build's `prepare_call` obtains
responses through `services(api)` and passes them into the existing image-core
`provider_lookup` seam. Every provider owns its activation and prepared state.

Keep authority, terminal rejection, explicit domain preference, deterministic ties,
dependency graphs/conflicts, default pull, and candidate/build fallback in image core.
Trying another image candidate is domain policy, not an RPC retry. Preserve archive/
vrnetlab and other preparation order edges and reject offers before their maps are
ready. Existing build workers consume resolved data and never receive APIs.

Attribute wrapper calls to the active wrapper adapter ID. Preserve separate
DockerImageGoal catalog adapters and its sanctioned `PROVIDE_IMAGE_PHASE`. Install
explicit codecs for each accepted recipe kind; wire identifiers never import code.

Migrate each producer/consumer set coherently, then remove its operational context
objects/declarations. Keep legitimate immutable shared data, schema contracts, and
image graph contributions. No fallback to direct foreign calls or delayed registry
writes is permitted. These are service-consumer releases, not the foundation's
ecosystem-wide packaging transition.

## 6. Direct-child protocol and later proxies

Define the protocol with Python/Go encoder/decoder vectors before transport. Every
portable capability owns separate payload vectors tested by actual Python codecs
and independent Go adapters; a generic JSON parser does not prove recipe/record
semantics. The Go example is reference/interoperability code, not a separately
published SDK commitment.

Retain these v3 choices with the synthesis corrections:

- Private Unix stream socket pairs, non-inheritable endpoints, explicit `pass_fds`,
  and early closure of redundant descriptors. Validate the versioned
  `ENGULF_SERVICES_ENDPOINT` fd/type/family/connected state and device/inode identity
  before traffic; never close an unrelated reused fd on validation failure.
- Four-byte network-order frame length and strict UTF-8 JSON. One outstanding request
  per connection, increasing IDs, no reconnect/retry/cancellation/remote callbacks.
  Local calls use the same encode/validate/decode path and immutable decoded values.
- HELLO bootstrap 4 KiB; constrained receive floor 4 KiB and standard frame limit
  1 MiB. Serialize real directory fixtures, make READY fit the negotiated bound, and
  reject an unadvertisable directory intelligibly. No speculative directory paging.
- Safe 53-bit integer tokens, finite binary64 floating forms, integer negative zero
  normalized, floating signed zero retained, explicit domain codecs, depth 64 and
  65,536 value nodes. Reject duplicate keys, invalid Unicode, unknown envelope fields,
  unsupported values, and invalid frame/response ordering.
- Closed error kinds `request`, `domain`, `provider`, `infrastructure`, `protocol`,
  with the synthesis's distinctions between recoverable requests, framework defects,
  peer misuse, and typed client-only channel/uncertain-outcome failures.
- One bounded input/output frame per connection, 32 MiB aggregate charged transport/
  parser storage, reserved error capacity, incremental output encoding, 64 KiB read
  and write work per turn, at most one top-level provider dispatch, and prompt return
  to child polling. Nested provider calls remain synchronous within that dispatch.
- Five-second handshake and 30-second incomplete-frame/blocked-output limits, without
  resetting on tiny progress. Bound waiting clients at 16; never grow decoded queues
  or ID histories without limit.

Use 30-second application call budgets initially. The wire's 24-hour numeric ceiling
is a validation limit, not permission or an execution bound. Nested requests cannot
extend the initiating deadline. Check budgets before/after cooperative provider
work; use finite provider waits. Timeout before sending means no dispatch; after
transmission starts, channel loss/expiry means outcome unknown and no retry. Document
that synchronous providers can delay polling beyond any selector interval/deadline.

Direct-child exit revokes child access and discards queued work/unsent replies.
An executing callback returns cooperatively; poll before writing its response.
Closing child transport/resources does not disable invocation-local services.

Deliver proxying after direct-child acceptance. Each explicit proxy creates fresh
downstream pairs with narrower grants, serializes upstream requests, remaps upstream
IDs while preserving downstream IDs, and keeps nested Engulf directories separate.
No automatic endpoint sharing or upstream discovery is introduced in the meantime.

For proxies, cap downstream connections at 16 and fairly schedule bounded queues.
At capacity return recoverable `resource_exhausted`; expire queued-unsent requests
with correlated `deadline_exceeded` while preserving healthy peers. Queue timers
run independently of upstream response waits. Recheck/decrement budgets before
forwarding; do not promise to predict arbitrary synchronous completion times.
Parent/proxy loss closes descendants; uncertain upstream work is never retried.

## 7. Compatibility checks, observability, and releases

Use the completed foundation manifest, then assign later functional runtime
versions. If the foundation candidates were used, Engulf/wrapper `0.5.0` are the
next source-based minor candidates; confirm actual unused versions at release time.
Core API `1.4.0` and wrapper-api `1.3.0` need no interface change merely because
their implementations become available. Do not bump their catalog majors.

Applications require the functional runtime floors, not just the foundation floors.
The services bootstrap verifies the expected operation API major and concrete
`OperationSupport.implemented`; wrapper integration also checks
`EXECUTION_SUPPORT_IMPLEMENTED`. Reject missing/unimplemented integration before
business callbacks. Definition presence, package import success, provider selection,
and actual readiness are different checks.

Service/provider/consumer wheels add the applicable API dependencies and versions.
Applications require runtimes; API-only providers/clients do not. Install both
repositories coherently during development and prove the loaded module origins.
Test functional services against the foundation runtime explicitly: refusal is the
correct result, without direct-call fallback or silent disabled operation.

Provide a safe immutable setup description and managed debug reporting of descriptors,
providers/defaults/access. Make reporting available after invocation logging options
take effect. Explain failed local access/readiness checks with caller/target/phase;
do not expose ungranted metadata to children. A setup-only view reports readiness
as unevaluated. Defer a separate isolated directory diagnostic until there is an
explicit sanitized host snapshot contract.

## 8. Implementation stages and completion criteria

| Stage | Acceptance gate |
| --- | --- |
| 1. Functional core operations | Test-only handler/provider exercises real before-goal calls, A → B → C ownership, typed rejections, locks, preserved origin/latch, early completion, termination, and complete finalization. Only then advertise implemented support. |
| 2. Functional generic wrapper seam | Fake support proves setup/open/prepare/spawn/pump/close ordering, disabled blocking wait, real outcomes, finite pump turns, signals/PTY, environment and completion behavior. Only then advertise implementation. |
| 3. Portable service contracts/router | API-only facade, directories/defaults/access/readiness, full codec equivalence, scope DAG/cleanup, two-provider local example, early Python/Go and capability vectors. No broker required. |
| 4. Registry application/consumer migration | Both eclab construction paths and coherent packages; real persisted state precedes first deletion; expected failures delete nothing; consumption observes new commits and preserves N/A. |
| 5. Image migration | Owner-dispatched offers preserve readiness, authority/rejection, graph/conflict, default pull, domain fallback, adapter IDs, and data-only build workers. |
| 6. Direct-child transport | Actual Python/Go traffic, bounded framing/buffers/deadlines, fd/environment handling, child exits during work, framework failure with real outcome, and invocation services after child close. |
| 7. Proxy follow-on | Restricted descendants, fair queue expiry/admission, ID remapping, parent/peer failure, separate nested directories, and no retry/inheritance leaks. |
| 8. Packaging/docs/release preparation | All eight public distributions and examples build/install/test coherently, with new source paths in CI/type/docs checks and downstream consumer tests. Publication follows the user's release workflow. |

Retain existing framework/wrapper regression suites and add the semantic tests
deferred by the stub release. Test later reverse scope edges, partial provider failure,
cleanup calls to existing dependencies, all cleanup attempted after exceptions,
stale handles, repeated invocations, and no imports of unselected providers. Use
barriers/pipes/fake clocks instead of timing-only sleeps for concurrency and deadlines.

Run full [workspace checks](../../../AGENTS.md), all new package/Go suites, direct sibling
consumer suites, clean install checks, packaging checks, complete wheel/sdist builds,
and Twine. Update owning READMEs, root dependency/package counts from five to eight,
build/install/type/docs/CI lists, and the related
[CLI parser plan](../../goal-owned-cli-parser.md) where setup or package counts intersect.

Completion of this plan means working services and migrations have passed their
acceptance gates. A published foundation, importable service API, or successful
stub test alone is not completion of services.
