# Source evidence and design assumptions

This design reviews the working source in the Engulf workspace and its sibling
`engulf-clab` checkout. The sibling checkout is being edited independently; source
paths and symbols below are the evidence anchors, not a claim that both repositories
were clean or that every historical line number still matches. A file-hash snapshot
is recorded with the [design validation](delivery/design-validation.md).

## Core contracts and dispatch

| Evidence | Observed behavior | Design implication |
| --- | --- | --- |
| [Goal contracts](../../engulf-api/src/engulf_api/goals.py), `GoalPhase`, `GoalResult` | Frozen phases hold a local adapter; generic API annotations are erased. `GoalResult` can preserve a value with framework-failed status through its constructor. | Canonical phase allowlist; no imagined runtime phase kind. Preserve actual child outcome when applying a managed failure. |
| [Public API](../../engulf-api/src/engulf_api/plugin_api.py), `GoalSetupAPI`, `InvocationAPI` | Setup and invocation capabilities are distinct ABC contracts. | New methods on existing ABCs need concrete unsupported defaults. |
| [Dispatcher](../../engulf/src/engulf/_dispatch.py), `_PhaseDispatcher._dispatch`, `_HookRunner` | Each owner is activated before its endpoint call and deactivated afterward. `None` is a valid absent generic contribution. Exception wrapping currently happens at each dispatch/hook boundary. | Reuse owner dispatch; validate required service replies in the owner adapter; preserve managed origin through outer boundaries. |
| [Capabilities](../../engulf/src/engulf/_capabilities.py), `_ActivationState`, `_LockCoordinator` | Generation/current checks protect callback-bound capabilities; coordinators track each participant's transactions/leases. Generation checks do not establish the current nested execution frame. | Add a per-invocation execution stack for the new operation path; inspect ancestor locks without transferring them. |
| [Application](../../engulf/src/engulf/application.py), `_invoke`, `_setup_goal` | Handlers do not exist yet. State destruction follows outer hooks; API closure follows destruction. A cleanup exception can bypass later unguarded cleanup calls. | Install operation lifetime before hooks, finalize before state destruction, and exhaust every finalizer while preserving the primary failure. |
| [State](../../engulf/src/engulf/state.py), `RuntimeStateStore`, `_UserStoreBackend`, `finalize_destructions` | Transactions serialize writes without rollback; ordinary reads can wait with `timeout=None`; transaction-held user-store access avoids reacquiring its store lock. Destruction collects ordinary exceptions, not all termination exceptions. | Registry service reads and writes use explicit finite user-state transactions. Do not claim all filesystem waits become interruptible. Broaden managed finalization tests to termination. |
| [Core guide](../../engulf/README.md), [API guide](../../engulf-api/README.md), [workspace instructions](../../AGENTS.md) | Core is portable; all plugin calls use the internal execution endpoint. Plugin catalogs and application selection are independent from trust. | No wrapper/service imports into core, no directory of live implementations, no claim of isolation. |

## Executable wrapper

| Evidence | Observed behavior | Design implication |
| --- | --- | --- |
| [Wrapper goal](../../engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py), `setup`, `achieve`, `_prepare`, `_execute` | Help is collected in setup. Preparation dispatches one plugin at a time and unwinds successful preparers. Process ownership and signal forwarding already reside here. | Generic support attaches at those seams; do not move `Popen` or goal lifecycle into a broker. |
| [Wrapper API guide](../../engulf-executable-wrapper-api/README.md), [runtime guide](../../engulf-executable-wrapper/README.md) | Analysis/preparation/postprocessing are separate; a failed preparation is not a call. Some registries and completion callbacks are deliberately local. | No blanket serialization requirement on existing wrapper APIs. Keep real outcomes and the disabled blocking path. |

## Registry and consumers

The originally suggested nested consumption/sleep paths are now separate packages:
`plugins/engulf-clab-consumption` and `plugins/engulf-clab-sleep`.

| Evidence | Observed behavior | Design implication |
| --- | --- | --- |
| [Registry plugin](../../../engulf-clab/plugins/engulf-clab-lab-registry/src/engulf_clab_lab_registry/plugin.py), `before_goal`, `after_goal` | Publishes a capability-free session snapshot, queues consumers' updates, and writes in the owner's later hook. Corruption currently serves an empty nonpersistent session. | Owner activation is respected for storage today, but immediate operational semantics are missing. Replace the session with fresh service reads and acknowledged writes; distinguish unknown from empty. |
| [Registry storage](../../../engulf-clab/plugins/engulf-clab-lab-registry/src/engulf_clab_lab_registry/storage.py), `SessionLabRegistry`, `StateLabRegistry` | `labs.json` version 1; keys, sorting and merge semantics; transaction writes; no inventory page or message limit. | Preserve persistence format and namespace; add bounded snapshot paging in the domain API rather than assume a full inventory fits one frame. |
| [Registry API](../../../engulf-clab/plugins/engulf-clab-lab-registry-api/src/engulf_clab_lab_registry_api/contract.py) | `LabRecord` owns typed identity/observation semantics and context access. | Capability codecs and typed clients belong in this API package; consumers still cannot read provider files. |
| [Consumption plugin](../../../engulf-clab/plugins/engulf-clab-consumption/src/engulf_clab_consumption/plugin.py), [command](../../../engulf-clab/plugins/engulf-clab-consumption/src/engulf_clab_consumption/command.py) | Runs/preempts in `before_goal`; repeatedly reads the session during two-second polling and calls `upsert`. | Managed operations must work before `goal.achieve`; every reporting iteration needs a newly persisted snapshot. |
| [Sleep plugin](../../../engulf-clab/plugins/engulf-clab-sleep/src/engulf_clab_sleep/plugin.py), [command](../../../engulf-clab/plugins/engulf-clab-sleep/src/engulf_clab_sleep/command.py) | Holds `eclab-sleep:docker`; `execute` calls session `upsert` before removing resources. That call does not yet establish persistence. | Cross-owner state work under the caller's external lease is required. Verify persisted state independently at the first deletion. |
| [Registry contribution guide](../../../engulf-clab/plugins/engulf-clab-lab-registry/CONTRIBUTING.md), [usage](../../../engulf-clab/plugins/engulf-clab-lab-registry/USAGE.md) | Expected tracking failures should not change successful deployment results; observations must be complete. | Expected storage errors become declared domain results; implementation defects still follow managed failure rules. Update documentation coherently at migration. |

## Images and application composition

| Evidence | Observed behavior | Design implication |
| --- | --- | --- |
| [Image API](../../../engulf-clab/plugins/engulf-docker-image-api/src/engulf_docker_image_api/contract.py), `IMAGE_PROVIDER_CONTEXT`, `PROVIDE_IMAGE_PHASE` | Both a shared registry of provider objects and the sanctioned owner-dispatched DockerImage goal phase exist. | Migrate the wrapper registry through owner-dispatched services; retain the separate DockerImage goal and its phase. |
| [Image resolver](../../../engulf-clab/plugins/engulf-docker-image-core/src/engulf_docker_image_core/resolver.py), `registered_provider_lookup`, `resolve_image_graph` | Registered objects are called directly; the `provider_lookup` seam already accepts attributed responses. Authority, terminal rejection and dependency resolution are domain logic. | Adapt the existing lookup seam; do not move domain ranking into generic service selection. |
| [Image build adapter](../../../engulf-clab/plugins/engulf-clab-image-build/src/engulf_clab_image_build/plugin.py), `prepare_call` | Passes shared providers to `provision_image_graph` during image-build's activation. | Obtain offers through managed calls on the invocation thread before data-only build workers run. |
| [Archive adapter](../../../engulf-clab/plugins/engulf-clab-image-archive/src/engulf_clab_image_archive/plugin.py), [vrnetlab adapter](../../../engulf-clab/plugins/engulf-clab-vrnetlab-build/src/engulf_clab_vrnetlab_build/plugin.py) | Prepared provider maps are populated before image-build and cleared by failure/after-call paths. | Separate method readiness from basic entered status, retain preparation edges, and prevent stale maps in repeated invocations. |
| [Application](../../../engulf-clab/engulf-clab/src/engulf_clab/app.py), `_containerlab_goal`, `ContainerlabApp.__init__` | Two goal-construction paths preserve application branding, policy, completion and workspace behavior. | Use one application-owned service configuration helper in both paths; no import-time discovery or setup. |

## Boundaries of this review

Observed behavior above is source-backed. The new types, protocols, resource limits,
package release candidates and migration behavior are proposed design. No live
Docker mutation, package publication, installed-index version availability check,
or working Python/Go service interoperability is claimed here. Those belong to
the implementation gates in [delivery](delivery/README.md).
