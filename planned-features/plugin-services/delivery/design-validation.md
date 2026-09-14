# Validation of this design workspace

The original documentation and design models were checked on September 13, 2026
local time (September 14 UTC). The strategy refinement was checked on September 14.
These results validate this planning artifact, not an implemented services runtime.
The implementation obligations remain in
[verification](verification.md).

## Source and artifact evidence

- [source-snapshot.json](source-snapshot.json) records 27 source/guide files linked
  from the evidence index, with hashes, line counts and repository heads. Engulf
  was at `4bac606f1aeb3547ad64febfd1fd8068dcd994d4`; the sibling's final captured
  head was `4d09efc7c9c2f69cf653fe4e356613c5e2a16fff`. Reads used working files; the
  sibling changed independently during the review.
- [package-inventory.json](package-inventory.json) captures all 45 project-bearing
  metadata files returned by repository inventory: 7 in Engulf and 38 in engulf-clab.
  Source versions and direct dependencies are recorded; no index availability was
  queried and no package versions changed.
- [seed-navigation.json](seed-navigation.json) records original/repaired hashes and
  path substitutions for 105 links in seven moved seed documents. Only Markdown
  destinations were repaired; archived prose, code and historical claims remain.
- [review ledger](../review.md) records 37 counterexamples/refinements across four
  recursive passes, including the strategy boundary and the withdrawn invalid
  `GoalResult.error` carrier. Each has owning components and implementation gates.

## Executed checks

| Check | Result |
| --- | --- |
| [Executable design model](models/check_design.py) | Passed; full structured output in [results.json](models/results.json) |
| Directed graph enumeration | 4,096 graphs examined; all 543 four-participant DAGs had valid cleanup order; 2,484 cycle-forming candidate edges rejected |
| Activation counterexample | Generation/thread-only ancestor access reproduced; current-frame refusal and later valid resumption checked |
| Cleanup/failure model | All modeled finalizers attempted; first termination retained; a later success with no value could not remove the saved outcome or managed failure |
| Registry paging model | 1,207,491-byte synthetic complete inventory split into 320 pages fitting a 4 KiB payload budget; snapshot consistency and oversized-record rejection checked |
| Commit/deadline models | Three failed-batch positions blocked all modeled deletion; 36 nested-budget cases, independent queue expiry, composite deadlines and lost-first-page snapshot expiry checked |
| Model Ruff lint and format | Passed |
| Model mypy | Passed, one source file |
| Existing documentation unittest suite | Passed, one test |
| Documentation structure after strategy refinement | All 56 Markdown files reachable from the architecture; 335 local links/anchors, 53 active tables, five JSON examples and four JSON artifacts checked; fences and whitespace passed |
| Working-tree whitespace | `git diff --check` passed; untracked planning files also checked directly |

The 4 KiB paging fixture tests domain payload packing, not the size of an actual
negotiated wire envelope/READY directory. The commit model is in-memory, not proof
of filesystem persistence. The graph model is finite, not a proof of real endpoint
cleanup. Those distinctions are part of the acceptance matrix.

## Strategy refinement validation

The refinement adds four strategy pages and updates the architecture, foundation,
execution/transport interactions and acceptance gates. It specifies a working Unix
transport/Linux process strategy and explicitly unavailable Windows strategies.
The Windows IPC primitive remains undecided because this delivery only requires a
stub. Generic launch and readiness contracts now use opaque resources and a narrow
platform-support snapshot.

Documentation unittest passed again (one test); the structure/link/table/JSON audit
and whitespace checks passed. The existing model source, model results and captured
JSON artifacts are unchanged. No native strategy implementation, Windows test run
or fake-strategy runtime conformance is claimed by these documentation checks.
Those cases are required at the new A-STRATEGY, W-STRATEGY and T-PLATFORM/STRATEGY/
WINDOWS gates.

The earlier dictionary-based failure model did not detect the actual `GoalResult`
contract mismatch. Its `error` field accepts text, not `OperationFailure`. The
invalid result-carrier pseudocode has been withdrawn and the missing goal-side
reporting boundary recorded as an A freeze blocker. This is separate from the
settled platform strategy/Windows stub requirement.

## Scope of changes and remaining implementation work

This task adds the architecture workspace, component designs, pseudocode, review
ledger, source/package snapshots and one standard-library design model. It repairs
moved seed navigation. Production source, runtime behavior and package metadata
are unchanged by this task. Unrelated user deletions/moves are preserved.

Full runtime/consumer/Go tests, platform/signal tests, actual memory bounds, clean
wheel installs and wheel/sdist/Twine builds belong to A/B implementation; they were
not re-run as evidence that this design implements those features. No services
package, broker, real Docker mutation or external publication is claimed.
