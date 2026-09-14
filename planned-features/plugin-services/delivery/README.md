# Delivery and verification

This component turns the architecture into two implementation plans with reviewable
acceptance gates. It does not authorize package publication or implement runtime
code as part of the current documentation task.

| Supporting page | Purpose |
| --- | --- |
| [Packaging and compatibility](packaging.md) | Definition/functional floors, source manifest and install matrix |
| [Source package inventory](package-inventory.md) | Current packages from both repositories, including examples/aggregate/skill packages |
| [Verification matrix](verification.md) | Contract, runtime, consumer, transport and regression gates |
| [Design models](models/README.md) | Executable counterexamples and bounded state-model checks |
| [Design validation](design-validation.md) | Results actually obtained for this design workspace |

## A — foundation implementation sequence

| Step | Concrete work | Gate |
| --- | --- | --- |
| A1 | Finalize generic core/wrapper definitions, including caller-kind, opaque strategy resources/support snapshot and the still-open goal failure-reporting boundary | Typed non-fd fake consumers, real `GoalResult` compatibility, constructor validation, public exports, Windows API imports |
| A2 | Add concrete unsupported ABC defaults and guarded runtime stubs; reject non-`None` wrapper support | No registration acknowledged, factory called, provider activated or environment changed |
| A3 | Apply owned package/version/floor manifest, preserving catalogs and application IDs | Old API subclasses and upgraded legacy plugins work; module origins and metadata checked |
| A4 | Run existing full checks, builds, clean installs and downstream regressions; update owning docs | Independently complete foundation; services still unavailable |

Do not implement handlers, nested dispatch, a latch, scope manager, broker sockets
or eclab context migrations in A. A can be released and maintained indefinitely.

## B — services implementation sequence

| Step | Concrete work | Must pass before moving on |
| --- | --- | --- |
| B1 | Functional core operations and exhaustive cleanup with test-only handlers/providers | Real before-goal A→B→C ownership, frame checks, locks, origin/latch, early completion and termination |
| B2 | Generic wrapper seam with fake support/strategy, Linux execution strategy and explicit Windows stub | Non-fd resource binding, process/PTY/signals, no double wait, every failure path, real outcomes and disabled blocking behavior |
| B3 | Optional services API/runtime, canonical codecs, directory/policy and scope DAG | API-only local consumers, absent broker, Python/Go envelope and domain vectors, cleanup dependencies |
| B4 | Both eclab construction paths plus registry/consumption/sleep coherent migration | Actual persisted-state deletion barrier, bounded complete snapshots, failed commits and fresh polls |
| B5 | Image provider/consumer migration using the existing lookup seam | Ownership, readiness, domain ranking/fallback and data-only workers |
| B6 | Portable endpoint/pump/client over transport strategies; working Unix strategy, Windows stub and selectable configuration-only broker | Non-fd fake conformance, native Windows imports/local services/stub rejection, real Unix Python/Go traffic, bounds, environment/resource cleanup and child exit during provider work |
| B7 | Explicit proxy follow-on | Fair bounded admission, independent queued expiry, ID/grant mapping and honest host-scope lifetime |
| B8 | Packaging, documentation, clean installs and release preparation | All eight public Engulf distributions and affected downstream wheels/source distributions validated |

These steps are implementation gates, not a promise of a separately published API
at every step. Freeze optional service/capability APIs only after the first concrete
consumers and protocol vectors validate them. Proxies can follow direct-child
delivery without delaying local consumer improvements.

B explicitly delivers **stubbed Windows IPC**. A working Windows native transport,
process binding or wrapper port is future work and does not block the selected B
milestones. Windows import/local-service/unavailability tests do block them. No
transport strategy is loaded solely to support local service calls.

## Definition of completion

A is complete when stubs and the compatible upgraded legacy ecosystem pass their
gates. B is complete for a selected milestone only when its actual consumers and
failure paths pass. Importable APIs, a fake helper, a model checker, or a published A
release alone are not evidence that services work.

Future implementation should update owning READMEs, build/install/type/docs/CI
source lists and package counts as packages actually arrive. Coordinate setup and
package-list assumptions with the [goal-owned CLI parser plan](../../goal-owned-cli-parser.md).
Do not replace that separate plan or unrelated concurrent work.
