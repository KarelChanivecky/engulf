# Critique: plugin services v4

Reviews [plugin-services/](plugin-services/) — 44 active pages, 3,554 lines outside
`seed/` — against the Engulf workspace at `4c7e95e` (current `master`). Source
references are `file:line` at that commit. `goals.py` means
`engulf-api/src/engulf_api/goals.py`; `application.py`, `_dispatch.py`,
`_capabilities.py` and `plugin_loader.py` mean the modules under
`engulf/src/engulf/`; `goal.py` means
`engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py`.

Status: open. Findings are `S1`–`S28`. `S1`–`S5` and `S21`–`S23` block; `S1` is
already open in the plan's own ledger as R37 but is not closed and is not applied
where it binds.

**Two snapshots moved under this review.**

*The plan.* Pass 4 (R33–R37), the `transport/strategies/` and
`executable-support/strategies/` layers, and the R37 withdrawal all landed on
2026-09-14 between 09:24 and 09:33, growing the workspace from 2,997 to 3,554 lines
across 28 touched files. Everything below is against the post-09:33 text. Where a
finding restates something the authors had already caught that morning, it says so.

*The repository.* `master` advanced from `4bac606` to `4c7e95e` ("chore: establish
beta baseline") during the review, which reset all four core distribution versions —
`engulf-api` 1.3.0 → **1.0.0**, `engulf` 0.3.0 → **0.1.0**,
`engulf-executable-wrapper-api` 1.2.1 → **1.0.0**, `engulf-executable-wrapper`
0.3.0 → **0.1.0** — and rewrote every dependency floor. That falsifies the plan's
packaging rollout wholesale; see `S23`.

Scope: this repository only. The plan links into the sibling `engulf-clab` checkout
for the registry, consumption, sleep and image consumers; that tree was not read, so
every claim about those plugins rests on the plan's own description and is marked
unverifiable where it matters. Every source claim below was read, not inferred.

Method: fourteen criterion analyses and six adversarial lenses, each grounded against
the real source, with independent refutation of the lens findings. Dimensions marked
**(single-pass)** in the ratings table are my own reading rather than a verified agent
pass — the review ran into a rate limit and those were completed by hand.

## Verdict

This is the most rigorous design document in `planned-features/`, and the rigor is
real rather than decorative. It reuses the execution endpoint instead of inventing a
provider registry; it replaces generation-only capability checks with a current-frame
rule and proves the counterexample; it separates portable payloads from local
dispatch events so result validation happens while the owner is still activated; it
keeps a review ledger of 37 counterexamples with owning pages and acceptance gates;
and `evidence.md` separates what was read from what is proposed, which almost no plan
here does. The A/B split is a genuinely good instinct, and Delivery A's code risk is
small — about fifteen lines of live-path change in two files, everything else
additive and fail-closed.

The problems are not in the machine. They are in three places the plan has not looked
as hard at as it has looked at itself.

**The freeze does not yet hold.** The plan's own R37 withdrew the exception-valued
`GoalResult.error` carrier on 2026-09-14 and correctly marked it an unresolved A
freeze gate. But the withdrawal was applied to `lifecycle`, `process` and
`foundation`, and **not** to `managed-operations/contracts.md:79-82` — the one page
`foundation/README.md:9-11` designates authoritative and frozen (`S1`). A second,
independent `engulf-api` change that R30 requires — `framework_failed()` has no
`value` parameter — is not recorded anywhere at all (`S2`). Both falsify
`packaging.md`'s "API packages need no new version in B". A freeze that has two
unbooked `engulf-api` edits against it is not ready to be frozen.

**The child boundary is specified everywhere except at the authorization decision.**
The design spends extraordinary precision on *who is asking* — runtime-derived caller
IDs, the caller-kind enum, the current-frame check, closed wire envelopes — and then
takes *what may be granted* from the request payload. `OpenChild.grants` is never said
to be intersected with the frozen application policy (`S3`), and the seed had that
rule explicitly (`seed/plugin-services-v3.md:209`, "Broker policy can lower limits but
cannot expand application grants", plus a `permitted_broker_ids` allowlist) before it
was dropped without a ledger entry. The endpoint's principal is whoever holds the fd,
and descendant containment is the *child's* cooperation, not host enforcement (`S5`).
Denial codes distinguish `denied` from `missing`, which is an existence oracle, and
the seed had that rule too (`v3:268`, `not_granted` "without revealing other
metadata") before it was dropped. Three security rules present in the archive are
absent from the design that replaced it.

**Elevation does not appear in 3,554 lines.** The most recent feature commit is
`4bac606` "feat: require goal opt-in for elevated startup"; `privilege.py:45-102` demands that
an installed entry point's declaring distribution *verifiably own the goal module's
file* before an elevated run proceeds. The plan then adds `execution_support=` — an
arbitrary object from any distribution, subject to no such proof — and hands it the
goal's operation client, which is what mints child scopes, chooses grants, sets the
child environment and chooses `pass_fds` (`S4`). The framework audits the goal class's
provenance and does not audit the component that actually exercises goal authority.
No gate in `verification.md` mentions elevation.

Two things I would not change. The invariant set is large but load-bearing, and the
explicit refusal list — no retry, reconnect, cancellation, batching, notifications,
lock transfer, lease union, async dispatch, cross-operation cleanup — is what keeps
this at an 8 rather than a 10 on complexity. And the honesty discipline is exemplary:
where the design has a limit it says so, in the place a reader would otherwise
over-trust the mechanism.

Two things I would change before writing code. Close the A-freeze gaps (`S1`, `S2`,
`S16`) and shrink A to the consumer-facing half of its surface, because roughly half
of what A freezes cannot be reached by any A-era consumer and is therefore frozen
with zero feedback. And give B the compatibility treatment A got: B1 rewrites the two
cleanup paths every existing invocation already traverses, and there is no B-COMPAT
gate and no clean-install row for an ordinary plugin on a B runtime (`S6`).

## Ratings

Every scale is 0–10 and every one runs "worse → better", **except complexity**, which
measures rather than grades: there 0 is very simple, 5 average, 10 very complex.

| # | Criterion | Score | One-line reading |
| --- | --- | --- | --- |
| 1 | Flexibility / abstraction headroom | **6** | The operation primitive is genuinely capability-agnostic; the ceiling is reached fast in the directions that matter |
| 2 | Security | **6** | Caller identity is excellent; the one authorization decision in the child path is unspecified, and elevation is absent |
| 3 | Specification completeness | **6** | Runtime semantics specified to an implementable depth; the surface an author types first is missing |
| 4 | Strong / weak points (holistic) | **6** | Right mechanism, roughly 3–5× the size its own evidence justifies |
| 5 | **Complexity (measurement)** | **8** | Harder than a gRPC service layer with lifecycle; easier than a capability-secure microkernel |
| 6 | Ease of implementing service plugins | **4** | A correct provider is achievable; a quick one is impossible, and today neither is writable from the docs |
| 7 | Breaking surface vs old plugins | **6** | A is close to provably inert; B is where the surface is, and it is not enumerated |
| 8 | Delivery A simplicity and risk | **7** | ~15 lines of live-path change, fail-closed throughout; freezes more than it has evidence for and less than R16 needed |
| 9 | Testability / gate realism | **6** *(single-pass)* | 30 concrete gates, but several recorded results are vacuous and the security gates are missing |
| 10 | Performance and resource cost | **6** *(single-pass)* | Fine for the named consumers; the paging protocol buys message bounding, not memory bounding |
| 11 | Observability / debuggability | **4** *(single-pass)* | Exit 70 collapses every managed defect; no chain rendering, no correlation ID, no introspection |
| 12 | Evolvability and versioning | **5** *(single-pass)* | Eight version axes, no per-axis rule, and the application is a hard bottleneck on every new capability |
| 13 | Delivery risk / effort realism | **4** | A rigorous design with an unrigorous delivery plan attached; ~30% of B has no consumer |
| 14 | Conceptual integrity / cognitive load | **6** *(single-pass)* | One clean central idea; five vocabulary collisions and no glossary or worked example |

Criteria 1–8 were requested directly; 9–14 are the six I added. Scores are independent
judgements, not a scorecard to average — the design is strong where it is strong and
weak in a small number of specific, fixable places.

### Sub-ratings for complexity

| Facet | Score | Note |
| --- | --- | --- |
| Delivery A alone | **3** | ~40 frozen definitions plus stubs; comparable to a plugin hook registry |
| Delivery B | **8** | Topological cleanup surviving termination, a latch that survives being caught, a hand-rolled bounded parser, two OS strategy layers, cross-language conformance |
| Exposed to a service *consumer* | **4** | The typed facade absorbs most rules; a consumer holds about four |
| Exposed to a service *provider* | **7** | ~14 simultaneous rules, four mechanical chores per provider, three footguns only reachable on rare paths |

Measured surface behind those numbers: ~118 new public tokens (65 named
types/protocols/errors, 19 constants and state names, ~34 closed-vocabulary strings);
10 state machines with ~57 named states; 15 interacting lifetimes of which roughly 21
of 105 pairs are specified; 208 strict normative clauses (374 counting
`require`/`only when`) across 3,554 lines and 44 files; 9 architectural invariants,
not 8. Estimated new production code: ~600–900 lines for A, ~5,600–8,900 for B in this
repo, against 11,071 existing source lines — B roughly doubles the framework.

## The six added criteria

Four of these were produced by the same grounded process as criteria 1–8. The five
marked *(single-pass)* above were completed by hand after the review hit a rate limit,
and are summarised here rather than given their own findings.

**Testability (6).** The 30 gates are unusually good as gates: each names a concrete
counterexample rather than "test thoroughly", and B4's is written to reject the cheap
proxy for it ("a mock `commit` event preceding a mock `remove` event is
insufficient"). Against that, `S24` shows several recorded validation results cannot
fail, on a page `verification.md:3` lets discharge implementation obligations; there
is no gate for grant enforcement, information leakage, elevation, an existing plugin
on a B runtime, or authoring a provider from the published docs; and several gates
need infrastructure the plan never specifies — a Go toolchain in CI, a fake wrapper
helper, fake Docker, multi-process barriers, PTY harnesses. The repo has 8,175 test
lines today; B plausibly needs as many again.

**Performance (6).** The forbidden local fast path is the right call and costs little
at the actual workloads — six image providers per requirement during preparation, one
inventory per two-second poll, all at human scale. The real cost is the snapshot
paging protocol: at the 4 KiB floor the plan's own 1.2 MB fixture is 320 round trips,
each a separate core dispatch with its own state transaction that re-reads and
re-parses the whole `labs.json`, since the provider does
`read_and_validate_existing_format(store)` per snapshot regardless. The page concedes
the limits "are not ... a bound on the existing state API's whole-file read
allocation" — so the protocol bounds the message, not memory, which is most of what
one would want it for. The deferred reserve-before-allocate JSON parser is the
throughput unknown.

**Observability (4).** The weakest dimension. Exit 70 carries every managed defect, so
distinguishable failures collapse into one signal. `application.py:811` stringifies
today (`str(error.error)`), and no page specifies wiring `OperationFailure`'s
`call_chain` into the existing renderers, so the attribution the design works hardest
to preserve has no rendering path. The latched-failure experience is genuinely
confusing: a consumer catches, continues, logs success, and the process exits 70
naming a plugin the author may not own — with no diagnostic at the catch site. The
wire carries no correlation ID, so an operator cannot match a child-visible bounded
error string to the host-side diagnostic. There is no way to list services, explain a
policy denial, or inspect the scope DAG, though `engulf-plugin-list` is the obvious
precedent. And a synchronous provider that never returns stalls the pump and the whole
invocation with nothing reporting what it waits on.

**Evolvability (5).** Eight independent version axes — `PLUGIN_API_MAJOR`, goal catalog
majors, `MANAGED_OPERATIONS_API_MAJOR`, `EXECUTION_SUPPORT_API_MAJOR`, capability
majors, codec identity plus version, wire `protocol_major`, and distribution
versions/floors — and no page draws the compatibility rule for each: who bumps it, who
checks it, what happens on mismatch. `OperationSupport` carries `api_major` only, and
the wire carries `protocol_major` only, so neither has a minor or feature axis for a
compatible extension. The structural problem is that the application owns accepted
capabilities, the codec catalog and the access policy, and `edition()`
(`application_definition.py:106-132`) can replace only display metadata,
`plugin_policy` and `required_plugin_ids` — not the goal factory. So no third party can
ship a working provider/consumer pair without an application source release. That
inverts today's model, where a plugin declares its own `context_reads`/`context_writes`
and ships independently. The frozen keyword-only record convention is the redeeming
feature: field addition stays source-compatible, which correctly narrows the freeze
risk to the items in `S16`.

**Conceptual integrity (6).** The central idea is clean and statable in one sentence:
*a consumer asks the runtime to re-enter a provider through the endpoint that already
activates and attributes plugin callbacks*. Everything in `managed-operations/` follows
from it. The dilution is at the edges — `transport/` exists for no consumer,
`snapshots/` exists only because the local-equals-wire rule imports a frame ceiling
into a local call, and `strategies/` is a user requirement rather than a consequence of
the idea. Five vocabulary collisions land on a reader who already knows Engulf:
"capability" (the callback-bound runtime capability in `_capabilities.py` vs a service
capability descriptor), "scope" (`StateScope` vs service resource scope), "context"
(`get_context`/`set_context` vs `ServiceCallContext`), "phase" (`GoalPhase` vs service
phase), and "broker" (`S18`). As documentation the workspace is dense and disciplined
but has no glossary, no end-to-end worked example, no lifetimes diagram, and no
"why not simpler" section — and by `architecture.md`'s own stop criterion it is not
finished, because the consumer-facing leaves in `S17` have neither a specification nor
a named deferral.

## Findings

### S1 — the withdrawn `GoalResult.error` carrier is still live on the page the freeze designates authoritative

**Blocking.** R37 (`review.md:66`) resolves to "Withdraw the invalid carrier example,
preserve `str | None`". `lifecycle/README.md:83`, `process/README.md:74-77` and
`foundation/README.md:68` all apply it. `managed-operations/contracts.md:79-82` does
not:

> A goal can also return a `GoalResult` whose `error` is an explicit `OperationFailure`.
> Core records that carrier before outer hooks, preserving the result value.

and the next paragraph builds the reserved wrapper failure identity
`org.engulf.executable-wrapper.execution-support` on top of that mechanism.
`foundation/README.md:9-11` sends the A implementer to exactly this page: "The
authoritative proposed definitions live in [operation contracts] ... Only those pages'
A definitions are frozen here."

The mechanism cannot be built. `GoalResult` is `@dataclass(frozen=True, slots=True)`
with `error: str | None` (`goals.py:35`) and `__post_init__` raises:

```python
if self.error is not None and not isinstance(self.error, str):
    raise TypeError("error must be a string or None")   # goals.py:43-44
```

An implementer who follows `foundation/README.md` to `contracts.md` and writes the
documented result gets a `TypeError` raised *inside the framework-failure reporting
path*, at which point `application.py:812`'s `except Exception` converts it to
`GoalResult.framework_failed(error=str(error))` — destroying both the original
provider failure and the real child `CallOutcome`, and reporting "error must be a
string or None" as the invocation's error.

This is not a re-report of R37. R37 is recorded; it is the *application* of R37 that
is incomplete, on the single page that binds. Delete or rewrite `contracts.md:79-82`
to match `process/README.md:74-77`, re-anchor the reserved wrapper identity on the
accumulator rather than the result field, and add a check to the A1 gate
(`delivery/README.md`) that greps the frozen pages for any claim that `error` accepts
a non-`str`.

The replacement contract is still owed. `review.md:91-92` is right that goal-side
managed failure reporting with a text field is unresolved, and it is the last real A
blocker.

### S2 — R30 needs a second `engulf-api` change that no page records

**Blocking.** `lifecycle/README.md:60-64` returns

```text
GoalResult(status=FRAMEWORK_FAILED, exit_code=70, value=pre_after_value, error=...)
```

using the raw constructor, because the classmethod cannot express it:

```python
def framework_failed(cls, *, exit_code: int = 70, error: str | None = None):
    return cls(GoalResultStatus.FRAMEWORK_FAILED, exit_code, error=error)   # goals.py:95-101
```

There is no `value` parameter, and every core call site uses the classmethod and
therefore discards `value` — nine of them, at `application.py:557, 591, 701, 739, 811,
818, 863` and `_dispatch.py:136, 172`. So R30's fix requires either adding a
keyword-only `value` to a published `engulf-api` classmethod — an A change — or
rewriting those call sites in B.

`packaging.md` says "The API packages need no new version merely to flip concrete
implementation availability if the frozen interfaces still match." The condition is
honestly phrased, and the plan has now broken it twice: once knowingly (`S1`/R37) and
once without noticing (here). Book both, or the A version table is wrong.

### S3 — `OpenChild.grants` is payload-supplied and is never intersected with the frozen application policy

**Blocking.** `routing/README.md:26` is the whole of the authorization decision:

```text
if OpenChild: return create_child_scope(grants, host_session_identity)
```

`grants` is a field of the request, constructed by the services helper — itself an
arbitrary `execution_support=` object (see `S4`). The only stated guard on `OpenChild`
is `caller.participant_kind == GOAL` (`routing/README.md:15-16`), which authenticates
*who is asking* and says nothing about *what they may ask for*. `ExecuteChild` then
validates "the child request against **that scope's grants**" (`:30`) — the scope's
stored copy, not the policy. `directory/README.md` does freeze "access policy and
optional broker configuration", so the policy is in hand at `OpenChild`; it is simply
never said to be consulted.

The archived seed had the rule and it was dropped with no ledger entry:

> Child grants are explicit; the default grants no child access. Broker policy can
> lower limits but cannot expand application grants. `permitted_broker_ids` defaults
> to ... — `seed/plugin-services-v3.md:207-210`

The broker is an ordinary selectable plugin whose CONFIGURE contribution receives no
content validation — registrations are validated "against canonical accepted
descriptors and codec catalog" (`directory/README.md:16-17`), but the broker gets only
"Reject duplicate broker configuration" (`:25-26`). So an installed broker plugin can
supply a grant set that the application policy never authorized, and the design as
written does not say the handler refuses it.

State that `OpenChild.grants` is a *narrowing* request: intersect with the frozen
policy for caller kind CHILD and reject — not silently trim — anything outside it, so
maximum child authority is always set by application code. State that a broker
CONFIGURE contribution is transport configuration and can never widen access. Add an
S-CONTROL case: broker requests a capability outside policy, `OpenChild` is rejected,
no scope and no endpoint are allocated.

### S4 — elevation is absent from the entire design, and `execution_support=` is an unaudited injection that inherits goal authority

**Blocking.** `grep -rniE 'elevat|privileg|sudo|uid'` over all 44 active pages returns
nothing. Meanwhile:

- `application.py:175` computes `self._elevated = is_process_elevated()`, and
  `:217-223` runs `validate_goal_privilege` before setup when elevated.
- `privilege.py:45-102` resolves `type(goal).__module__`'s file and requires that
  exactly one installed entry point, whose declaring distribution *verifiably owns
  that file*, names it. It refuses ambiguity.
- `api.elevated` is a callback-bound property on plugin and goal APIs
  (`plugin_api.py:31-43`), and `AGENTS.md:160-164` makes `ElevationRequirement` a
  declared, machine-readable property whose optional plugins "must branch on
  callback-bound `api.elevated` and provide a coherent unprivileged path."

The design adds a synchronous entry point into that process and never mentions the
state. Three consequences follow.

**The access policy has no privilege axis.** It is "indexed by runtime caller kind/ID
and target capability/provider" (`directory/README.md`). A provider declaring
`ElevationRequirement.REQUIRED` — the ones doing Docker, netns and registry mutation,
which is exactly why `plugin_loader.py` refuses to start without elevation — cannot
say "and my capability is never child-grantable". `ElevationRequirement` becomes
non-transitive with no note: a consumer declaring `NONE` can cause a `REQUIRED`
provider to act, and a child process can do the same with no plugin metadata involved.

**The privilege gate audits the wrong object.** `validate_goal_privilege` inspects the
goal class's provenance and nothing about its constructor arguments. The plan then
adds `execution_support=None` to `ExecutableWrapperGoal.__init__` and gives that
object the goal's operation client (`routing/README.md`, "Wrapper session lifetime").
That object mints child scopes, chooses grants, sets the child environment and chooses
`pass_fds`. Under elevation the audited artifact is the goal class; the component that
actually exercises goal-kind authority is an arbitrary object from any distribution.

**`pass_fds` is validated for well-formedness, not ownership.**
`executable-support/contracts.md` requires "unique nonnegative fd integers excluding
booleans, live descriptors" — type and liveness. Nothing requires `pass_fds` to be a
subset of descriptors the session itself created. Under elevation a helper can hand
the child any live root-held descriptor, including the POSIX state platform's flock
descriptor (`_state_posix.py:30-39`). The fix is one contract line — `pass_fds` ⊆
session-created descriptors, enforced by the wrapper, not the helper — plus a W-ENV
assertion.

Add an elevation section; add `elevated` to the access-policy index; default-deny
child scopes under elevation unless the application explicitly opts in, mirroring
`privilege.py`'s stance; map `ElevationRequirement` into descriptor registration; and
add acceptance cases for elevated + broker, elevated + child grant of a REQUIRED
provider, and a non-elevated regression.

### S5 — the endpoint's principal is whoever holds the fd; descendant containment is the child's cooperation, not host enforcement

**Blocking.** `transport/strategies/posix/README.md` says the host creates a
socketpair, marks both ends non-inheritable, passes only the intended child end with
`pass_fds`, and drops its copy after spawn. Then:

> the child claims the inherited endpoint and does not pass it to ordinary
> descendants.

and `endpoints/README.md`: "The concrete backend prevents ordinary subprocess creation
from accidentally sharing the stream with descendants. Explicit proxies are required
for supported descendant access."

Both sentences describe the behavior of the *child's copy of the services client
library*. `pass_fds` hands the child an open, non-`CLOEXEC` descriptor. Nothing
requires the wrapped executable to be a services client, and nothing verifies it
became one — `helper.open` creates the child scope and its grants *before* spawn
(`transport/README.md`), so the scope exists regardless of what the spawned binary
turns out to be.

Concretely: eclab wraps an arbitrary resolved executable. If that is
`/bin/sh -c 'containerlab deploy …'`, or a vendored `#!/bin/sh` shim, the shell never
reads `ENGULF_SERVICES_ENDPOINT` and never calls `connect_from_environment`, so the
descriptor is never claimed and never marked non-inheritable. A POSIX shell passes
every non-`CLOEXEC` descriptor to each command it runs. Any descendant — a topology
hook, a node startup script, anything the user's lab config runs — can write a framed
HELLO directly into fd 3 and be served with the child scope's full grants. Because a
socketpair is a shared endpoint rather than a listener, `SO_PEERCRED` reports the
creating process, so the host cannot distinguish writers; two descendants interleaving
frames look like one well-behaved child.

`endpoints/README.md` does list "child-created subprocess fd inheritance" as a test
case, so the authors considered it — but the tested resolution is the *cooperating*
client clearing the flag, which only exercises the configuration in which the defect
cannot occur.

The generic disclaimers do not cover this. `architecture.md`'s "managed calls are not
isolation" and `transport/README.md`'s "the direct child and normal plugins retain
their actual OS authority" are about in-process plugins and about the child's own OS
rights. Neither says the channel is reachable by unrelated processes, and both sit
beside an affirmative descendant-containment claim.

There is also no host-side peer verification at HELLO or ever. A hostile or
compromised child can re-enable inheritance or pass the fd over `SCM_RIGHTS`, and the
host serves whoever holds it. The design never states "grants attach to the
connection, therefore to any process the child hands the fd to."

For the initial migrations the blast radius is nil — `child_grants=empty` — but the
proxy milestone builds directly on this, and `packaging.md` already anticipates
creating the socketpair, exporting the endpoint and running the full parser path for a
child that can call nothing, which is attack surface for zero functionality. Require
an explicit per-executable opt-in before a child scope is created at all; state the
principal honestly in the grants model; and add a case with an `sh -c` wrapped
executable asserting either that no endpoint was passed or that a descendant's raw
HELLO is refused.

### S6 — B1 rewrites the cleanup paths every existing invocation traverses, with no B-COMPAT gate

**Major.** `verification.md:13` carries A-COMPAT, scoped explicitly to "Both
repositories, A". There is no B equivalent — the string `COMPAT` appears once in the
file. `packaging.md`'s clean-install matrix has eight rows and not one is "existing
unmodified plugin + B runtime, no services installed". B1's own gate is entirely about
new machinery: "Real before-goal A→B→C ownership, frame checks, locks, origin/latch,
early completion and termination."

B1 is where the two cleanup paths every invocation already traverses get replaced:

- `_dispatch.py:239-240` — today a failing `api.deactivate()` inside
  `finally: api.deactivate()` masks the plugin's `PluginCallbackError`. This is
  reachable by any existing plugin using `api.lease()` or `state().transaction()`,
  because `deactivate()` calls `self._locks.release_active()`
  (`plugin_api.py:79-91`), which re-raises the first release error.
- `application.py:843-845` — today `for api in plugin_apis.values(): api.close()` is
  unguarded, so one raising close skips every later plugin's close, `goal_api.close()`,
  and the `UnusedContextWarning` block at `:846-861`.

Under B1 both become accumulated secondaries and the invocation returns exit 70
instead of raising. Both changes are improvements — R05 and R06 are correct — but they
are not opt-in, and the design's guard sentence ("An application that never uses
operations does not gain a universal sticky failure rule", `lifecycle/README.md`) is
about the latch, not about these.

A third, directly assertable difference: today `application.py:862-863` returns
`GoalResult.framework_failed(error="workspace state cleanup failed")` with `value=None`
on a workspace-cleanup failure; `lifecycle/README.md:60-64` returns
`value=pre_after_value`. Any existing test asserting `result.value is None` on that
path sees a different object, for a plugin that has nothing to do with services.

A fourth: `lifecycle/README.md`'s replacement `finally` block does not mention the
`UnusedContextWarning` at `application.py:846-861`, and reassigns `result` in ways that
would change its `status is COMPLETED` gate. The plan says nothing either way.

Add a B-COMPAT gate and a matrix row, and enumerate the B1 semantic deltas the way
`foundation/README.md` enumerates A's.

### S7 — nothing detects a partially upgraded venv, and the actual floors are wider than the plan assumes

**Major.** The declared floors are wider than any analysis in the plan:

```toml
engulf/pyproject.toml:22                    dependencies = ["engulf-api>=1.0,<2"]
engulf-executable-wrapper/pyproject.toml:23 "engulf>=0.1,<1"
```

So `engulf-api` 1.4.0 — dependency-free — installs cleanly beside `engulf` 0.1.0, and
`engulf-executable-wrapper` 0.3.0 installs beside `engulf` 0.4.0. Nothing checks the
pair at runtime: `plugin_loader.py` reads `distribution.version` only for reporting
and identity dedup, and `PLUGIN_API_MAJOR` is a constant used to build entry-point
group names, never compared against anything.

`packaging.md` names `engulf-check-packaging` as the gate for the clean-install matrix.
That tool cannot check any row — `_read_project` reduces `project.dependencies` to a
frozenset of bare distribution *names*:

```python
_normalize_distribution_name(_requirement_name(requirement))
for requirement in project.get("dependencies", ())     # packaging_check.py:104-106
```

Version specifiers are never parsed or compared, and it is a build-time CLI over
`pyproject.toml`, never invoked at startup.

The consequence the matrix gets wrong: row "B services/application + A runtime →
explicit installation/availability refusal" is false on the wrapper axis. With
`engulf-executable-wrapper` 0.3.0 (whose `__init__` has no `execution_support`
parameter, `goal.py:261-267`) beside `engulf` 0.4.0, the eclab B application's
`_containerlab_goal()` raises `TypeError: __init__() got an unexpected keyword
argument 'execution_support'` — not `ExecutionSupportUnavailableError`, and not
anything a user can act on. Because that is the goal factory, it fires for
`eclab --help` and for shell completion.

R28 routes this to "functional runtime floors and probes", but the probe lives in the
application bootstrap, which is the code that never runs because the goal constructor
raised first — and there is no probe at all for the api-ahead-of-runtime direction.

Either stop citing `engulf-check-packaging` as the matrix gate or teach it version
specifiers; add a cheap runtime cross-check at `Application` construction; and expand
the matrix from an A/B dial to the four real distribution axes, marking per row the
exact moment of detection (resolver / import / goal construction / setup / first
request).

### S8 — a migrated consumer wheel and an unmigrated application are installable with no conflict, and the plan forbids the only fallback

**Major.** `package-inventory.md` shows the migrating consumers are distributions
separate from the application: `engulf-clab-consumption` 0.2.0 and
`engulf-clab-lab-registry` 0.1.1 are distinct rows from `engulf-clab` 0.3.2.
`packaging.md` says a domain provider/consumer package depends on "Own capability API
+ applicable goal/API packages; runtime implementation not required", and forbids
adding runtime dependencies to API-only wheels to force an upgrade.

So the migrated consumption wheel has no expressible dependency on the application —
yet the only thing that makes it work is the application's
`execution_support=make_containerlab_execution_support()`. A routine
`pip install -U engulf-clab-consumption` pulls the B-migrated build whose `before_goal`
is `registry = typed registry client built from services(api)`, resolves with zero
warnings against the unmigrated application, and fails at runtime with
`unknown_operation` because the unmigrated goal never called `register_operation`.

There is no fallback by design: `lab-registry/README.md` removes `SessionLabRegistry`
publication and the context reads/writes, and `packaging.md` comes down against
retaining the old symbol. The matrix has no row for this direction — it covers
"A-definition consumer + B runtime", the inverse and less likely case.

Name the floor concretely. Either require migrated eclab plugin wheels to declare a
direct floor on the distribution that supplies their capability configuration (these
are not API-only wheels, so the no-runtime-dependency rule does not apply), or give the
capability-API wheel a major bump whose floor makes the incoherent set unsatisfiable.
*Unverifiable from this repo: the sibling plugins' actual dependency metadata.*

### S9 — the context-key flag day's blast radius is the whole invocation, and the inventory is repo-scoped

**Moderate.** `lab-registry/README.md` removes the operational context reads/writes
"after API, provider and consumers migrate together", and `image-providers/README.md`
requires proving no callables remain in `IMAGE_PROVIDER_CONTEXT`. "Together" is scoped
to the six adapters the plan enumerates, and the page says so.

But context access is declared by the *plugin's own* metadata, not the application:
`PluginMetadata.context_reads` (`engulf-api/.../plugin.py:33,176-177`) flows through
`LoadedPlugin` (`plugin_loader.py:256`) into
`RuntimePluginAPI(context_reads=item.context_reads, …)` (`application.py:758-769`). Any
wheel in any repo can declare a read of a removed key without appearing in that
inventory.

The failure is not confined to the stale plugin. `MissingContextError` is raised on
read (`_capabilities.py:45`); `_dispatch.py:230-238` wraps *any* `Exception` in
`PluginCallbackError` and re-raises unless `phase.isolate_failures`. So for any
non-isolated phase the entire invocation framework-fails with exit 70 — `eclab deploy`
stops working because one unrelated plugin is one version behind, with no version
constraint able to express the dependency, because the key is a string in metadata,
not a package. The `IMAGE_PROVIDER_CONTEXT` half fails *silently* instead: image-build
no longer reads the context, so a private provider simply stops being consulted and
different images get built.

Add a deprecation release: keep publishing the key for one minor cycle while warning,
naming every plugin whose metadata still declares a read (the runtime already knows
this from `LoadedPlugin.context_reads`). Add the matrix row. State in both pages that
the inventories are repo-scoped and cannot enumerate external consumers.

### S10 — child-facing denial codes are an existence oracle, and the seed's rule was dropped

**Moderate.** `directory/README.md` promises: "Explain local rejections with caller,
target and phase without exposing hidden providers to children." `wire/README.md`'s
`request` kind then enumerates "denied/missing/ambiguous/not-ready/unsupported/invalid
request…" and delivers them to the child as correlated recoverable responses.

`denied` versus `missing` is a one-bit existence oracle over a namespace of ordinary
reverse-DNS identifiers: one bounded CALL per guess recovers the host's hidden
provider inventory for every capability the child can name. `ambiguous` reveals that
at least two exist. `not-ready` leaks lifecycle state. Omitting `provider` entirely
distinguishes "no provider" from "an inaccessible default is configured", because
`directory/README.md` deliberately chose an explicit typed rejection there so
"configuration mistakes are visible" — the right goal locally, shipped over the
boundary where the page had promised the opposite.

The seed had this right: "request outside the grant returns `not_granted` without
revealing other metadata" (`seed/plugin-services-v3.md:268`), dropped with no ledger
entry.

Split the taxonomy by audience: over the wire, collapse denied/missing/ambiguous for
an unadvertised target into one indistinguishable code with a fixed message — the
child can only ever legitimately name a provider it was advertised, so a specific
reason is never actionable for it. Keep the distinguishing codes locally. Add a
conformance vector asserting byte-identical error frames for a denied-existing
provider, an unknown provider, and a filtered default.

### S11 — `pre_after_value` is captured after `run_goal()` returns, so it is `None` on exactly the paths R30 exists to cover

**Major.** `lifecycle/README.md`'s pseudocode does:

```text
if no early result: result = run_goal()
pre_after_value = result.value  # capture before outer hooks can replace it
```

Its own prose 35 lines later says something strictly stronger: "Capture a returned
goal result inside the goal boundary before deactivation can fail." The pseudocode
captures *outside* the boundary, after `run_goal()` has returned normally, and names
only outer hooks as the hazard.

Any exception from the goal frame's own teardown — which this design adds work to
("attempt all owner-local lock releases and API deactivation", plus the frame pop) —
means `run_goal()` raises rather than returns, `pre_after_value` is never assigned, and
the final result reports `value=None`. The loss R30 was opened to prevent then happens
through the code R30 produced. The same hole opens whenever the whole goal raises,
including via `S1`'s `TypeError` and `S12`'s close failure.

R30 is titled "A later hook returns success with no value" and addresses only the
hook-overwrite path. R05 covers the *error*, not the *value*. The prose shows an author
already saw this and did not amend the pseudocode — which matters, because the
pseudocode is what `delivery/models/check_design.py` encodes.

Move the capture inside the goal boundary, in the same statement that validates the
returned result (the `_require_result` site at `application.py:809`), before any
deactivate, lock release or frame pop. State what `pre_after_value` means on the
early-completion path, where no goal ran. Add a W-FAIL case: goal returns a value,
goal-frame teardown raises, assert the framework-failed result still carries it.

### S12 — a child-scope close failure destroys `after_call` and the real child outcome

**Major.** Three pages fix the ordering "close child session/resources before
`after_call`" (`executable-support/README.md`, `process/README.md`,
`architecture.md`). One page defines what closing a scope does on failure:
`close_scope` ends with "propagate first termination or recorded managed cleanup
failure" (`scopes/README.md`) — it raises out of the caller's frame. In the wrapper
that frame is `ExecutableWrapperGoal.achieve`, between `self._execute(...)`
(`goal.py:404`) and the `_AFTER_CALL` dispatch (`goal.py:415`).

No page says what the wrapper does when that close raises. Every failure rule on the
process page is written for `open`, preparation, spawn, pump and `after_call` —
including the careful case "`after_call` itself raises while an execution failure is
pending" — but nothing covers "child-resource close raises before `after_call` runs at
all". The default Python behavior of the stated ordering skips `after_call` entirely:
postprocess plugins never see the real exit code, and the exception lands in
`application.py:812` producing `framework_failed(error=str(error))`, which carries no
value, with `pre_after_value` unset per `S11`. The user gets exit 70 with a
provider-close message and no record that their command ran and exited 2 —
contradicting the outcome table in `lifecycle/README.md` that promises the
`CallOutcome` is retained.

R18 introduced the distinct child/invocation scopes and fixed the *order*; it assigned
no failure semantics to the new close point. The process page's own failure-injection
list enumerates `open`, `spawned`, `interests`, `step`, `stop`, `close` and preparer
unwinds — and omits child-scope close, which is why this survived.

Record a child-scope close failure into the invocation accumulator (via
`OperationAPI.report_failure`, which `contracts.md` already defines) and never
propagate it through the wrapper's business path. `after_call` must still be dispatched
with the real `CallOutcome`. Terminations remain the exception.

### S13 — exhaustive finalization makes Ctrl-C inert during shutdown, with no aggregate deadline and no escalation

**Major.** For a termination raised *during* the finalization loop to be "retained"
rather than propagated, `failures.attempt(...)` must swallow `BaseException` and
continue. Combined with "Give each close attempt a **fresh** finite application cleanup
budget" and "Synchronous providers still cannot be forcibly timed out"
(`scopes/README.md`), total finalization is O(providers × budget) with no ceiling — and
no page in the workspace states what a *second* termination during cleanup does. The
only escalation the design specifies is for the child process (SIGTERM, 1 s, SIGKILL).

Today the very first Ctrl-C inside `api.close()` propagates immediately and ends the
process (`application.py:843-845`). Under this design an operator pressing Ctrl-C five
times during a 12-provider shutdown has each one recorded and swallowed, and cleanup
continues for minutes before the first is finally re-raised. The design converts an
interruptible shutdown into one only SIGKILL can stop, and never says so. That is
squarely the case where a stated limit ("OS termination can prevent cleanup") silently
undermines a property the reader would assume.

A related hole in the same paragraph: `state.py` catches only `Exception`, and
`finalize_destructions()` **returns** `tuple[WorkspaceCleanupFailure, ...]` rather than
raising (`application.py:832`). So `failures.attempt(destruction)` observes nothing,
`failures.has_workspace_cleanup_failure` has no defined source, and the promised
per-destruction attempts cannot be delivered without rewriting that function — which
the plan never says. `lifecycle/README.md`'s assertion that "Existing workspace-cleanup
failure precedence remains enforced" is an assertion, not a mechanism: today
`application.py:862-863` yields a definite `error="workspace state cleanup failed"`,
while the new merged return yields `error=failures.primary_framework_error`, which is
`None` when no managed defect occurred.

Add an escalation rule (second termination aborts remaining finalizers, journals the
unreleased resources, re-raises the first), one absolute aggregate finalization
deadline distinct from the per-close budget, and name the feed for workspace-cleanup
failures explicitly.

### S14 — whatever replaces R16 must not let a caller mint a trusted failure carrier

**Major, forward-looking.** R37 withdrew the `GoalResult.error` carrier, so this is not
a live defect — it is a constraint on the replacement, and it is worth recording
because the natural replacement reintroduces it.

`OperationFailure` carries `origin: PluginCallbackError | None`, and
`PluginCallbackError.__init__(plugin_id, phase, error)` is a public constructor taking
an arbitrary `plugin_id` string (`engulf-api/src/engulf_api/errors.py:13-20`), which it
stores verbatim on the instance. The withdrawn design
told core to trust a caller-constructed carrier's identity fields, hardening only the
*dispatch* path ("Handwritten caller frames cannot authorize dispatch").

The implicit assumption was that only the goal produces the returned result. That is
false: `Plugin.before_goal` returns `GoalResult[object] | None`
(`engulf-api/.../plugin.py:221-227`), and a non-`None` return short-circuits the goal —
`_HookRunner.run_before` returns that plugin's own object and `application.py:822`
assigns it. Since the status is not `REJECTED`, no `rejected_by` stamping occurs, so
the returning plugin is never named anywhere in the result. Any ordinary selected
plugin could therefore have minted a failure claiming the reserved wrapper identity and
blaming an arbitrary provider via a forged `origin`, breaking invariant 1 ("Neither
payloads nor context objects choose a caller identity") and invariant 3's "original
provider attribution".

Contrast today's behavior, which is safe: a plugin that simply *raises* in `before_goal`
is wrapped into `PluginCallbackError(item.plugin_id, "before_goal", error)` with
runtime-derived attribution (`_dispatch.py:231-235`).

Constrain the replacement: accept a carrier only if it is the identical object core
minted, or re-attribute `origin` and `call_chain` from core's own current frame and
refuse any `operation_id` the returning participant does not own. Define explicitly what
happens to a `before_goal` short-circuit result and an `after_goal` replacement result
that carries one.

### S15 — half of A's frozen surface is unreachable by any A-era consumer, and a services-aware goal cannot ship against A

**Major.** `contracts.md` freezes nine definitions. Five — `InvocationOperation`,
`OperationHandler`, `OperationAPI`, `OperationCallFrame`, `OperationCallerKind` — are
touched only by code that registers or handles an operation. In A, `register_operation`
always raises and no factory is ever called, so no A-era program can obtain an
`OperationAPI`, construct a handler, or observe a call frame. That half is frozen with
zero A-era feedback for zero A-era benefit.

Worse, a goal that calls `register_operation` on an A runtime does not degrade
gracefully. `application.py:651-662` logs and **re-raises** any setup exception:

```python
try:
    self._goal.setup(api)
except PluginCallbackError:
    raise
except Exception as error:
    diagnostics.failure(...)
    raise
```

So the `OperationUnavailableError` escapes setup and kills the whole application —
including `--help` and completion. A services-aware goal therefore cannot ship against
A at all without first guarding on `operation_support.implemented`. That is the correct
failure mode, but it means the provider-side freeze buys A's consumers nothing.

Shrink A to the consumer-facing half (`OperationSupport`, `OperationClient`, the ABC
members, the error types) and let B freeze the provider-side surface once a real
handler exists.

### S16 — the true one-way doors are the property-vs-method choices and the unrecorded ABC-vs-Protocol decision

**Major.** Most of A's freeze is safely evolvable: `contracts.md` mandates frozen
keyword-only records, so adding a defaulted field in B is source-compatible. That
correctly narrows what the freeze actually risks — and the plan does not draw the
conclusion, so it guards the wrong things.

The genuine one-way doors:

- `OperationClient.support` is a no-argument property. A consumer asking "is operation
  X available?" must issue a request and catch `unknown_operation` — the clean-install
  matrix admits this. A property cannot grow a parameter; `support(operation_id=None)`
  could have. Same for `GoalSetupAPI.operation_support` and
  `ExecutionSupport.environment_removals -> frozenset[str]`, which cannot depend on
  call mode even though `executable-support/README.md` already carves out mode-specific
  behavior for help, completion and preemption.
- `contracts.md` never says whether the new types are ABCs or Protocols. If ABCs, B can
  add a member with a default. If Protocols — the natural choice for `ExecutionSupport`,
  since the helper is third-party — adding any member breaks structural conformance for
  every implementer and the freeze is absolute. This is a one-word decision a freeze
  gate must record.
- `OperationSupport` has `api_major` only: no minor, no feature set. Recoverable via a
  defaulted field, but it is the axis a freeze normally needs.
- The closed request-code list is frozen in A but derived entirely from B's unbuilt
  runtime. Two separate 32-depth ceilings share one `call_depth_exceeded` code, and the
  ancestor-transaction rejection is folded into `lock_order` by implication. The gates
  that would surface a missing code (C-FRAME, C-LOCK, C-FAIL) all run after the freeze.
- `OperationHandler` has no per-invocation start hook while `close(api)` gets an API. A
  handler needing to act before its first request must lazily initialize inside
  `handle`. This is the most likely place B discovers it wants a third member — and
  whether that is even possible depends on the unrecorded ABC-vs-Protocol choice.

### S17 — the consumer-facing surface an implementer types first is unspecified

**Major.** The plan specifies its *runtime* semantics to an unusually falsifiable depth
and leaves the *public surface* largely absent. `architecture.md`'s own stop criterion
is "an explicit owner, bounded state, failure/cleanup behavior, and a falsifiable
acceptance case, or a named deferred decision with a gate." These fail both halves —
they are not deferred, they are unnoticed, with no ledger entry, no gate row, and no
line in the A/B sequences:

- **`services(api)`** appears in pseudocode on four active pages and is defined by one
  sentence that names neither its module, its parameter type, its return type, nor what
  it does on an A runtime — where two different `RuntimeError` subclasses are reachable
  and neither is mapped to a typed facade error. An engineer starting B3 cannot write
  the first line of `engulf-services-api`.
- **Capability, method and codec identity grammar.** The active pages say "Qualified
  capability ID" and cite the repository's identifier validation for *operation* IDs
  only. The actual rules — `CapabilityKey = (capability_id, api_major)`, reuse
  `validate_global_identifier`, "an exact positive integer, not `bool`", dot-qualified
  wire method IDs — exist only in `seed/plugin-services-v2.md:159-163` and
  `seed/plugin-services-v3.md:237-239`, which the workspace classifies as historical
  input. The active wire example even uses an *unqualified* method name
  (`"method":"read_page"`), contradicting the seed rule it silently relies on.
- **The provider handle record** has no fields; **the two service `GoalPhase` objects**
  have no IDs or field values; **nonparticipant detection** has no mechanism, despite
  `GoalSetupAPI.dispatch` being structurally unable to target a subset.

Contrast W-FAIL, which the plan tracks in four places. That is the model; apply it here.

### S18 — "broker" collides with the repo's own privilege-separation guidance, and the seed's disclaimer was dropped

**Moderate.** `engulf/README.md:216` tells operators: "Strong privilege separation
should keep the general Python application unprivileged and expose narrowly validated
privileged operations through a separate broker." The plan ships a component called the
broker that configures child transport and is explicitly not that.

The seed critique raised exactly this collision
(`seed/plugin-services-critique.md:230-231`, "Rename 'broker' or disclaim it
explicitly") and v2 added the disclaimer (`seed/plugin-services-v2.md:37`, "It is not a
privilege-separation broker"). The active plan carries the component and dropped the
sentence. An operator reading `README.md` and then seeing "selectable broker" in
release notes will reasonably conclude Engulf now has the privilege separation the
README recommends. Given `S4`, that inference is exactly backwards.

Rename it — `child-transport-config`, `endpoint-provider` — or restore the disclaimer
verbatim.

### S19 — no size, effort or staging estimate exists anywhere in 44 pages

**Moderate.** `grep -rniE 'estimate|engineer-week|person-|lines of code'` over the
active plan returns zero. For a change that adds three distributions, roughly doubles
the framework's runtime source, and requires a second-language implementation, a
decision-maker has no magnitude anchor.

Measured against the existing tree — `engulf/src` 7,493 lines, `engulf-api` 1,263,
wrapper + wrapper-api 2,315, so 11,071 total, against 8,175 test lines — the estimate
that falls out is roughly 600–900 production lines for A, and 5,600–8,900 for B in this
repo's packages (core operations runtime 900–1,500; wrapper seam 400–700;
`engulf-services-api` 800–1,200; `engulf-services` routing/directory/scopes
1,000–1,500; transport including the parser 1,600–2,700; broker 150–300; Go codec
500–1,000), plus 1,500–3,000 eclab-side lines that are unverifiable from here, plus
6,000–13,000 test lines at the repo's current 0.72:1 ratio — which the gates' PTY,
signal, fake-clock, multi-process and cross-language demands push higher, not lower.

The single highest-risk component is one paragraph: the reserve-before-allocate JSON
parser. `pump/README.md` forbids the obvious implementation, requires depth 64, 65,536
nodes, duplicate-key rejection, strict UTF-8 with surrogate rejection, safe-integer
bounds, `-0` normalization, signed-zero float preservation and incremental charged
output — then defers the implementation choice to the gate. That is realistically
400–800 lines of the most bug-prone code in the plan, with a cross-language equivalence
obligation on top. It is the schedule risk for B6.

### S20 — cross-plan coordination with the CLI parser plan is one sentence with no gate

**Moderate.** `delivery/README.md` says only: "Coordinate setup and package-list
assumptions with the goal-owned CLI parser plan. Do not replace that separate plan."
There is no gate ID, no owner, and no statement of what the interaction is.

Both plans add broadcast phases to the same `ExecutableWrapperGoal.setup` through the
same `GoalSetupAPI.dispatch`; both add a keyword-only constructor argument to the same
class; and both target `engulf-executable-wrapper-api` — which plugin-services freezes
at 1.3.0 in A while the parser plan says not to bump versions. None of that is written
down. `goal-owned-cli-parser-critique.md` is itself open with three blocking findings,
so the ordering constraint is live.

### S21 — three pages give three incompatible owners for target activation, and the literal composition double-activates

**Blocking.** `OperationAPI.dispatch` is specified three times, with three different
components owning `api.activate`:

- `activation/README.md:29-30` — the operation runtime does it:
  "activate target with a fresh generation / push participant frame(target)".
- `dispatch/README.md:37-39` — it delegates the whole body:
  `return existing_phase_dispatcher.dispatch_invocation(canonical, event,
  plugin_ids=targets, managed_context=window)`, and that function activates
  internally at `_dispatch.py:226`.
- `lifecycle/README.md:94-96` — it activates itself and then calls
  `owner.endpoint.dispatch_phase(phase, event, owner_api)` directly, bypassing
  `_PhaseDispatcher` entirely.

All three are normative text describing the same call, and the plan never names the
single owner. Only the second reuses the existing dispatcher, which
`dispatch/README.md` explicitly instructs.

Compose the two pages `managed-operations/README.md`'s subcomponent table tells an
implementer to read together — `activation` for the frame and generation rules,
`dispatch` for the body — and the result double-activates: the operation runtime calls
`api_B.activate("org.engulf.services.call")`, then `dispatch_invocation` reaches
`_dispatch.py:226` and calls `api.activate(phase.phase_id)` again.
`_capabilities.py:93-96` sees `_phase is not None` and raises
`PluginPhaseError("invocation API for B is already active")`.

That raise happens *on* line 226, which is outside the `try:` that begins on line 227
— so it is not wrapped into a `PluginCallbackError`, gets no plugin attribution, and
skips the `finally: api.deactivate()`. The failure mode is the exact opposite of what
the design is for: an unattributed framework exception from the machinery whose stated
purpose is correct owner attribution.

No ledger entry asks which component calls `api.activate` on the managed path. R01
tightens *what is compared* against frames; R03 is phase identity; R05 is deactivation
masking. Name one owner — `dispatch/README.md`'s delegation is the right choice, since
it is the only one that reuses the existing endpoint — and make the other two pages
describe rather than re-specify it.

### S22 — the execution stack has no defined push for participants entered through the existing path, so every first-hop call fails its own precondition

**Blocking.** `activation/README.md:20` makes this a precondition of every request:

```text
require stack.top is the participant frame bound to client
```

The only two pushes in the entire workspace are `activation/README.md:30` and
`lifecycle/README.md:95`, both inside managed dispatch, and `evidence.md:16` scopes
the new stack explicitly to "the new operation path". Nothing pushes a frame for a
participant activated the ordinary way — by `_HookRunner` through
`_PhaseDispatcher._dispatch` at `_dispatch.py:226`, or for the goal at
`application.py:806`. There is no stated root or empty-stack rule.

So every managed call chain begins with a participant that has no frame. Trace
`architecture.md`'s own headline sequence: `App->>A: Activate A; before_goal(api_A)`
then `A->>Ops: api_A.operations.request(service request)`. A was activated by
`_dispatch.py:226`; the stack is empty; `stack.top is <A's frame>` evaluates against
`None` and rejects. The first call of the first consumer in the architecture diagram
fails.

The same applies to the goal path that carries all of Delivery B's transport value:
`application.py:806` does a bare `goal_api.activate("goal.achieve")` — not a dispatcher
call — and the wrapper session then retains that goal client to issue `ExecuteChild`.

R01 is the reverse direction: it presumes the frames exist and tightens what is
compared against them. C-FRAME is worded entirely around the negative case ("B cannot
borrow active A/goal/handler clients"); nothing gates a goal-originated or
hook-originated first hop, which is every real call. State who pushes a frame for
ordinarily-activated participants — the cleanest answer is that the same code that
calls `activate` pushes, which makes `S21`'s single-owner decision load-bearing.

### S23 — the packaging rollout was falsified by the commit that followed the one it snapshotted

**Blocking.** `delivery/packaging.md` "Foundation candidates" records observed
versions and derives A candidates and floors from them:

| Distribution | Plan's "observed" | A candidate | Actual at `4c7e95e` |
| --- | --- | --- | --- |
| `engulf-api` | 1.3.0 | 1.4.0 | **1.0.0** |
| `engulf` | 0.3.0 | 0.4.0 | **0.1.0** |
| `engulf-executable-wrapper-api` | 1.2.1 | 1.3.0 | **1.0.0** |
| `engulf-executable-wrapper` | 0.3.0 | 0.4.0 | **0.1.0** |

Every observed value is wrong, and the derived A candidates are now three minor
versions *ahead* of reality. The prescribed floors (`engulf-api>=1.4,<2`,
`engulf>=0.4,<1`, wrapper-api `>=1.3,<2`) name versions that do not exist; the real
floors are `engulf-api>=1.0,<2` and `engulf>=0.1,<1`.

The cause is commit `4c7e95e` "chore: establish beta baseline", which reset all four
versions and rewrote every floor — the commit immediately after `4bac606`, which is
the head `delivery/design-validation.md` records as its snapshot. So the rollout was
stale within one commit of being written.

This is not only a number-refresh. The plan's rollout rationale is that A's floor bump
moves ecosystem churn earlier and off the critical path, and
`package-inventory.md`'s 45-row table plus `source-snapshot.json` are built on the same
stale reads. The whole packaging component needs re-deriving, and `S7`'s observation —
that the real floors are wide enough to admit every broken mixed-version combination —
is a direct consequence of the floors this table never saw.

Add a refresh step to A3 that re-reads versions at implementation time rather than
trusting a recorded snapshot, and state in `design-validation.md` that recorded
version observations expire.

### S24 — several recorded validation results are vacuous, on a page the verification matrix treats as discharging obligations

**Major.** `delivery/verification.md:3` makes recorded results load-bearing: "These are
implementation obligations **unless a result is explicitly recorded in design
validation**." Two of `check_design.py`'s five checks are genuine —
`check_current_frame`, and `check_scope_dags`, whose `require((new_order is None) ==
cycle)` really does cross-check admission against cleanup across all 543 four-vertex
DAGs. Others assert values constructed immediately above the assertion.

`design-validation.md` claims "a later success with no value could not remove the saved
outcome or managed failure". The code (`check_design.py:136-145`):

```python
final = {
    **after_hook_result,          # {"exit_code": 0, "value": None}
    "exit_code": 70,
    "value": saved_goal_value,
    "error": latched_failure,
}
require(final["value"] is actual_outcome, "Preserve actual child outcome")
require(final["exit_code"] == 70, "Success rewrite must not clear managed failure")
```

The later keys in the same dict literal override the hook result. The assertion checks
a value written two lines above it. Invert the design's policy and the check still
passes, because the policy is not modelled — only the desired answer is written down.

Likewise for "Three failed-batch positions blocked all modeled deletion"
(`check_design.py:219-235`): `failed` is set true exactly when `batch == fail_at`, and
every `fail_at` in `(0, 1, 2)` is less than `range(3)`, so
`require(deletions == int(fail_at is None))` restates the loop's own control flow.

This matters more than a normal test-quality complaint, because
`design-validation.md:64-67` already diagnoses this exact failure mode — it names "the
earlier dictionary-based failure model" as the reason the `GoalResult` mismatch (R37)
was missed — while citing the same dictionary-based model unchanged in the table above.
The diagnosis was made and not generalised.

Either model the policy under test (a function that takes the design's rule and can be
made to fail) or downgrade these rows from "Passed" to "illustrative, not falsifying",
and remove them from the set of results `verification.md:3` lets discharge an
obligation.

### S25 — the image-offer pseudocode hands a live API and a client-bearing closure into the worker pool it promises never to give one

**Major.** `eclab/image-providers/README.md` states the rule twice — "The lookup closure
runs synchronously inside image-build's active preparation", "Build workers receive
resolved recipes only" — and promises to "Prove ... no build worker receives a managed
API". Its own pseudocode does the opposite:

```text
def lookup(requirement):
    ...  typed_image_client(provider).offer(requirement)   # -> api.operations.request

provision_image_graph(graph, api=api, provider_lookup=lookup,
                      max_workers=existing_jobs_option)
```

Both the live, thread-bound `api` and the closure that calls through it are passed
*into* the function that owns the `max_workers` pool. Resolution is what `lookup` does,
so "workers receive resolved recipes only" holds only if `provision_image_graph` calls
`provider_lookup` exclusively on the calling thread — a contract the design never
states and never gates. If any node resolves inside the pool, `activation/README.md:17`
rejects on `invoking thread == client.owner_thread` and every offer from all six
adapters fails, falling through to the synthetic pull that
`image-providers/README.md` explicitly forbids as a substitute.

R23 and R24 cover method readiness and tie precedence; neither touches thread affinity.
`activation/README.md` states the general rule correctly ("Build workers receive
resolved data only") — the concrete consumer page contradicts it in pseudocode.

Either state and gate that `provider_lookup` is invoked only on the calling thread, or
resolve the whole graph before `provision_image_graph` is entered and pass it resolved
recipes, which is what the prose already claims happens.

### S26 — sleep's barrier proves write ordering, not the freshness of the inventory the deletion plan is computed from

**Major.** Invariant 8 and `eclab/sleep/README.md` enumerate exactly three conditions
that permit no deletion: "Unknown inventory, partial page reads, or failed commit
acknowledgment". Staleness of a *complete, successfully read* inventory is not among
them, and nothing between `registry.records()` and `execute_deletions(plan)`
re-validates it.

The design widens the window it is silent about. R19/R20 replaced a single-call read
with a multi-page immutable snapshot — 320 pages for the plan's own 1.2 MB fixture —
and `snapshots/README.md` makes the staleness a *guarantee*: "All pages refer to the
original immutable snapshot even if another process commits between pages", with "No
lock remains held while the consumer processes a page". The same page then forbids the
only mechanism that could detect the drift: "no new revision/CAS or observation
timestamp protocol is implied".

So: sleep reads L1 (stopped, image `I`) at T0 and releases the transaction. While it
pages and plans, another process deploys L2, which also uses `I`, and the registry's
own `after_goal` persists it. Sleep's shared-image preservation filter — the thing
standing between the design and deleting an image another lab needs — was computed over
the T0 snapshot, where `I` looked unshared. Its commit touches only L1's key, so every
batch acknowledges successfully and the barrier opens. `I` is deleted out from under
L2.

R21 covers acknowledgment prefixes, R22 covers corrupt reads mis-typed as empty, R20
resolves intra-read divergence by making the snapshot immutable — which creates this
case rather than fixing it. The page's disclaimers are honest about Docker atomicity
and about `eclab-sleep:docker` not being a global lease, but none of them says that a
complete, successfully-read inventory may be stale by the time deletion starts.

The honest minimum is to say so in invariant 8. The real fix is a recency check at the
barrier — re-read the inventory under the commit transaction and abort if the
eligibility set changed — which is cheap because sleep already holds its lease and
already does one more transaction.

### S27 — "complete observation" is a quality predicate, not a recency one, so consumption's polling loop can clobber fresher deploys

**Major.** The registry's only write rule is "replacement of image IDs only by complete
observation" plus "Commit order retains existing last-complete-observation merge
semantics; no new revision/CAS or observation timestamp protocol is implied".
Completeness describes how well the observer saw Docker at its sampling instant. It says
nothing about *when*. With multiple processes writing and merge resolving by
commit-arrival order, a complete-but-old observation legally overwrites a
complete-and-newer one.

`eclab/consumption/README.md` specifies exactly the loop that produces this: sample
Docker, commit complete observations, wait two seconds, repeat, for the whole duration
of a long-lived `eclab consumption` command — an unbounded stream of writes derived from
samples that are seconds old by the time they commit.

Concretely: consumption samples L1 → `{OLD}` at T=0.0 and takes ~0.4 s to render and
round-trip. At T=0.1 a separate `eclab deploy L1` persists a complete observation
L1 → `{NEW}`. At T=0.4 consumption's commit merges its *complete* observation and
last-complete-wins replaces the image set with `{OLD}`. The acknowledgment is explicit
and successful; no error, no warning, no revision conflict, because none is defined.
The corrupted field is precisely the image-ownership data `S26`'s deletion filter reads.

No ledger entry examines the write-merge rule across processes.
`snapshots/README.md` presents "no revision/CAS" as a scope reduction that "preserves
the required barrier" — it does not, for anything except sleep's own writes.

The cheap fix is a monotonic observation sequence or timestamp per `(lab, observer)`
with last-*newest*-wins rather than last-arrival-wins; it changes the record format,
which is why it should be decided before the migration rather than after.

### S28 — local services are gated behind the wrapper process seam by a premise the source contradicts

**Major.** The plan's only route to registering a managed operation is the wrapper's
`execution_support` helper. `eclab/application/README.md` shows both construction paths
as `ExecutableWrapperGoal(..., execution_support=make_containerlab_execution_support())`,
and `executable-support/README.md` asserts: "The local services helper registers its
operation during setup even without a child broker, so installing it into A's
deliberately rejecting wrapper cannot work."

But `Goal.setup(self, api: GoalSetupAPI) -> None` is a **non-abstract** method on the
ABC — `goals.py:237`, a docstring and nothing else — and `ExecutableWrapperGoal(Goal[CallOutcome])`
(`goal.py:253`) is an ordinary subclassable class. A `ContainerlabGoal(ExecutableWrapperGoal)`
overriding `setup` to call `super().setup(api)` and then `api.register_operation(...)`
registers the services operation with no wrapper API change at all.

The consequence is sequencing, and it is expensive: B2 (the wrapper seam, the process
strategy, the Windows stub, the PTY and signal gates) sits on the critical path to B4,
the registry migration that is the only user-visible benefit the plan names. It does not
need to. Re-cut B as B1 → B4 → B5 and let the wrapper seam follow the transport it
actually exists to serve.

## Recommended sequence

1. **Close the freeze before freezing.** Fix `S1` (delete the withdrawn carrier from
   the authoritative page), book `S2` (`framework_failed` needs `value`), decide
   `S16`'s ABC-vs-Protocol question in one word, and convert the three no-argument
   properties to methods. Re-derive `S23`'s packaging table from the current tree.
2. **Name one owner for activation** (`S21`) and state who pushes a frame for
   ordinarily-activated participants (`S22`). These are specification bugs in the
   mechanism everything else rests on, and both are cheap now and expensive after B1.
3. **Shrink A** to the consumer-facing half of its surface. The provider-side
   definitions are unreachable by any A-era consumer and gain nothing from being frozen
   early (`S15`).
4. **Re-cut B around B4.** `Goal.setup` is overridable (`S28`), so the registry fix does
   not need the wrapper seam. Sequence B1 → B4 → B5 and let B2/B6/B7 follow a consumer
   that actually asks for a child grant. That moves the only user-visible benefit the
   plan names — fresh registry reads and a real persistence barrier — from roughly 26
   weeks out to roughly 12.
5. **Before building the child transport at all, name its caller.** If there is none,
   the local-equals-wire rule loses its justification, and with it `snapshots/`, the
   per-caller slot limits, snapshot expiry and the one-deadline facade — several hundred
   lines of contract. If there is one, then `S3`, `S4`, `S5` and `S10` are prerequisites,
   not polish.
6. **Decide the two domain-semantics questions before the migration**, because both
   change the record format or the barrier: snapshot recency at the deletion barrier
   (`S26`) and last-arrival-wins merge under a two-second polling writer (`S27`).

Two changes are worth landing independently of services, because they fix real defects
in today's runtime: exhaustive individual finalization in `Application._invoke`
(`application.py:831-845` currently skips every later close when one raises), and
preserving the pre-after-goal result value on framework failure.

## Limits of this review

- **Sibling repository not read.** Every claim about the registry, consumption, sleep
  and image plugins rests on the plan's own description. `S8`'s dependency-floor
  conclusion and `S9`'s blast radius are reasoned from in-repo machinery plus the plan
  text, not from those wheels' metadata.
- **Both snapshots moved during the review** (see the header). Findings against pages
  edited after 09:33, or against commits after `4c7e95e`, may already be stale.
- **Coverage is uneven.** Eight dimensions and five adversarial lenses were completed
  by grounded agents with independent refutation of the lens findings. The dimensions
  marked *(single-pass)* in the ratings table, and one planned lens on resource bounds
  and deadline arithmetic, were not — a rate limit ended the run. The bounds lens is
  the notable gap: the numbers in `pump/README.md`, `scopes/README.md` and
  `snapshots/README.md` (1 MiB / 4 KiB / 32 MiB / 64 KiB / 16 / 32 / 64 / 65,536 / 30 s
  / 5 s / 100 ms / 24 h) were not systematically cross-checked for conflicts.
- **No refutation pass ran on the criterion weaknesses**, only on the lens findings.
  Where a criterion weakness is reproduced above as a numbered finding, I verified it
  against source myself; where it appears only in the ratings commentary, I did not.
- **Two agent citations were corrected against source**: the real dependency floors are
  `engulf-api>=1.0,<2` and `engulf>=0.1,<1`, wider than reported, which strengthens
  `S7`; and `framework_failed` has nine call sites, not four.
