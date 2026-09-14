# Critique synthesis: plugin services v3

Status: source-checked synthesis and recommendations for the next plan revision.
This document does not amend [v3](plugin-services-v3.md), alter the
[v3 critique](plugin-services-v3-critique.md), implement services, or authorize a
release. D1–D15 refer to that critique. Recommendations below are proposed changes;
the two architecture choices already made by the user remain the starting point.

Engulf evidence is pinned to `4bac606f1aeb3547ad64febfd1fd8068dcd994d4`.
Sibling evidence is pinned to engulf-clab
`5f3afaec5032133e003e4e5309ab1c690450e284` and was checked with `git show`, including
files whose current working copies have since changed. Relative source links are
navigation aids; the named commits define the evidence. See the reproducibility
section below.

## Assessment

Keep v3's generic managed-operation facility, plugin callers, and synchronous
acyclic provider chains. The registry and image workflows justify them: consumption
and sleep finish in `before_goal`, while image-build requests providers from its
own preparation callback. Neither can use the existing goal-only dispatch API
directly. Moving behavior out of shared context remains the correct direction.

The critique identifies real delivery and contract gaps. The most useful remedies
are to name the application integration, define a coherent development installation,
exercise public interfaces before finalizing them, and specify failure propagation
and readiness ordering. These are requirements at different stage boundaries, not
reasons that no development stage can begin.

Three claims in the critique need correction:

- **D4 overstates the existing result-transform guarantee.** Workspace destruction
  already has a post-`after_goal` failure override. The new operation latch needs
  explicit scope and documentation, but it does not introduce the first such
  override into core.
- **D9 mistakes a deadline field for an execution bound.** A cooperative deadline
  does not preempt a provider. The proposed 24-hour maximum neither bounds nor
  determines the wrapper's worst-case unresponsiveness; a blocked callback can
  outlast even a 30-second request deadline.
- **The verified lock discussion assumes finite waits that current APIs do not
  require.** Existing lease and transaction timeouts accept `None`. The stack rules
  correctly preserve framework lock order, but finite provider waits remain an
  implementation obligation, not an existing universal guarantee.

These corrections strengthen the critique's practical recommendations while
avoiding unnecessary changes to unrelated applications or the transport protocol.

## Application integration and delivery: D1, D2, D6

### D1 — Accept the missing delivery mechanism; correct the release claim

The missing dependency-floor mechanism is real. Consumption and sleep currently
require `engulf-api>=1.2,<2` and wrapper-api `>=1.2,<2`; such ranges cannot distinguish
two source builds with the same version and different APIs. `pip check` alone cannot
prove that managed operations exist. However, the migrations can be developed and
installed from a coherent unreleased source set. A hosted release is not a
prerequisite for implementation or integration tests.

Specify the development path before beginning either migration:

1. Use a fresh integration virtual environment with a manifest recording both
   checkout revisions and all participating local distributions.
2. Install the core/API, wrapper/API, services/API/runtime, capability APIs, eclab
   application, and migrated provider/consumer wheels from that source set. For
   editable development, explicitly select every changed distribution by path in
   the same environment. Do not let an index satisfy a changed member accidentally.
3. Check dependency resolution and assert the loaded distribution/module locations.
   Run the application construction and real managed-call tests in this environment.
4. Land the Engulf facility with its first consumer first. Then land the eclab
   integration together with each producer/consumer migration and its tests. Keep
   a source-integration CI job across the two pinned revisions until release floors
   can express the dependency.

Add an early compatibility guard to the services integration bootstrap. It verifies
the managed-operation API contract and the concrete setup bridge before provider
registration or invocation work, and emits a specific compatibility error naming
the missing contract and installed packages. Check concrete support, not just a
distribution version or a base-class attribute. Import ordering matters: run the
guard before importing helper modules that unconditionally require new API exports,
or the intended diagnostic will be replaced by an `ImportError`.

Keep the API addition optional for existing API implementations: new operation
entry points should have an explicit unsupported default, rather than new mandatory
abstract members that prevent an older runtime from constructing its API facade.
The default advertises no operation support; the new runtime advertises the concrete
supported operation contract. Exercise this distinction in the mixed-version tests.

Test an older coherent core/API pair with the new integration, a partially mixed
API/runtime pair, and the supported source set. A failure must identify installation
compatibility before any provider business callback. A plugin consumer must also
detect a goal that omitted the services operation before beginning its command;
installing compatible libraries alone does not install goal integration.

Keep current no-bump instructions. Development artifacts are not release artifacts.
At the separately authorized release, update versions and dependency floors across
the coherent set, including the eclab application. Remove neither source-integration
tests nor explicit unsupported-goal errors after floors become available.

Evidence: [consumption packaging](../../../../engulf-clab/plugins/engulf-clab-consumption/pyproject.toml),
[sleep packaging](../../../../engulf-clab/plugins/engulf-clab-sleep/pyproject.toml), and
[current setup API](../../../engulf-api/src/engulf_api/plugin_api.py#L112).

### D2 — Accept; include both application construction paths

The missing owner is concrete:
[engulf-clab/src/engulf_clab/app.py](../../../../engulf-clab/engulf-clab/src/engulf_clab/app.py).
It constructs the wrapper in two places: `_containerlab_goal()` at line 80, used by
`CONTAINERLAB_APPLICATION` and editions, and `ContainerlabApp.__init__()` at line
107, which constructs another `ExecutableWrapperGoal` at line 134. Changing only
the factory would leave the supported direct application API inconsistent.

Factor their services configuration/construction into one application-owned helper
and use it in both paths. Preserve each path's binary, completion, metadata, policy,
and workspace options, and keep import-time behavior free of discovery/setup.

The first eclab integration needs this policy:

| Capability | Accepted providers and local callers | Child access |
| --- | --- | --- |
| Lab registry | Accept the canonical registry descriptor; allow consumption and sleep to read and commit through `engulf_clab.lab_registry`. The registry's own observation code uses its owned storage directly. | Empty. |
| Image offers | Accept the canonical image-offer descriptor and explicitly installed recipe codecs; allow `engulf_clab.image_build` to enumerate/call selected, compatible wrapper provider adapters. | Empty. |

Use the selected compatible provider set, not discovery during lookup. Image offers
have no generic service default: their domain resolver ranks all responses. The
registry has one intended provider. Require it when a selected consumer needs it;
do not install an unconditional default that makes a custom edition with neither
consumer nor registry fail setup. Preserve exact local caller checks and the
application's deliberate provider selection when editions add compatible adapters.

Add the services runtime/wrapper integration and capability API dependencies to the
application distribution. Integration without the child broker must be sufficient
for all these migrations. Test the standard definition, an edition, direct
`ContainerlabApp`, and a deliberately minimal plugin policy.

### D6 — Accept the general rule; the named consumers already satisfy it

At the pinned sibling commit, both consumption and sleep already declare:

```toml
"engulf_clab.lab_registry" = "preprocess=before; postprocess=none"
```

Archive and vrnetlab providers also explicitly place image-build after themselves
using `preprocess=after` on their image-build dependency. There is no evidence that
these particular consumers currently rely only on priority.

State the general rule explicitly: a consumer that requires a provider during
`before_goal` must establish a packaging dependency that places the provider first.
For runtime-selected alternatives, every selectable alternative must have a declared
ordering path, or the call must be moved to a phase after all candidates initialize.
This expresses real lifecycle ordering, not a service preference. Likewise, offer
readiness after provider preparation requires the appropriate preparation order.

Do not add a consumer dependency on every optional image provider merely to force
ordering; that would make absent optional providers required. Keep provider-owned
edges to the shared image-build consumer where appropriate. Test resolved order
and readiness with different selected sets; retain `ProviderNotReady` as a guard,
not the expected way to discover missing ordering declarations.

Evidence: [consumption dependency](../../../../engulf-clab/plugins/engulf-clab-consumption/pyproject.toml#L30),
[sleep dependency](../../../../engulf-clab/plugins/engulf-clab-sleep/pyproject.toml#L30),
[archive dependency](../../../../engulf-clab/plugins/engulf-clab-image-archive/pyproject.toml#L32),
and [vrnetlab dependency](../../../../engulf-clab/plugins/engulf-clab-vrnetlab-build/pyproject.toml#L33).

## Contracts, result precedence, and cleanup: D3–D7

### D3 — Accept consumer-led gates; stages are not separate releases

Public package ownership is not evidence that every intermediate commit freezes a
released contract. V3 explicitly defers publishing. Nevertheless, each interface
should have a real consumer before its design is declared complete:

- Deliver the minimal API-only service facade and a state-owning test provider with
  the generic core facility. Exercise a call from `before_goal`, an A → B → C chain,
  early completion, and cleanup through the real endpoint. Typing alone is not the
  acceptance gate.
- Deliver Python and Go envelope encoder/decoder vector runners with the protocol
  specification, before transport. Add capability payload vectors as each portable
  capability is defined. Neither runner needs a socket or an image build engine.
- Specify and type-check the wrapper seam against a fake execution-support consumer
  before implementing transport. Preserve the ordinary blocking wait when there is
  no execution session.

The wrapper contract should commit to the following proposed signatures. These
resolve the ambiguity in v3; they are not existing exports:

```python
class ExecutionSupport(Protocol):
    def setup(self, api: GoalSetupAPI) -> None: ...

    @property
    def environment_removals(self) -> frozenset[str]: ...

    def open(
        self, event: PreparedCallEvent, api: GoalAPI
    ) -> ExecutionSession | None: ...


class ExecutionSession(Protocol):
    @property
    def launch(self) -> ExecutionLaunch: ...

    def spawned(self, pid: int) -> None: ...
    def interests(self) -> tuple[ExecutionInterest, ...]: ...
    def step(self, ready: tuple[ExecutionReady, ...]) -> ExecutionProgress: ...
    def stop(self, reason: ExecutionEndReason) -> None: ...
    def close(self, end: ExecutionEnd) -> None: ...
```

Define frozen, keyword-only value records alongside these protocols:

| Type | Fields and meaning |
| --- | --- |
| `ExecutionLaunch` | Immutable `environment: Mapping[str, str]` additions and `pass_fds: tuple[int, ...]`. Copy/freeze the mapping on construction. |
| `ExecutionInterest` / `ExecutionReady` | `fd: int`, `readable: bool`, `writable: bool`; interests request events, ready records report them. Reject an interest requesting neither event. |
| `ExecutionProgress` | `immediate: bool`; true requests another pump turn without blocking, after the wrapper polls the child. This covers buffered input and deferred responses. |
| `ExecutionEndReason` | Enum: preparation failure, spawn failure, child exit, infrastructure failure, termination. |
| `ExecutionEnd` | `reason: ExecutionEndReason`, `outcome: CallOutcome | None`; a real outcome exists after an attempted launch, never for failed preparation. Error objects/precedence remain in wrapper/core failure bookkeeping. |

Do not pass a `Popen`, reaping handle, or live plugin to support code. `close` returns
`None`; failures propagate to wrapper/core bookkeeping while all required cleanup
continues. The wrapper invokes support on the invocation owner thread, outside any
broker/provider callback. Local dispatch still goes through the registered operation
bridge; transport support never gains raw plugin access.

### D4 — Partly accept; explicitly limit the new latch

The critique stops its analysis too early. After the invocation `finally`,
[`application.py:862`](../../../engulf/src/engulf/application.py#L862) already returns a
framework failure if workspace cleanup failed. The existing
[cleanup precedence test](../../../engulf/tests/test_state.py#L294) exercises this path.
Thus `after_goal` is not unconditionally the last word today, even though the
numbered lifecycle description should explain its exceptions more clearly.

The recommended rule is narrower than a universal failure latch:

- Registering operations enables their mandatory finalization. Only actual managed-
  operation/provider contract or infrastructure failures set the new latch.
- No registered operations means no new latch behavior. Existing ordinary goal/hook
  failures, result transformations, and workspace-cleanup precedence remain as they
  are. Merely registering an unused operation also does not make unrelated failures
  sticky.
- Declared domain errors and rejected requests never set this latch. An actual
  latched operation failure cannot be erased by a caller or later middleware.
- Run ordinary after hooks, close managed handlers, finalize state cleanup, then
  construct the final ordinary result with applicable failures taking precedence.
  Preserve the real result value where available. Termination exceptions still
  propagate after mandatory cleanup rather than becoming results.

Update the lifecycle's numbered sequence and result-transform documentation to name
both the existing cleanup override and the new opt-in operation override. Test
unintegrated applications, integrated applications with no operation failure, caught
provider failures, and combined operation/state-cleanup failures. The services work
does not need a separate universal result-policy change.

### D5 — Accept; introduce a generic operation failure carrier

Prefer a new `OperationFailure` in `engulf-api` to changing the meaning of the
existing three-argument `PluginCallbackError`. The new type is service-independent
and carries the original `PluginCallbackError` when a provider failed, an immutable
ordered call chain, and the operation/stage for an infrastructure failure without a
provider origin. Each frozen call frame records participant ID, active phase ID,
and operation ID. Capture frames before unwinding the activation stack.

Keep `PluginCallbackError.plugin_id`, `.phase`, `.error`, and its constructor
unchanged. The operation bridge turns an attributed provider callback failure into
`OperationFailure` once and records it in the invocation latch. Local callers receive
that generic typed failure unchanged; the optional transport maps it to the safe
provider/infrastructure wire error. Expected capability errors continue through the
ordinary service reply path.

Add explicit handling in the phase dispatcher, both outer hook runners, and the goal
execution boundary before their generic `Exception` handlers. Passing a runtime-
recorded operation failure through these boundaries must not rewrap it as the current
caller or log it again. Core recognizes its own type and invocation failure record;
it does not import services exceptions or infer attribution from exception strings.
If a caller catches the failure and raises a separate defect, that defect may receive
its own diagnostic, but the original provider failure remains latched.

Test both an uncaught C failure through B/A and one caught by a caller that returns
success. Assert origin, chain, diagnostic count, final status, and cleanup. Include
operation infrastructure failures with no provider to avoid manufacturing attribution.

Evidence: [current error type](../../../engulf-api/src/engulf_api/errors.py#L13),
[hook runners](../../../engulf/src/engulf/_dispatch.py#L117),
[phase wrapper](../../../engulf/src/engulf/_dispatch.py#L230), and
[goal exception boundary](../../../engulf/src/engulf/application.py#L808).

### D7 — Accept the documentation gap; retain the chosen acyclic policy

V3 intentionally imposes two restrictions: no active recursive call and no dependency
cycle within a resource scope. After A has called B in a scope, B cannot later call A
in that same scope even after the first request returned. This can be a runtime,
call-order-dependent rejection and must be documented prominently for capability
authors. A new invocation resets the graph; changing scope is not a way to smuggle
resource dependencies across incompatible lifetimes.

Retain this policy. If A needs B during cleanup and B needs A, ordering strongly
connected components does not define a safe order inside their shared component.
First-use ordering also cannot ensure either dependency remains usable. Supporting
cycles would need another lifecycle contract, such as separating dependency-using
quiescence from final disposal. That is additional design, not a drop-in graph
algorithm, and was not the user's selected call-chain model.

Providers needing bidirectional interaction should factor shared behavior into a
third provider or have an orchestrating caller coordinate the sequence. Test the
later reverse edge as well as active recursion and existing-dependency cleanup.

The lock-stack rules remain justified by existing lease-before-transaction and
no-overlapping-lease rules in
[`_LockCoordinator`](../../../engulf/src/engulf/_capabilities.py#L311). Reuse
[`require_current`](../../../engulf/src/engulf/_capabilities.py#L114) for generation checks
and add thread ownership; do not invent a second generation mechanism. Limit the
claim to preventing introduced framework lock inversion. Arbitrary external I/O and
cooperating code outside these rules remain separate concerns.

## Transport and interoperability: D8–D11, D13

### D8 — Accept the sizing test; neither a larger floor nor paging follows yet

A minimum legal receive limit is not a promise that every legal client can accept
every application's directory. A client choosing 4 KiB may legitimately be unable
to use a larger directory. The standard client can default to the proposed 1 MiB
frame limit while a deliberately constrained client accepts the smaller supported
service set. Making this compatibility condition explicit is necessary.

The critique does not establish the image directory's encoded size. A directory
contains declarations and codec identifiers, not actual image requirements, recipe
instances, paths, or build graphs. Also, the eclab image migration is local and the
application policy above grants nothing to Containerlab. It does not require a
4 KiB Go client to receive image capabilities.

Keep the separate 4 KiB HELLO bootstrap bound and 1 MiB standard receive default.
Before freezing the wire schema, serialize worked minimal, demo, registry, and image
directories, including all supported recipe codec declarations, and record their
exact UTF-8 byte sizes in conformance fixtures. Test READY at the chosen peer limit
and a bounded, intelligible handshake rejection when the directory does not fit.
Required codec schema material must be accounted for if the final wire descriptor
carries it; do not estimate from Python class definitions.

Retain the 4 KiB opt-in receive floor unless these fixtures reveal a specific
compatibility requirement that it cannot serve. Do not add paging or a directory-fetch
operation solely to make every valid limit work for every directory. Either addition
would introduce protocol states, requests, and lifetime behavior beyond the observed
problem. A handshake-size test belongs in the early protocol gate, not late transport
debugging.

### D9 — Reject the claimed bound; fix the actual responsiveness obligations

Changing 86,400,000 to a smaller number cannot make a synchronous provider return.
The wrapper cannot poll, enforce a timeout, or inspect a deadline while the same
thread is blocked inside the provider. V3 already calls deadlines cooperative; the
critique's claim that this number is the worst-case polling bound is incorrect.

Current core also accepts unlimited lock waits:
[`_validate_lock_timeout(None)`](../../../engulf/src/engulf/state.py#L751) returns `None`,
and [`_timeout_deadline`](../../../engulf/src/engulf/state.py#L767) then produces no deadline.
The existing registry uses
[`state.transaction()` without a timeout](../../../../engulf-clab/plugins/engulf-clab-lab-registry/src/engulf_clab_lab_registry/storage.py#L72).
Consequently the critique's claim that both lock kinds already have finite waits
must not become the justification for a responsiveness guarantee.

Separate three controls in the next revision:

1. The wire integer ceiling is a validation limit. Retaining 24 hours there does
   not grant a caller a 24-hour operation or promise a 24-hour execution bound.
2. The application sets the effective request budget. Use 30 seconds by default
   for the initial registry/offer integration; larger budgets require explicit
   application policy rather than merely a larger incoming field. Nested calls
   cannot extend the originating deadline.
3. Providers use explicit finite lock/external-I/O timeouts within the remaining
   budget and check deadlines between steps. Audit the actual acquisition paths;
   an outer timeout does not automatically bound an internal wait. Keep image
   builds out of the offer callback and keep registry transactions short.

Test finite lock contention, slow cooperative providers, and a callback held behind
a deterministic barrier while the child exits. The test must demonstrate delayed
observation, then correct revocation/reaping once the callback returns. Do not label
the request deadline or 100 ms selector interval as a hard responsiveness bound.
Hard preemption needs an isolated/asynchronous execution design and remains outside
this implementation.

### D10 — Accept recoverable queue failure; reject unknowable scheduling promises

Sixteen clients sharing an upstream connection do not necessarily exceed 30 seconds;
their service times determine that. Conversely, the proxy cannot know that a request
will start in time merely because earlier requests have deadlines: those deadlines
do not preempt their execution. There is no general admission-time prediction
available from v3's metadata.

Specify implementable semantics instead:

- Admit into a bounded, fairly scheduled queue only while capacity and a positive
  remaining budget exist. At capacity, return correlated `resource_exhausted`
  without closing an otherwise healthy downstream connection.
- Run queue deadline timers independently of the serialized upstream response wait.
  A request that expires before forwarding receives correlated `deadline_exceeded`,
  is known not to have been dispatched upstream, and leaves the connection usable.
- Recheck immediately before the first upstream byte; subtract all local elapsed
  time. If transmission has begun, retain the outcome-unknown and no-retry rules
  when its channel/deadline fails.

Advertised cost estimates could support stricter policy later, but do not treat
them as execution guarantees. Test a blocked upstream request and a second request
that expires while queued; the second must fail promptly without upstream execution
or unrelated peer revocation. These requirements apply when the proxy milestone is
implemented, not to the initial local-services gate.

### D11 — Accept; define a closed error-kind taxonomy

Adopt this proposed wire taxonomy, with capability-owned codes confined to the
domain kind. The shared schema and Python/Go vectors must fix spelling and behavior:

| `error.kind` | Codes or responsibility | Connection/result behavior |
| --- | --- | --- |
| `request` | `invalid_request`, `missing_provider`, `ambiguous_provider`, `not_granted`, `not_ready`, `unsupported_method`, `call_cycle`, `call_depth_exceeded`, `resource_exhausted`, and pre-dispatch `deadline_exceeded`. | A valid correlated rejection is recoverable; no framework latch. |
| `domain` | Codes declared by the capability, such as unavailable inventory or commit failure. | Recoverable request failure; the caller's domain decides the command result. |
| `provider` | `provider_failure`: unexpected provider defect or invalid reply. | Record the original provider failure, latch framework failure, and revoke affected transport as specified. |
| `infrastructure` | `broker_failure`: internal operation/router/transport support defect. | Latch framework failure without forging provider attribution. |
| `protocol` | Version, handshake, envelope-order, framing, and response-correlation violations. | Close the affected connection; send a bounded error only when the protocol state permits it. Peer misuse alone does not latch framework failure. |

Transport disappearance, absent endpoints, and uncertain outcome after timeout are
typed local client conditions; do not invent an error frame on a dead channel.
Malformed bytes without a usable correlation ID are not ordinary correlated
`request` errors. An invalid caller payload is different from a provider generating
an invalid result. Wire category alone is not authority to mark an invocation
failed: trusted server-side failure bookkeeping remains authoritative.

### D13 — Accept separate payload vectors; correct the Go scope assumption

Envelope conformance cannot prove that a path, set, authority value, rejection,
recipe, or registry record has the same meaning across implementations. Every
capability API claiming portable payloads should own versioned positive and negative
vectors, separately from transport vectors. Each includes raw JSON bytes, the
expected normalized logical value or error, and the expected round-trip behavior.

Exercise registry paths/sets/history and image parameters, every accepted recipe
kind, offer/reject/no-opinion, authority, and fallback metadata. Include absent versus
null fields, unsupported kinds, invalid types, and boundary cases. Bind vectors to
the same codec identities and capability major as the directory declarations.

Run the capability vectors through the production Python codecs and independent Go
codec/vector adapters before declaring their portable contract complete. A generic
Go JSON parser alone does not validate domain semantics. This is data-codec work;
it does not require a Go registry implementation or a Go image build engine.

The critique overstates v3 when it says section 6 already requires a Go-side image
consumer. The selected Go demonstration uses a small separate capability. Preserve
that scope while making the portability claim for real capability payloads testable.

## Operator visibility and staged scope: D12, D14

### D12 — Accept the operational need; do not assume the diagnostic can see services

The current [plugin-list diagnostic](../../../plugins/engulf-plugin-list/src/engulf_plugin_list/__init__.py#L14)
reads sanitized plugin execution/provenance records. Neither
[`DiagnosticRequest`](../../../engulf-api/src/engulf_api/diagnostic_extensions.py#L15) nor
[`DiagnosticAPI`](../../../engulf-api/src/engulf_api/diagnostic_extensions.py#L133) carries
the services directory, grants, or invocation readiness. A new diagnostic wheel
cannot discover that state just by following plugin-list's packaging pattern.
It must not import live host plugins or reach around the worker's isolation.

For the initial implementation, expose a deterministic setup description through
the services helper and emit it with managed debug logging: accepted capabilities,
selected registered provider IDs, advertised methods, configured defaults, and local/
child access decisions. Use the existing logging controls; keep endpoint descriptors,
payloads, state contents, and secrets out of it. Report readiness as unevaluated
before invocation, not false or ready merely because registration succeeded.
Capture the description during setup, but make debug reporting available after
invocation logging controls take effect; logging it only during application
construction would hide it from normal command-line verbosity controls.

At a failed local request, managed diagnostics identify the caller, target, capability,
method, phase, and the specific failed readiness/access check. Child errors expose
only permitted metadata. This gives an operator a useful explanation without a
debugger and without adding a fourth services distribution.

Defer a dedicated isolated directory diagnostic. If added later, it needs an explicit
host-generated sanitized snapshot contract and tests proving it neither runs provider
business logic nor fabricates invocation readiness. Log/describe output is inspection
of configuration, not a claim that a provider's resources are currently ready.

### D14 — Accept a separate proxy milestone; do not silently remove its requirements

None of the registry, consumption, sleep, or image migrations needs descendant
proxying. The first Go interoperability demonstration needs only a direct child.
Proxy scheduling, downstream ownership, grant filtering, ID translation, and failure
cascades therefore need not block either local services or direct-child validation.

Recommend separate acceptance milestones: local migrations, direct-child transport,
then explicit proxying. Keep v3's proxy requirements as a follow-on deliverable,
including the restricted descendant example, rather than declaring them implemented
or deleting them from an already agreed plan. Preserve IDs, grant triples, deadline
budgets, and endpoint noninheritability in the first wire version so proxy support
can be additive.

Do not partially implement implicit descriptor forwarding as a substitute for a
proxy. Until that milestone is complete, descendants receive no services endpoint
automatically. This reduces the first delivery's critical path without changing the
chosen managed-call architecture or claiming that proxy behavior is free.

## Reproducibility and the unreviewed migrations: D15

Accept the criticism of v3's phrase "together with the inspected working-tree state."
Replace that phrase in the next revision with committed evidence for factual claims
and a separate, explicitly identified note for later working-tree observations.

The central sibling claims are reproducible at the commit already named by v3:

| Committed evidence | Verified behavior |
| --- | --- |
| [Registry storage](../../../../engulf-clab/plugins/engulf-clab-lab-registry/src/engulf_clab_lab_registry/storage.py#L16), lines 16–83 | `SessionLabRegistry` contains records/pending updates and no retained state capability. `upsert` queues; `StateLabRegistry.upsert` performs the transaction/write. |
| [Registry lifecycle](../../../../engulf-clab/plugins/engulf-clab-lab-registry/src/engulf_clab_lab_registry/plugin.py#L66), lines 66–118 | Read failure publishes a nonpersistent snapshot; pending writes are attempted later in `after_goal`. |
| [Sleep execution](../../../../engulf-clab/plugins/engulf-clab-sleep/src/engulf_clab_sleep/command.py#L148), lines 148–175 | `registry.upsert` returns before container/image deletion begins. With the real session implementation, this is not a persistence acknowledgement. |
| [Image-build preparation](../../../../engulf-clab/plugins/engulf-clab-image-build/src/engulf_clab_image_build/plugin.py#L216), committed lines 216–242 | The wrapper passes `providers=image_providers(api)` to provisioning. |
| [Image resolver](../../../../engulf-clab/plugins/engulf-docker-image-core/src/engulf_docker_image_core/resolver.py#L75), lines 75–91 | The lookup directly invokes `registered.provider.provide(requirement)`. |
| [Application construction](../../../../engulf-clab/engulf-clab/src/engulf_clab/app.py#L80), lines 80–153 | Both the standard factory and direct application constructor omit services integration. |

These checks close the v3 critique's stated sibling-verification gap for the
architectural claims above. They do not claim that all future migration behavior
already exists or that the changing sibling working tree is the pinned baseline.
In particular, current image/provider working files have subsequent edits; a current
line link may navigate differently from the committed excerpt.

Reproduce an excerpt without modifying either checkout:

```console
git -C ../engulf-clab show 5f3afaec5032133e003e4e5309ab1c690450e284:engulf-clab/src/engulf_clab/app.py
git -C ../engulf-clab show 5f3afaec5032133e003e4e5309ab1c690450e284:plugins/engulf-clab-lab-registry/src/engulf_clab_lab_registry/storage.py
git show 4bac606f1aeb3547ad64febfd1fd8068dcd994d4:engulf/src/engulf/application.py
```

Commands assume the Engulf workspace root. No commit, reset, or patch of the sibling
working tree is needed to establish this evidence.

## Recommended sequence and acceptance gates

| Gate | Work that must be concrete before proceeding |
| --- | --- |
| Core facility and first consumer | Generic operation contracts plus minimal services facade/provider, concrete failure type, opt-in latch behavior, generation/thread/lock checks, acyclic cleanup, and real lifecycle tests. |
| Portable contracts | Canonical capability APIs, setup/readiness/access rules, Python/Go envelope runners, per-capability vectors, exact error kinds, and serialized directory fixtures. This work can evolve with the local vertical slice before any release. |
| Registry migration | Coherent two-repository environment, compatibility diagnostics, both eclab construction paths, required ordering, real registry commit acknowledgement, consumption refresh, and persisted-state inspection before the first fake Docker deletion. |
| Image migration | Application-accepted codecs, selected wrapper adapter identities, preparation readiness/order, managed offer enumeration, and unchanged domain resolution/fallback behavior. |
| Direct-child transport | Fully typed wrapper seam exercised by a fake helper, bounded protocol implementation, actual Python/Go traffic, child outcomes/signals/PTY/environment checks, and local services still usable after child scope close. |
| Proxy follow-on | Independent queue timers/admission errors, fair upstream serialization, restricted grants, ID remapping, crash/revocation tests, and the explicit descendant example. |
| Release preparation | All package/build/type/docs checks, clean installation of the coherent set, versions and floors updated only under separately authorized release work. |

This sequence makes the added work visible: core lifecycle changes, application and
plugin migrations, protocol/interoperability, and process/proxy handling are separate
integration risks. It does not assign speculative calendar estimates or make the
last milestone a prerequisite for proving the first.

## Finding disposition

| Finding | Synthesis |
| --- | --- |
| D1 | Accept missing development/install/compatibility path; reject the claim that unreleased cross-repository code cannot be installed. |
| D2 | Accept; update both eclab construction paths with application-owned policy and dependencies before migrating consumers. |
| D3 | Accept executable consumer gates and exact seam signatures; distinguish unreleased development stages from publication. |
| D4 | Partly accept; existing workspace cleanup already overrides results. Scope the new latch to actual operation failures and document both overrides. |
| D5 | Accept; use a generic `OperationFailure` carrier with immutable call frames, preserving `PluginCallbackError` compatibility and avoiding duplicate attribution. |
| D6 | Accept the general readiness-order rule; consumption/sleep and the inspected image providers already declare relevant edges. |
| D7 | Accept disclosure of the runtime restriction; retain the agreed scope DAG because SCC/first-use order does not solve dependency-using cleanup. |
| D8 | Accept measured directory fixtures and explicit constrained-client failure; a larger mandatory floor or paging is not established as necessary. |
| D9 | Reject the alleged execution bound; separate wire limits, application budgets, and finite provider waits, while acknowledging cooperative execution. |
| D10 | Accept bounded, recoverable queue failures; replace admission-time prediction with independent expiry and pre-forward checks. |
| D11 | Accept; fix the request/domain/provider/infrastructure/protocol taxonomy in schemas and vectors. |
| D12 | Accept the visibility need; deliver safe setup description/debug output and reason-specific diagnostics, deferring a new isolated snapshot extension. |
| D13 | Accept payload-level vectors in capability packages; a Go data-codec adapter is sufficient, without a Go image execution engine. |
| D14 | Recommend a separate proxy milestone while preserving the agreed follow-on requirements and first-version wire affordances. |
| D15 | Accept reproducibility correction; verify the relevant sibling claims directly against the existing pinned commit. |

The next plan revision should incorporate these decisions in the sections they
change, then update its acceptance gates and disposition table. Neither this
synthesis nor a source-level agreement marks an implementation finding resolved.
