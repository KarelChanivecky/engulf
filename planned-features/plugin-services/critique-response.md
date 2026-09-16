# Assessment and revision of the v4 critique

Status: assessed and applied to the active plan. This revises documentation, not the
runtime, package metadata or release state. Implementation acceptance gates remain
open. The incoming [critique](../plugin-services-critique.md) is preserved unchanged.

The critique identifies real freeze, lifecycle, child-policy and migration gaps.
Its strongest contribution is tracing consequences across component boundaries.
Several remedies, however, assume an API limitation or execution behavior that the
current source does not have. Apply the verified problem, not every proposed fix.

## Evidence and scope

Rechecked Engulf at `4c7e95e68d822c17151633e1bef9e0dd197e2b26` and the sibling at
`f8c906317fc74a6ecae8c40866fb6571062b6189`. Unlike the incoming critique, this pass
inspected the image provisioner/worker submission, registry storage, consumption
metadata and reclaim command/Docker adapter in the sibling. The
[source evidence](evidence.md#reassessment-snapshot),
[hash snapshot](delivery/review-source-snapshot.json) and refreshed
[45-package inventory](delivery/package-inventory.md) identify those observations.
No Docker mutation or package-index availability check was performed.

The sibling also reset its versions. Its former sleep consumer was renamed to
`engulf-clab-reclaim` in `e543a30`; the current plugin and lease names are
`engulf_clab.reclaim` and `eclab-reclaim:docker`. The active plan uses those names;
the `eclab/sleep/` page path and R-SLEEP gate retain navigation continuity.

## Decisions that shape the revision

- Retain the user-confirmed A foundation and the strategy/Windows-stub scope. A's
  early API freeze has real risk, but shrinking its agreed surface is a scope change.
- Specify a goal-only reporting method; keep `GoalResult.error` textual and use its
  existing constructor to preserve values. Validate provenance through runtime
  records, never a caller's public exception fields.
- Give the shared dispatch callback boundary sole ownership of participant frames,
  including ordinary hooks and goal entry. Capture results before teardown.
- Start local adoption through goal setup: B1 → B3 → B4 → B5. Process support and
  IPC are separately gated B2/B6 work; name a child consumer before building IPC.
- Limit child grants by application policy, explicit executable opt-in and elevated
  mode. Empty grants create no endpoint. State that connection holders can delegate
  their authority and that the configuration broker does not separate privileges.
- Add conditional observation writes and a final inventory comparison before
  reclamation. Keep the remaining registry/Docker race explicit.

## Finding dispositions

“Applied” below means the plan was revised; it never means an implementation gate
passed. Gate definitions live in the [verification matrix](delivery/verification.md).

| Finding | Assessment and revision | Owning page / gate |
| --- | --- | --- |
| S1 | Applied. Removed the stale exception-valued result carrier from the authoritative contract. Proposed `GoalAPI.report_managed_failure(error, *, stage)` has an unavailable A default and a goal-bound B accumulator path. | [Contracts](managed-operations/contracts.md#goal-side-reporting-and-provenance); A-API, W-FAIL |
| S2 | Integration concern valid; mandatory API-change conclusion rejected. The existing public constructor accepts `value` with framework-failed status. Only B's result-merging sites need to change; nine unrelated classmethod sites need not all be rewritten. | [Lifecycle](managed-operations/lifecycle/README.md); W-FAIL, B-COMPAT |
| S3 | Applied. OpenChild requests only narrow frozen application grants, including method subsets. Reject any excess before allocating scope or endpoint; validate attributed broker selection and configuration. | [Directory](service-runtime/directory/README.md), [routing](service-runtime/routing/README.md); S-CONTROL |
| S4 | Applied with source corrections. Elevation needs explicit policy and tests, but goal opt-in is startup consent, not an audit of all composed code. Normal plugins/helpers already share process authority. The current strategy draft already removed public `pass_fds` and requires session ownership; strengthen the native allocation-record gate rather than treating those removed fields as current. | [Elevation](service-runtime/directory/README.md#elevation), [support](executable-support/contracts.md); S-ELEVATION, W-ENV |
| S5 | Applied. Connection possession is the principal; client-side non-inheritance is cooperation, not host containment. Require executable opt-in and omit endpoints for empty grants/unopted shells. Explicit delegation retains the connection's grants. | [Endpoints](transport/endpoints/README.md#connection-authority); T-AUTH, T-CONSUMER |
| S6 | Applied. Enumerate B1 cleanup deltas, saved values and the unused-context warning predicate. Add unchanged-plugin/no-services install and invocation cases. | [Lifecycle compatibility](managed-operations/lifecycle/README.md#b-compatibility-and-interruption-policy); B-COMPAT |
| S7 | Partially accepted. Version skews need install/preflight tests; `engulf-check-packaging` is not a resolver. Broad floors can legitimately support old consumers with newer APIs, so no universal version-pair veto is added. Application preflight runs before optional imports/new constructor keywords. | [Packaging](delivery/packaging.md#clean-install-matrix-and-detection-points); B-MIGRATE |
| S8 | Accepted risk, different remedy. A new plugin can install beside an old unintegrated app. Keep API-only plugin dependencies, document coordinated releases and detect missing registration in typed preflight before business work. A capability-API major bump alone cannot force the app's goal to register anything. | [Composition](eclab/application/README.md), [packaging](delivery/packaging.md); B-MIGRATE |
| S9 | Applied. Inventory is repository-scoped. Add a deprecation stage and selected-metadata diagnostics, followed by explicit pre-invoke refusal of legacy context consumers/providers. Inspect public ActivePlugin metadata after construction; do not invent metadata access on GoalSetupAPI or preserve a foreign-call/deferred-write fallback. | [Registry migration](eclab/lab-registry/README.md#migration-and-review), [images](eclab/image-providers/README.md); B-MIGRATE |
| S10 | Applied. Check advertised grants before directory lookup. Hidden/missing/filtered targets receive fixed `not_granted` frames; detailed local reasons remain local. | [Wire](transport/wire/README.md); T-AUTH |
| S11 | Applied. Save a validated goal result inside its callback boundary before deactivation; also define the early-result and no-result cases. | [Lifecycle](managed-operations/lifecycle/README.md); W-FAIL |
| S12 | Applied. Ordinary child-scope/session close failures are recorded, cleanup continues and after_call receives the saved actual outcome. Termination still follows the termination path. | [Process](executable-support/process/README.md#child-close-cannot-bypass-postprocessing); W-FAIL |
| S13 | Partially accepted. Add one cooperative aggregate budget and consume workspace-destruction outcomes explicitly. Retain the required exhaustive attempts and first termination, including repeated interrupts; abort-on-second-interrupt would relax that requirement. No deadline can forcibly stop synchronous Python, and core cannot invent recovery journals for arbitrary resources. | [Lifecycle policy](managed-operations/lifecycle/README.md#b-compatibility-and-interruption-policy), [scopes](service-runtime/scopes/README.md); C-CLOSE |
| S14 | Applied as a provenance constraint. Returned results never mint failure authority; only runtime-minted carriers preserve provider origin. Public/foreign carriers cannot choose blame, and plugins cannot borrow an ancestor goal's reporting API. | [Contracts](managed-operations/contracts.md#goal-side-reporting-and-provenance); C-FAIL, W-FAIL |
| S15 | Narrowing A is not adopted. The plan records the user's explicit foundation choice and accepted early-freeze risk. Add real typed handler/helper authorship fixtures and state that B-only setup must preflight A's unsupported runtime. | [Foundation](foundation/README.md#definition-freeze-gate); A-API, A-STUB |
| S16 | Partially accepted. Decide nominal ABCs/defaults and compatibility axes now. Keep support/removal properties with their narrow meaning: a future parameterized query can be added separately, so a property is not an irreversible ban on introspection. | [Operation contracts](managed-operations/contracts.md), [execution contracts](executable-support/contracts.md), [version axes](delivery/packaging.md#independent-compatibility-axes); A-API |
| S17 | Applied through explicit signatures, nominal participant detection, phase values and identity grammar. Method IDs are deliberately capability-local, matching the wire example, rather than silently inheriting seed grammar. A full public-import authoring fixture and the later transport-configuration constructor have named gates before publication. | [Descriptors](service-contracts/descriptors.md), [clients](service-contracts/clients/README.md), [worked call](service-contracts/README.md#worked-local-call); S-AUTHOR |
| S18 | Applied. Restore the explicit distinction between a transport-configuration plugin and a privilege-separation broker. | [Transport](transport/README.md), [vocabulary](architecture.md#vocabulary-and-lifetimes) |
| S19 | Planning gap accepted; numeric estimates not validated. Record the critique's estimates as hypotheses, identify infrastructure and parser risks, and gate implementation sizing per milestone. Do not adopt unsupported 12/26-week dates. | [Delivery sizing](delivery/README.md#sizing-and-implementation-prerequisites); D-SIZE, T-BOUND |
| S20 | Applied. Name wrapper/parser owners, shared constructor/setup surfaces, ordering assumptions, combined feature tests and release-manifest reconciliation. Do not silently implement or amend the separate parser proposal. | [CLI coordination](delivery/README.md#cli-plan-coordination); X-CLI |
| S21 | Applied as a specification ambiguity, not a reproduced runtime failure in an unimplemented feature. All pages now refer to one callback boundary, invoked by the existing dispatcher; the coordinator never pre-activates a managed target. | [Activation](managed-operations/activation/README.md), [dispatch](managed-operations/dispatch/README.md); C-FRAME |
| S22 | Applied with source correction. Ordinary hooks use HookRunner's own activation, not PhaseDispatcher. Both traversals and goal entry need frames. C-FRAME already named real callbacks; now it explicitly tests successful first hops and exact entry/exit counts. | [Activation](managed-operations/activation/README.md); C-FRAME |
| S23 | Applied to both repositories. Refresh versions, dependencies, entry points and hashes; retire numeric release candidates derived from the old baseline. Keep original source evidence historical and require another refresh before releasing. | [Inventory](delivery/package-inventory.md), [packaging](delivery/packaging.md); A3, B8 |
| S24 | Applied. The dictionary-overlay and failed-batch models illustrate intended outcomes but do not falsify the implementation. Downgrade those claims and prohibit all design-model results from discharging implementation gates. Preserve the useful finite graph/current-frame checks. | [Validation](delivery/design-validation.md), [models](delivery/models/README.md) |
| S25 | Claimed violation rejected after sibling inspection. `provision_image_graph` resolves before building; the executor receives only ResolvedImage arguments. The existing I-WORKER gate is strengthened with real thread/submission checks, including fallback iterations. | [Images](eclab/image-providers/README.md#offer-contract-and-lookup-seam); I-WORKER |
| S26 | Recency gap accepted; its proposed recheck is not a complete concurrency fix. Add fresh eligibility and a final snapshot comparison, abort on detected drift and explicitly retain the post-transaction race. Current image removal omits force, so the critique's deployed-container example does not by itself prove successful deletion. | [Reclaim](eclab/sleep/README.md), [snapshots](eclab/lab-registry/snapshots/README.md); R-FRESH, R-SLEEP |
| S27 | Applied with a different concurrency mechanism. Compare pre-sample canonical record fingerprints in the commit transaction for every owned writer. A conflict discards stale observations. Per-observer clocks/sequences do not order different observers; a persisted timestamp/schema change is not inherently required. | [Registry](eclab/lab-registry/README.md), [consumption](eclab/consumption/README.md); R-FRESH |
| S28 | Applied. Local setup can use an app-owned wrapper subclass; B2 is removed from the local critical path. Keep B3, which provides the router/API needed before B4. The subclass requires its own exact elevated-startup opt-in and must not double-register alongside a later helper. | [Composition](eclab/application/README.md), [delivery](delivery/README.md); S-AUTHOR, S-ELEVATION |

## Other corrections to the critique

The performance discussion charges a whole-file state read to every snapshot page.
The plan instead reads once at `begin_snapshot` and pages retained immutable data.
The 320-page fixture still demonstrates many dispatch round trips, not 320 reparses
of labs.json. The added final recency comparison is a separate explicit state read.
Paging bounds messages and retained canonical data, not Python RSS or the state API's
initial whole-file allocation.

The directory page already proposed an immutable setup snapshot for diagnostics;
the real observability gap was rendering/correlation and publication of that view,
not complete absence of introspection design. The revision requires bounded failure
chain rendering and correlation using existing request IDs. A live scope inspector
remains explicitly deferred.

## Remaining gates

No service runtime is implemented by this revision. A still needs typed consumers,
unsupported-default tests and release compatibility checks. Local B needs actual
endpoint/cleanup and registry concurrency tests. The transport configuration's final
constructor, child consumer/grants, bounded parser, Go interoperability and native
Windows stub tests remain named child-delivery gates. D-SIZE must produce a staffed
estimate before those milestones start. These limits do not leave findings silently
unassigned or turn illustrative models into proof.
