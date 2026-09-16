# Recursive architecture review

This ledger records the review performed while expanding the seed plans. Findings
are proposed design resolutions, not fixes already implemented in Engulf. Source
evidence is indexed in [evidence.md](evidence.md); acceptance IDs refer to the
[verification matrix](delivery/verification.md).

## Pass 1 — ownership, public contracts and source seams

| ID | Counterexample / flaw | Design resolution and owner | Gate |
| --- | --- | --- | --- |
| R01 | Generation/thread checks accept a suspended ancestor's client in B's same-thread callback. | Require the actual current participant/handler frame; [activation](managed-operations/activation/README.md). | C-FRAME |
| R02 | A service control payload claims a goal identity or relies on a reserved ID prefix. | Add runtime `OperationCallerKind` to the unpublished foundation frame; goal-only host controls use it. [Contracts](managed-operations/contracts.md). | A-API, S-CONTROL |
| R03 | A phase ID matches but its replacement object contains a different callback. Python generic phase API types are erased. | Freeze exact phase objects; do not claim runtime annotation inspection. [Dispatch](managed-operations/dispatch/README.md). | C-PHASE |
| R04 | `None` passes generic contribution handling; result encoding outside activation loses the clear owner boundary. | Required explicit reply and trusted canonical codec validation inside the owner adapter. [Descriptors](service-contracts/descriptors.md). | C-PHASE, S-CODEC |
| R05 | Provider C fails, then B's deactivation fails and masks C/termination. | Capture primary outcome before exhaustive cleanup; preserve original carrier and first termination. [Lifecycle](managed-operations/lifecycle/README.md). | C-FAIL, C-CLOSE |
| R06 | Finalization loops run in `finally` but one API close/destruction termination prevents later cleanup. | Attempt every finalizer individually, not merely wrap a sequence in `finally`. Same lifecycle owner. | C-CLOSE |
| R07 | Service entry validates locks, but a provider acquires a new external lease later. | Cross-stack check in existing lock claim path before acquisition; retain ancestor ownership. [Activation](managed-operations/activation/README.md). | C-LOCK |
| R08 | Finite request timeout surrounds an implicit `read_text` lock with `timeout=None`. | Registry uses explicit finite user-state transactions; no hard filesystem/callback timing claim. [Registry](eclab/lab-registry/README.md). | R-STATE, T-EXIT |

## Pass 2 — interaction and resource ownership

| ID | Counterexample / flaw | Design resolution and owner | Gate |
| --- | --- | --- | --- |
| R09 | Separate local/control operation factories need shared invocation state and cleanup ordering. | One service handler with typed local requests and private goal-only controls. [Routing](service-runtime/routing/README.md). | S-CONTROL |
| R10 | Session `step()` has no API argument, yet a token-only helper cannot enter core dispatch. | Retain a goal operation client only inside the same achieve window, clear on close; never capture handler APIs. Same routing page. | C-FRAME, W-LIFE |
| R11 | Generic handlers call each other during close with no resource order contract. | Reverse construction close; no cross-operation cleanup dependencies; same-closing-operation nesting only. [Managed operations](managed-operations/README.md). | C-CLOSE |
| R12 | Child uses provider A's dependency B and accidentally gains direct B access or root-scope resources. | Immediate caller policy differs from initiating scope/origin; both carried independently by host. [Directory](service-runtime/directory/README.md). | S-CONTROL |
| R13 | Completed A→B then B→A produces a cyclic lifetime graph although active recursion ended. | Retain per-scope DAG and reject temporal reverse edges; caller-before-dependency close order. [Scopes](service-runtime/scopes/README.md). | S-SCOPE |
| R14 | Ordinary caller A becomes a cleanup participant solely because it called B. | Track DAG vertices separately from touched service providers; hook resources retain their existing owner. Same scopes page. | S-SCOPE |
| R15 | Closing A discovers new C, reopens B, or needs another lease under A's held lease. | Freeze graph, permit only unclosed existing dependencies, retain stack lock rules; restructure owner release order. Same scopes page. | S-SCOPE, C-LOCK |
| R16 | Wrapper selector/helper failure happens outside a managed handler and a later hook overwrites exit 70. | Requires explicit goal-side reporting while preserving real child value. The original exception-valued `GoalResult.error` proposal was invalid; see R37 and [process](executable-support/process/README.md). | W-FAIL; open A freeze gate |
| R17 | Provider termination is swallowed as wait-only Ctrl-C, or two components reap the child. | Wrapper owns wait/reap; distinguish helper/provider termination and direct-child escalation. Same process page. | W-PROC |
| R18 | Child exit closes all service resources, making after-goal local calls fail. | Distinct child/invocation scopes; close child before after-call, invocation after outer hooks. [Scopes](service-runtime/scopes/README.md). | S-SCOPE, T-EXIT |

## Pass 3 — domain compatibility, limits and delivery

| ID | Counterexample / flaw | Design resolution and owner | Gate |
| --- | --- | --- | --- |
| R19 | A valid inventory larger than one frame makes local/wire-equivalent `records()` fail as a provider defect. | Bounded domain snapshot pages; complete-inventory facade and explicit single-record limits. [Snapshots](eclab/lab-registry/snapshots/README.md). | R-PAGE |
| R20 | Independent pages observe different versions, or polling leaves snapshots allocated. | Immutable per-read snapshot, bounded caller/count/bytes, explicit/finally/scope release. Same snapshot page. | R-PAGE, R-POLL |
| R21 | Batched commits acknowledge a prefix and reclaim starts deleting. | Complete commit facade returns only after every acknowledgment; later failure means zero deletion, no rollback claim. [Reclaim](eclab/sleep/README.md). | R-SLEEP |
| R22 | Corruption or a failed page is passed as empty inventory, distorting ownership and deletion safety. | Explicit unknown completeness; N/A for affected consumption values, zero deletion for reclaim. [Consumption](eclab/consumption/README.md). | R-POLL, R-SLEEP |
| R23 | Provider map exists from a previous invocation or was cleared after-call although basic entered status remains true. | Method readiness is owner-specific; reset/populate/clear maps on existing preparation paths. [Images](eclab/image-providers/README.md). | I-OFFER |
| R24 | Moving to generic ID order changes image tie precedence or mistakes synthetic pull for a plugin. | Keep explicit image-domain preference/ties and existing resolver cache/fallback; current source inventory lists actual wrapper IDs. Same image page. | I-OFFER |
| R25 | 32 MiB is claimed after an unbounded decoder already allocated data; tiny progress keeps a peer alive forever. | Account before allocation; bound frames/nodes/strings; absolute progress deadlines; distinguish charged storage from RSS. [Pump](transport/pump/README.md). | T-BOUND |
| R26 | Proxy waits upstream synchronously and cannot expire another unsent request. | Independent queue timers, fair bounded admission and correlated recoverable errors. [Proxies](transport/proxies/README.md). | T-PROXY |
| R27 | Proxy documentation promises per-descendant host cleanup without a wire scope-creation mechanism. | Explicitly retain direct-child host resource scope in v1; finer host scopes require a versioned extension. Same proxy page. | T-PROXY |
| R28 | Upgraded app is installed on A's definition-only runtime, or only one constructor gets services. | Functional runtime floors and probes; one config helper in both construction paths. [Application](eclab/application/README.md). | A-COMPAT, R-SLEEP |
| R29 | Router pseudocode inspects core entered status through an API that was never defined. | Leave entered checks in core dispatch; conservative touched entries close idempotently, with exact never-entered-owner rejection handled explicitly. [Routing](service-runtime/routing/README.md). | C-PHASE, S-SCOPE |
| R30 | A later hook returns success with no value, losing the real child outcome even though failure remains latched. | Preserve the pre-after-goal value independently and use it on managed failure. [Lifecycle](managed-operations/lifecycle/README.md). | W-FAIL |
| R31 | Sequential snapshot pages/batches each receive a fresh default budget; nested-call checks cannot detect the extension. | Typed facade owns one absolute deadline and passes remaining duration to every primitive. [Clients](service-contracts/clients/README.md). | R-PAGE, T-TIME |
| R32 | A timed-out first page allocates a snapshot but the client never learns its ID, consuming its only slot for a long polling invocation. | Fixed snapshot expiry, checked on service entry/scope close, reclaims lost allocations without a background provider callback. [Snapshots](eclab/lab-registry/snapshots/README.md). | R-PAGE, R-POLL |

## Pass 4 — platform strategy and contract correction

The user requires OS-specific behavior behind a strategy pattern and Windows to be
stubbed. A working Windows IPC backend is not an implementation prerequisite.

| ID | Counterexample / flaw | Design resolution and owner | Gate |
| --- | --- | --- | --- |
| R33 | Portable imports hide a Unix-only transport whose OS calls are still spread through generic code. | Transport and execution strategies own native mechanisms; protocol/routing/lifecycle use portable interfaces. [Transport strategies](transport/strategies/README.md), [execution strategies](executable-support/strategies/README.md). | T-PLATFORM, W-STRATEGY |
| R34 | A freezes raw `pass_fds` and `fd` fields as universal launch/readiness contracts. | Replace them before publication with opaque owned attachments/wait resources and a support snapshot. Native bindings remain in concrete adapters. [Contracts](executable-support/contracts.md). | A-STRATEGY, W-STRATEGY |
| R35 | Windows selects the Unix implementation, allocates scope/resources before failing, or silently treats stub `None` as disabled transport. | Fixed lazy Windows strategy; explicit typed unavailability before allocation, no fallback, local calls independent. [Windows stub](transport/strategies/windows/README.md). | T-PLATFORM, T-WINDOWS |
| R36 | Stale bootstrap chooses a foreign backend, or wrapper/helper double-close copied native handles. | Bounded backend-tagged metadata checked against local strategy; shared idempotent resource ownership and opaque bindings. [Endpoints](transport/endpoints/README.md). | T-STRATEGY, W-STRATEGY |
| R37 | Draft puts `OperationFailure` in `GoalResult.error`; actual API requires text, and dictionary-based models miss the mismatch. | Withdraw the invalid carrier; pass 5 proposes `GoalAPI.report_managed_failure` with runtime provenance and real API consumers. [Contracts](managed-operations/contracts.md#goal-side-reporting-and-provenance). | A-API, W-FAIL; implementation/freeze verification pending |

## Abstractions retained, reduced or deferred

Pass 5 applies the new external S1–S28 critique; the
[assessment and disposition table](critique-response.md) records every finding,
source correction, owning page and gate. R16/R37 now have the proposed
`GoalAPI.report_managed_failure` contract; their A-API/W-FAIL tests remain open.
R01/R05/R06/R30 now share one callback boundary, capture values before teardown,
consume destruction outcomes explicitly and specify ordinary child-close failures.
R28 uses local goal setup independently of the process helper. R19–R22 now include
conditional observation bases and a final inventory recency check. None of these
documentation resolutions claims a working B runtime.

| Choice | Reason |
| --- | --- |
| Retain generic operation coordinator and current execution frames | Before-goal calls, owner activation and lock checks are framework responsibilities across domains. |
| Retain capability descriptor + separate trusted codec catalog | Separates portable registration data from local codec behavior without exposing provider implementations. |
| Retain one per-invocation service handler and scope DAG | Gives one owner for nested local/child calls and resource lifetime. |
| Add registry snapshots/batches in its API | Solves a concrete complete-inventory/frame-budget conflict without adding generic streaming. |
| Reuse image-core lookup, ranking and response cache | The correct domain seams already exist; moving them into services adds coupling. |
| Require an explicit generic goal-side failure-reporting boundary | The proposed exception-valued result field was invalid; preserving provider attribution and the actual child result still needs a validated contract before A. |
| Retain separate transport and execution strategies | Keeps OS I/O and process ownership in their owning packages; optional binding avoids a core/services dependency on the wrapper runtime. |
| Stub Windows transport/execution strategies | User-selected scope; preserve portable imports/local services and explicit unavailability without freezing a Windows IPC primitive. |
| Defer cross-operation resource graphs, automatic retries, lock transfer and asynchronous owner dispatch | No current consumer justifies their added lifecycle/compatibility contracts. |
| Defer directory paging, published Go SDK and per-descendant host scopes | Real fixtures/consumers must justify expanding protocol/public surface. |
| Keep endpoint and phase transport separate | Portable business payloads do not make today's Python dispatch adapter remotely executable. |

## Residual limits and stop criteria

Synchronous providers can block indefinitely; OS termination can prevent cleanup;
registry/Docker mutations are not atomic; charged memory is not process isolation;
an A API freeze can still need later compatible refinement. These are explicit
limits, not unresolved promises hidden by pseudocode.

The goal-side failure-reporting design now has a concrete proposed signature and
provenance rule (R37/S1/S14); real API consumers and W-FAIL still gate its freeze.
Implementation-gated choices are bounded-parser implementation, measured descriptor
and recipe fixture sizes, actual unused release versions, additional owned downstream
roots, and whether a later capability needs per-descendant host resource scopes.
Each has an owner/gate above. The [design models](delivery/models/README.md) exercise
the core counterexamples; actual runtime/transport acceptance remains required.
