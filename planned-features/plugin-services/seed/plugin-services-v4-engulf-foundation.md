# Plugin services v4, plan 1: releasable Engulf interface stubs

Status: proposed independent implementation and compatibility-rollout plan.
No source implementation, version change, or publication has been performed.

This plan and [plan 2: services](plugin-services-v4-services.md) split
[v3](plugin-services-v3.md) using the
[critique synthesis](plugin-services-v3-critique-synthesis.md). The user's new
requirement is to complete the framework interface/package transition independently
of committing to services. These two plans supersede v3's combined implementation
sequence. Earlier documents remain historical inputs and are not rewritten.

Defaults for this split are explicitly unavailable stubs and retention of the
existing plugin catalog major for additive changes. Package versions and dependency
floors advance in the rollout. A deliberate framework-major-2 cutover would be a
different compatibility policy; it is not required by the changes specified here.

Source baseline: Engulf `4bac606f1aeb3547ad64febfd1fd8068dcd994d4`. Cross-repository
architectural evidence uses engulf-clab `5f3afaec5032133e003e4e5309ab1c690450e284`.
Refresh the release inventory at implementation time; the sibling working tree
contains subsequent work and is not a release manifest.

## 1. Independently complete outcome

Engulf publishes the generic interfaces that a later services implementation needs,
with honest unsupported behavior in the runtime. Existing goals and plugins continue
to execute normally. Maintainers can update API implementations/test doubles, bump
their owned plugin distributions and dependency floors, validate the resulting
installation, and stop after this plan indefinitely.

There are no services distributions, providers, capability registries, transport
endpoints, sockets, image-provider migrations, or registry behavior changes in this
release. No application installs services integration. An attempted use of an
unimplemented feature fails explicitly before doing work; a stub never pretends a
registration or request succeeded.

Plan 2 will implement these interfaces and opt-in behavior. It may update Engulf's
internal runtime and package versions, but must not require another ecosystem-wide
API/catalog transition merely to enable the interfaces reserved here. Actual service
consumers will still need their own behavior changes, dependencies, and releases.

Publishing stubs commits to their public contracts, not to delivering services.
It also cannot guarantee that an unforeseen future redesign would be compatible.
If implementation later cannot honor a published contract, treat that as a new
explicit API decision instead of silently changing the stub's promised meaning.

## 2. Compatibility assessment

The inspected source does not force a global plugin-major break:

| Proposed change | Required transition |
| --- | --- |
| Add operation names/types and non-abstract unavailable defaults to `InvocationAPI` and `GoalSetupAPI`. | Additive API release; existing plugin callback implementations need no new methods. |
| Add a keyword-only `execution_support=None` wrapper constructor argument and reject non-`None` support while unimplemented. | Additive constructor/API release; existing call sites remain valid. |
| Add a new operation failure type while preserving `PluginCallbackError`. | Additive API release. |
| Publish and require the new package floors. | Packaging compatibility boundary: old package sets no longer satisfy the upgraded distributions. |
| Add mandatory abstract members, replace callback signatures, change existing phase meaning, or change plugin selection compatibility. | A real breaking change; deliberately excluded from this stub plan. |

Existing plugins receive callback APIs; they do not generally implement those API
classes. Adding an abstract member would primarily break runtime facades, custom
API implementations, and test doubles, and is unnecessary for an optional feature.
Use concrete unavailable defaults on existing ABCs. New standalone protocols/ABCs
can describe the future interfaces without making old implementations abstract.

Keep `PLUGIN_API_MAJOR = 1`, `EXECUTABLE_WRAPPER_API_MAJOR = 1`, stable plugin IDs,
application IDs, state namespaces, and current catalog names. Package/API version
strings change independently. A framework major change would move application,
goal-catalog, and dependency entry-point groups together and cause old catalogs to
be ignored; it is not interchangeable with a package-version bump.

Evidence: [API bases](../../../engulf-api/src/engulf_api/plugin_api.py#L37),
[runtime facade](../../../engulf/src/engulf/plugin_api.py#L40),
[wrapper constructor](../../../engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py#L261),
and [catalog construction](../../../engulf/src/engulf/plugin_loader.py#L392).

## 3. Generic operation interfaces to reserve

All types in this section belong to dependency-free, portable `engulf-api` and are
exported at its package top level. They mention no service capability, wire schema,
wrapper, socket, or concrete plugin implementation. `R` and `S` below denote the
request and response type parameters.

| Public contract | Signature or fields |
| --- | --- |
| `MANAGED_OPERATIONS_API_MAJOR` | Integer constant `1`; identifies the definitions, not runtime availability. |
| `OperationSupport` | Frozen, keyword-only record: `api_major: int`, `implemented: bool`, `reason: str | None`. Unsupported status has a nonempty reason; supported status has no unavailable reason. |
| `GoalSetupAPI.operation_support` | Read-only `OperationSupport`; existing API implementations default to unsupported. |
| `GoalSetupAPI.register_operation(definition)` | Accepts `InvocationOperation[R, S]`, returns `None` when implemented; concrete unavailable default in this release. |
| `InvocationAPI.operations` | Read-only `OperationClient`; concrete unsupported default for legacy API implementations and a guarded stub in Engulf's runtime facade. |
| `OperationClient.support` | Read-only `OperationSupport`. |
| `OperationClient.request(operation_id: str, request: object) -> object` | Synchronous generic request; request/response types are validated against the registered definition. The future API-only facade supplies capability-specific typing. |
| `InvocationOperation[R, S]` | Frozen, keyword-only definition: stable `operation_id`, `request_type: type[R]`, `response_type: type[S]`, immutable `phases` tuple of permitted invocation `GoalPhase` values, and `handler_factory: Callable[[Invocation], OperationHandler[R, S]]`. |
| `OperationHandler[R, S]` | `handle(request: R, api: OperationAPI) -> S`; `close(api: OperationAPI) -> None`. The factory creates a fresh handler per invocation. |
| `OperationCallFrame` | Frozen, keyword-only runtime-derived record: `participant_id: str`, `phase_id: str`, `operation_id: str`. Ordered frames represent the initiating caller through the current operation/provider. |
| `OperationAPI` | New restricted callback API described below; no instance is created by the stub runtime. |
| `OperationUnavailableError` | Typed `RuntimeError` for an unavailable operation implementation. Includes the requested feature and reason. It does not indicate a provider failure. |
| `OperationRequestError` | Typed rejection before or during a managed request: stable `code`, safe `message`, optional runtime-derived `target_id`, and immutable `call_chain`. Codes are `invalid_request`, `unknown_operation`, `invalid_target`, `target_not_ready`, `call_cycle`, `call_depth_exceeded`, and `lock_order`. These rejections do not set the operation failure latch. |
| `OperationFailure` | New generic failure carrier: `operation_id`, `stage`, original `error: Exception`, optional `origin: PluginCallbackError`, immutable `call_chain: tuple[OperationCallFrame, ...]`. Termination exceptions are not wrapped. |

The new `OperationAPI` extends diagnostics/application metadata only. Reserve these
read-only properties and methods:

```text
operation_id -> str
invocation -> Invocation
caller -> OperationCallFrame | None
call_chain -> tuple[OperationCallFrame, ...]
dispatch(phase, event, *, plugin_ids: Sequence[str]) -> tuple[AttributedContribution, ...]
report_failure(failure: OperationFailure) -> None
```

Dispatch has the same phase/event/contribution type relationship as `GoalAPI.dispatch`.
Its target IDs are required and must be selected participants; its phases must be
among the definition's registered invocation phases. `caller` is absent during core
finalization. `report_failure` records a failure; it does not silently transform a
successful reply or suppress an exception. All these windows and behavior are the
contract plan 2 must implement, not functionality advertised by this release.

Validate definitions as immutable local-execution contracts: qualified operation
IDs, actual request/response classes, invocation phases with unique stable IDs, and
a callable factory. Do not serialize factories, APIs, handlers, or arbitrary phases.
Metadata construction executes no handler/provider code. Keep the existing
`PluginCallbackError(plugin_id, phase, error)` constructor and fields unchanged.

### Exact runtime stub behavior

- `_RuntimeGoalSetupAPI.operation_support` checks the setup window and reports API
  major 1, `implemented=False`, and a stable reason identifying this as the
  interface-only runtime.
- `register_operation` checks that the setup window is active and then raises
  `OperationUnavailableError`. It does not store the definition, instantiate a
  handler, allocate resources, or acknowledge a successful registration.
- `RuntimePluginAPI.operations` and the inherited goal facade return a stub client
  bound to the current activation generation and owner thread. Access/use outside
  the callback, from a different thread, or in a later generation raises the normal
  lifetime/phase error before any request could run.
- Within a valid callback, its `support` reports unavailable and `request` raises
  `OperationUnavailableError`. No lookup, plugin dispatch, state access, or cleanup
  registration occurs. The unsupported base implementation used by legacy/fake API
  classes never dispatches either; only Engulf's concrete facade promises runtime
  generation/thread enforcement.
- Existing code that never uses the new members follows the old invocation path.
  No operation handlers, active-call stack, failure latch, new lock rules, or new
  mandatory finalization traversal are installed by these stubs.

Reuse `_ActivationState.require_active` and `require_current` for the new guarded
client; do not change the lifetime behavior of every existing API method in this
release. Use a local collaborator for the stub, not a published context object.
An uncaught unavailable error follows current hook/setup error handling. Availability
checks let deliberate callers provide a clear unsupported-feature result first.

## 4. Generic wrapper interfaces to reserve

Keep these contracts in `engulf-executable-wrapper-api`. They are portable imports
and local-execution contracts; descriptor fields do not promise working transport on
Windows. No services package or POSIX module is imported by the API distribution.

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

Reserve the frozen keyword-only records from the synthesis:

| Type | Fields |
| --- | --- |
| `ExecutionLaunch` | Copied immutable `environment: Mapping[str, str]` additions and `pass_fds: tuple[int, ...]`. |
| `ExecutionInterest`, `ExecutionReady` | `fd: int`, `readable: bool`, `writable: bool`; an interest must request at least one event. |
| `ExecutionProgress` | `immediate: bool`, requesting a nonblocking next turn after child polling. |
| `ExecutionEndReason` | Enum values `PREPARATION_FAILED`, `SPAWN_FAILED`, `CHILD_EXIT`, `INFRASTRUCTURE_FAILED`, `TERMINATION`. |
| `ExecutionEnd` | `reason: ExecutionEndReason`, `outcome: CallOutcome | None`; outcome is absent for a preparation failure. |
| `ExecutionSupportUnavailableError` | Typed `RuntimeError` identifying unavailable wrapper execution support. |

Export `EXECUTION_SUPPORT_API_MAJOR = 1` from wrapper-api. Export
`EXECUTION_SUPPORT_IMPLEMENTED = False` from the wrapper runtime as the explicit
implementation probe. Plan 2 changes the latter only when the seam's runtime tests
pass; the presence of the protocol classes is never an availability probe.

Add keyword-only `execution_support: ExecutionSupport | None = None` to
`ExecutableWrapperGoal`. `None` preserves the existing implementation. A non-`None`
value raises `ExecutionSupportUnavailableError` in construction before invoking
support methods, running preparation, changing the environment, or starting a child.
Never accept a helper and silently ignore it.

The selector, support setup invocation, environment scrubbing, process-loop changes,
and provider cleanup are all deferred to plan 2. The existing wrapper remains a
working executable goal while its extension point is unavailable.

## 5. Package/version rollout independent of services

The user's requested split explicitly anticipates version bumps and downstream
updates. This plan therefore replaces the earlier plan's no-bump policy for this
specific future rollout; it does not change files or publish artifacts by itself.

Baseline-compatible candidate versions are:

| Distribution | Inspected version | Candidate foundation version / required foundation floors |
| --- | --- | --- |
| `engulf-api` | `1.3.0` | `1.4.0`; keep `PLUGIN_API_MAJOR=1`, update `PLUGIN_API_VERSION`. |
| `engulf` | `0.3.0` | `0.4.0`; `engulf-api>=1.4,<2`. |
| `engulf-executable-wrapper-api` | `1.2.1` | `1.3.0`; `engulf-api>=1.4,<2`; wrapper goal major remains 1. |
| `engulf-executable-wrapper` | `0.3.0` | `0.4.0`; `engulf>=0.4,<1` and wrapper-api `>=1.3,<2`. |
| Owned plugin, capability, example, application, and aggregate distributions in the rollout | Per-project inventory | Next unused patch release for metadata-only updates; direct requirements advance to the applicable foundation floor. |

These are source-based candidates, not assertions about available hosted version
numbers. Before changing metadata, verify the configured package repository and
record actual unused versions in a rollout manifest. If a candidate is occupied,
select the next compatible unused release and propagate that exact floor throughout
the manifest. Do not overwrite an existing published artifact.

Inventory both known monorepos and the user's owned downstream plugin repositories
included in the rollout. The inspected trees contain seven distributions in Engulf
(five public packages and two examples) and 38 in engulf-clab, including API-only and
aggregate packages. Counts may change; derive the manifest from packaging metadata
and installed entry-point metadata without importing unselected plugin targets.
Additional downstream repositories must be explicit manifest entries rather than
being silently assumed covered by these two checkouts.

For each owned plugin distribution in that manifest, bump its release version and
raise only dependencies it actually has. A wrapper plugin depends on the new API
floors, not on the Engulf or services runtimes. API-only packages and aggregate
packages receive the appropriate dependency/version updates as the dependency graph
requires. Update application/runtime dependencies and aggregate plugin minimums so
a clean installation selects the intended upgraded set. Synchronize version constants,
examples, package docs, generated packaging inputs, and lock/constraints files.

Keep existing entry-point names/targets, phase IDs, packaging order declarations,
context declarations, and provider behavior. In engulf-clab, this rollout does not
replace the registry session, change consumption/sleep, remove image provider context,
or install services into either eclab constructor. Those changes belong to plan 2.

Build and validate the coherent set before rollout. Install the foundation APIs and
runtimes, then dependent capability/plugin/application packages in dependency order.
Run packaging checks with dependency wheels installed. Use clean-environment tests
to verify module/distribution origins as well as `pip check`; broad constraints and
editable leftovers are not evidence of a coherent installation. Publication is a
separate action when explicitly requested, and does not depend on plan 2 starting.

## 6. Implementation order and acceptance

1. Inventory versions, exports, custom API implementations, test doubles, goals,
   wrappers, and owned downstream packages. Record the compatibility policy and
   proposed-to-actual release mapping.
2. Add portable core definitions and concrete unavailable defaults. Implement only
   the runtime support probe, setup refusal, and guarded invocation stub.
3. Add portable wrapper contracts, the false implementation probe, and the
   constructor extension with early refusal. Keep the `None` execution path intact.
4. Type-check a test-only future consumer that imports the public APIs, implements
   an operation handler/support helper, and constructs definitions. Exercise it
   against the real stub runtime and prove that its business methods never execute.
   No services distribution is needed for this contract test.
5. Apply the foundation version/dependency rollout, update owning documentation,
   build every affected distribution, and test legacy applications/plugins on the
   new package set.

Required tests include:

- New exports/records and protocol signatures are importable and typed on Linux
  and Windows, with no runtime imports in `engulf-api` and no services dependency.
- Existing API subclasses remain instantiable without implementing new members.
  Both public default stubs and concrete Engulf stubs report unavailable clearly.
- Runtime stub clients enforce activation generation and thread ownership; setup
  handles fail after closure. No registration is acknowledged or factory called.
- `execution_support=None` preserves normal, help, completion, veto, preparation,
  signal, and child-outcome behavior. Passing a helper fails before any helper method,
  provider preparation, environment mutation, or process launch.
- Existing `PluginCallbackError`, outer result transformations, state cleanup,
  lock behavior, repeated invocation, and non-import of unselected plugins pass
  their current tests. No global failure latch is introduced.
- The complete upgraded owned plugin set is discoverable under the same catalogs
  and preserves dependency ordering. Minimal policies still work. Required package
  floors reject older API/runtime sets before any new feature is attempted.
- The upgraded eclab definition, editions, and direct `ContainerlabApp` keep their
  existing behavior with services absent. Tests do not claim the old deferred registry
  write path now has a persistence guarantee; its correction remains in plan 2.

Run the full checks in [AGENTS.md](../../../AGENTS.md), owning package suites, documentation
coverage, and affected downstream checks. Metadata changes require complete wheel
and sdist builds and Twine validation. Update the stale `completed_plugin_ids`
documentation while documenting the preserved exception shape. Fix required build/CI
coverage for the packages in this rollout, including the encryption core dependency;
do not add the three services distributions or change the public package count to eight.

This test-only consumer checks signatures and honest unsupported behavior. It does
not prove the eventual runtime semantics. That is a deliberate tradeoff of the
requested stub-first release; plan 2 must satisfy the semantic conformance tests
without quietly changing these interfaces.

## 7. Stop point and handoff

This plan is complete when the interface-only package set and owned plugin updates
are built, verified, and ready for the user's release workflow. It remains useful
even if no services work follows. No pending socket, service registration, dependency
graph, or partial runtime is left enabled.

Plan 2 receives the frozen public contracts, actual foundation versions, the rollout
manifest, contract fixtures, and the following explicit state:

```text
managed operation definitions: present, API major 1
managed operation execution: unavailable
wrapper execution-support definitions: present, API major 1
wrapper execution-support execution: unavailable
plugin catalog major: 1
services packages and eclab service migrations: absent
```

Implementing those features later advances implementation/package availability, not
the meaning of existing plugin callbacks. Raising services' runtime floor above this
stub release is required; importing the new definitions alone must never satisfy a
services compatibility check.
