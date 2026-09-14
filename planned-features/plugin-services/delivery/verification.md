# Acceptance and regression matrix

Back to [delivery](README.md). These are implementation obligations unless a result
is explicitly recorded in [design validation](design-validation.md).

## Core and wrapper gates

| ID | Test or falsifiable check | Owner/stage |
| --- | --- | --- |
| A-API | Old ABC subclasses instantiate; new exports/records are typed and portable; unavailable reason is honest | API packages, A |
| A-STRATEGY | Generic launch/readiness use opaque resources; non-fd fake consumers and support snapshots type check; no strategy is instantiated by A | Wrapper API/runtime, A |
| A-STUB | Stale/thread-moved runtime stubs fail; no registration/factory/dispatch side effect; wrapper rejects support immediately | Core/wrapper, A |
| A-COMPAT | Upgraded owned packages discover/execute unchanged through existing catalogs; help/completion/editions intact | Both repositories, A |
| C-FRAME | Real A→B→C callbacks get correct owner APIs; B cannot borrow active A/goal/handler clients; A resumes valid afterward | Core, B1 |
| C-PHASE | Same-ID replacement phase, invalid/unentered/unselected target, duplicate target and `None` service reply fail correctly | Core/services adapter, B1/B3 |
| C-LOCK | Caller lease survives descendant state transaction; ancestor transaction rejects dispatch; new descendant lease rejects before acquisition | Core, B1 |
| C-FAIL | C origin survives B/A and caught failures; request/domain errors do not latch; unused operations do not alter ordinary result transforms | Core, B1 |
| C-CLOSE | Creation failure, early preemption, termination, deactivation failure and destruction/API-close failure still attempt every finalizer | Core, B1 |
| W-LIFE | Fake helper covers every lifecycle method, preparation unwind, disabled blocking path and no helper open for help/completion/veto | Wrapper, B2 |
| W-PROC | Real child/PTY/signals prove single process owner, direct-child termination, reaping, restored handlers and no wait-only swallowing of provider termination | Wrapper, B2 |
| W-STRATEGY | Fake non-fd strategy exercises generic loop; incompatible/foreign/closed resources reject; partial launch and duplicate cleanup are safe; Windows execution stub is importable and rejects operations without OS effects | Wrapper, B2 |
| W-FAIL | Resolve goal-side reporting contract using real `GoalResult` objects with textual errors; outside-handler defect plus real outcome survive outer success rewrite | Core/wrapper, A freeze/B2 |
| W-ENV | Actual child env/fds show removal/additions, no normalized-overlay leak, completion scrubbing and safe unrelated-fd reuse | Wrapper/client, B2/B6 |

## Services and consumer gates

| ID | Test or falsifiable check | Owner/stage |
| --- | --- | --- |
| S-DIR | Attributed registration, incompatible same-ID descriptors, optional subsets, filtered defaults, required selection and no unselected import | Services, B3 |
| S-CONTROL | Plugin cannot open child scope or forge caller/token; same handler reentry inherits origin/scope/deadline | Core/services, B3 |
| S-SCOPE | Independent invocation/child scopes, all DAG edge orders, later reverse edge, close dependency calls, no new edges, all touched cleanup after termination | Services, B3 |
| S-CODEC | Local/wire values are detached and equivalent; explicit codecs cover all accepted recipes/records; owner result errors attributed correctly | API/capability packages, B3 |
| R-STATE | Missing vs corrupt inventory, finite transactions, merge/no-op writes, expected vs unexpected errors, unchanged state identity/format | Registry, B4 |
| R-PAGE | >1 MiB inventory, page/snapshot consistency under concurrent writes, failed later page, oversized record, cursor limits and scope cleanup | Registry/API, B4 |
| R-SLEEP | Independent real state read at first fake deletion; all batches acknowledged; failed/uncertain commits cause zero deletion; lease remains held | Registry/sleep/application, B4 |
| R-POLL | Fresh commits observed on next reporting iteration, unknown completeness yields N/A, complete observations only, interruption releases snapshot | Consumption, B4 |
| I-OFFER | Active wrapper attribution, readiness/reset, authority/terminal rejection/ties, dependency conflicts, default pull and domain build fallback | All current image adapters/core, B5 |
| I-WORKER | APIs/callables do not reach build workers; migrated path never invokes `registered.provider.provide` under image-build | Image migration, B5 |

## Transport gates

| ID | Test or falsifiable check | Owner/stage |
| --- | --- | --- |
| T-VECTOR | Actual Python/Go envelope and capability codecs run the same valid/invalid vectors | Services and capability APIs, B3/B6 |
| T-PLATFORM | Native Windows imports/local service calls avoid Unix and wrapper-runtime imports; no strategy selection on local paths; fixed lazy strategy selection for IPC | Services, B3/B6 |
| T-STRATEGY | Portable protocol cases pass with non-fd fake channels; would-block/EOF/partial I/O, wrong backend/version, ownership and idempotent close are enforced without native field access | Transport, B6 |
| T-WINDOWS | Probe and unprobed open/connect reject with typed unavailability; stale Unix bootstrap cannot select Unix; no endpoint/environment/process/scope/provider side effects | Services, native Windows B6 |
| T-FRAME | HELLO/READY real fixture sizes, strict fields/keys/numbers/UTF-8, partial bodies, ID rules, bounded error replies | Transport, B6 |
| T-BOUND | Account before allocation, aggregate/per-frame bounds, one dispatch and 64 KiB I/O per turn, nonreading peer and tiny-progress timeouts | Transport, B6 |
| T-EXIT | Child exits behind blocked provider barrier: observation is delayed until return, then reply discarded, child reaped and scope closed | Wrapper/services, B6 |
| T-TIME | Queue expiry before send vs uncertainty after send, inherited deadlines never extend, no retry/reconnect | Client/host, B6 |
| T-PROXY | Independent unsent queue expiry while upstream waits, fairness, grants, ID maps, parent loss and separate nested directory | Proxies, B7 |

## Existing workspace checks

At implementation completion follow [AGENTS.md](../../../AGENTS.md), including the
API/core/wrapper and workspace unittest suites, Ruff lint/format, mypy, and owning
sibling consumer suites. Prepare the required Python 3.14 environment when needed;
do not confuse a source-only import path with a clean installed-wheel test.

Use deterministic subprocess/multiprocessing barriers, pipes and fake clocks rather
than timing-only sleeps. Run new packages' API/runtime/Go suites, packaging checks,
full wheel/sdist/Twine builds when metadata changes, and clean-install matrix tests.
Include new source paths in CI, type and documentation coverage. No live Docker
mutation is required for registry/sleep tests; the state and managed dispatch must
be real even while Docker is fake.

Windows IPC being intentionally stubbed does not make its tests optional. Test
portable services with a portable goal, independently of the Linux wrapper. Native
Windows transport implementation and Windows wrapper execution are outside B; no
Linux monkeypatch test alone can establish Windows importability.

The design models are deliberately smaller than these tests. They expose ordering
counterexamples and finite-state properties; they cannot prove runtime activation,
signals, filesystem durability, memory allocation or cross-language interoperability.
