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
| A1 | Finalize generic definitions, nominal ABC/default choices and proposed goal failure reporting | Typed handler/helper consumers, non-fd resources, real textual `GoalResult` values, provenance/stub cases; no exception-valued error claim on frozen pages |
| A2 | Add concrete unsupported ABC defaults and guarded runtime stubs; reject non-`None` wrapper support | No registration acknowledged, factory called, provider activated or environment changed |
| A3 | Refresh both source inventories, then prepare the actual release/floor manifest under current version policy | Old API subclasses and legacy plugins work; resolver, origins, preflight timing and catalog metadata checked |
| A4 | Run existing full checks, builds, clean installs and downstream regressions; update owning docs | Independently complete foundation; services still unavailable |

Do not implement handlers, nested dispatch, a latch, scope manager, broker sockets
or eclab context migrations in A. A can be released and maintained indefinitely.

## B — services implementation sequence

| Step | Concrete work | Must pass before moving on |
| --- | --- | --- |
| B1 | Functional core operations and exhaustive cleanup with test-only handlers/providers | Real before-goal A→B→C ownership, frame checks, locks, origin/latch, early completion and termination |
| B3 | Local services API/runtime, canonical codecs, directory/policy and scope DAG, directly installed during goal setup | Public typed authoring fixture, API-only consumers, absent broker, Python domain vectors, cleanup dependencies and elevation policy |
| B4 | Both eclab construction paths plus registry/consumption/reclaim migration using an app-owned goal subclass | Real persistence barrier, complete snapshots, conditional observations, final recency checks, fresh polls and migration diagnostics |
| B5 | Image provider/consumer migration using the existing lookup seam | Ownership, readiness, domain ranking/fallback and data-only workers |
| B2 | Independently gated generic wrapper seam with fake support/strategy, Linux strategy and Windows stub | Non-fd resources, PTY/signals, real outcomes despite close failures, provenance and B-COMPAT |
| B6 | Portable endpoint/pump/client over transport strategies; working Unix strategy, Windows stub and selectable configuration-only broker | Non-fd fake conformance, native Windows imports/local services/stub rejection, real Unix Python/Go traffic, bounds, environment/resource cleanup and child exit during provider work |
| B7 | Explicit proxy follow-on | Fair bounded admission, independent queued expiry, ID/grant mapping and honest host-scope lifetime |
| B8 | Packaging, documentation, clean installs and release preparation | All eight public Engulf distributions and affected downstream wheels/source distributions validated |

These steps are implementation gates, not a promise of a separately published API
at every step. Freeze optional service/capability APIs only after the first concrete
consumers and protocol vectors validate them. Proxies can follow direct-child
delivery without delaying local consumer improvements.

Step IDs are retained for existing gate references; numeric order is not dependency
order. The local path is B1 → B3 → B4 → B5. B2 and B6 follow as the child path, with
an identified child consumer/grant set at T-CONSUMER; B7 depends on that working
transport. Go interoperability blocks B6, not the local migration. B-COMPAT and
B-MIGRATE are release gates for the relevant local or child milestone, and B8's
packaging work applies to each chosen release, not only after proxies.

## Sizing and implementation prerequisites

The critique's estimates (600–900 production lines for A and 5,600–8,900 for B)
are unvalidated sizing hypotheses, not measured implementation cost. Its 12/26-week
comparison has no staffing or prototype evidence. Before implementation, D-SIZE
requires the delivery owner to estimate each selected milestone including tests,
packaging and native CI, and to update that estimate after the first working slice.
Local B's critical risks are callback cleanup/attribution and domain concurrency;
the separate child path adds parsing, resource bounds, process control and Go.

Before committing to B6, prototype the bounded JSON parser against adversarial
fixtures and measured allocation reservations (T-BOUND). A failed parser spike
blocks child IPC without blocking local service adoption. Test infrastructure owners
must provide a fake Docker adapter with real state, subprocess barriers and fake
clocks (B1/B4), PTY/signal helpers (B2), a Go toolchain and shared vectors (B6), and
native Windows import/stub CI (B3/B6). None is implied by passing the design model.

## CLI-plan coordination

The wrapper maintainer owns X-CLI jointly with the parser-plan implementer. Before
either branch freezes/releases shared definitions, reconcile keyword-only constructor
additions and setup order: argument/parser registration when enabled, completion/help
from finalized metadata, then service configuration/registration before setup closes.
The exact parser contract remains that plan's decision; service integration must not
run registration twice through both subclass and helper. Test neither feature,
parser only, local services only, and both, including native completion, preemption,
editions and the elevated exact-goal opt-in. Reconcile the actual release manifest
instead of reserving contradictory numeric wrapper-API versions in two plans.

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
