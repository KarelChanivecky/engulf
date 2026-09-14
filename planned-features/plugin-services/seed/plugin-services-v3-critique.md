# Critique: optional plugin services, implementation plan v3

Reviews [plugin-services-v3.md](plugin-services-v3.md) against the Engulf runtime at
`4bac606` (current `master`), its predecessor [v2](plugin-services-v2.md), and the
[v2 critique](plugin-services-v2-critique.md). Line references point at that commit.
`goal.py` means `engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py`.

Status: open. Findings below are `D*`. `B*`/`S*` are the original critique, `R*` the
synthesis review, and `C*` the v2 critique.

**Scope limit, stated up front.** Every Engulf-side claim in v3 was verified. The six
`../../engulf-clab/` rows in §2 and the whole of §6 were **not** — reviewing the
sibling checkout is outside this repository's scope by standing instruction. Those
paths do resolve correctly from this document's location, which is all I checked.
Roughly a third of v3 therefore carries no verification from this review, and
`D1`/`D2` are about the seam between the two repositories rather than the migrations
themselves.

## Verdict

v3 is not a revision of v2; it is a different plan that happens to share v2's back
half. It independently fixes eight of the eighteen `C*` findings (listed below), and
its most technically delicate new section — the cross-participant lock rules — is
correct in a way I did not expect: it is the existing per-participant invariant lifted
to a stack, not an invented hierarchy. The evidence discipline that made v2 worth
reading survives, and one anchor v2 got wrong is fixed.

Against that, v3 makes two bets that together roughly double the plan: a new generic
facility in `engulf-api`/`engulf`, and four cross-repository plugin migrations
sequenced *before* the transport that was v1's original point. Both are defensible on
their merits. Neither is costed. The result is a plan that freezes three public
contracts before any consumer exercises them (`D3`), narrows a documented core
guarantee for every application in the workspace without saying so (`D4`), and
schedules two stages of cross-repo work that cannot be installed anywhere until a
release §11 explicitly defers (`D1`).

`D1`–`D4` block a stage start. `D5`–`D9` are v3-specific gaps. `D10`–`D15` are
findings v2 carried that v3 did not close.

## Verified, and credit where it is due

Every Engulf-side anchor in §2 is correct: `plugin_api.py:37` and `:143`,
`_dispatch.py:224` and `:230`, `_plugin_execution.py:81`, `application.py:750`,
`_capabilities.py:66` and `:245`, `errors.py:13`, `goal.py:375` and `:837`,
`application_definition.py:106`, `ci.yml:27`. The `_ActivationState` anchor that v2
placed at line 88 is now correctly at 66.

The load-bearing new claim in §2 — "ordinary plugin callbacks have no dispatch
capability" — is true: `InvocationAPI` (`plugin_api.py:37-97`) exposes leases,
context, and state but no dispatch; only `GoalAPI` (`139-156`) has it. If services
must be callable from `before_goal`, a core entry point really is required. The
architecture bet follows from the evidence.

**§3's lock rules are right, and are the best part of v3.** I checked them against
`_LockCoordinator` rather than taking them on trust. Today, per participant:
`claim_leases` refuses a lease while a transaction is held (`_capabilities.py:333-336`)
and refuses nested leases (`337-338`); `claim_transaction` refuses nested transactions
(`317-320`) but permits a transaction under a held lease. The existing global order is
therefore leases-before-transactions, and v3's three stack rules are exactly that order
extended across participants — reject dispatch under an ancestor transaction, permit
descendant transactions under an ancestor lease, forbid a second external lease. A
`transaction_active` property already exists at `352-354` for the first check.
Because both lock kinds take finite timeouts, the order is also sufficient: no
participant can request a lease after a transaction, so the wait-for graph cannot
invert. Say this in the plan — the rule reads like invention and is not.

Also verified: per-plugin `RuntimePluginAPI` instances mean "descendant deactivation
releases only descendant locks" is automatic (`_dispatch.py:239-240` →
`plugin_api.py:79-85`), and the generation guard v3 wants for stale clients already
exists as `require_current` (`_capabilities.py:114-116`).

**Closed since v2, without having seen the v2 critique:** C5 (a disabled session now
"keeps ordinary blocking process waiting", §7), C16's latency trap ("pending replies
request an immediate iteration/write readiness", §7), C11's default grants ("the
default grants no child access", §4) and frozen-vs-dynamic removals (§7), C12 (the
wrapper README update is now named, §7), C15 (the child's install closure is spelled
out, §4), C18 (the incorrect "core dispatch cannot attribute them" reasoning is gone,
§4), C14 (§10 states the Go client is not a published SDK), C9 (the server now "checks
the remaining budget before dispatch", §9), and most of C7 — §9 explicitly says "do
not assume sixteen maximum-sized request/reply pairs plus parser objects all fit the
aggregate cap" and adds a resource-admission error case. v2's reverse-first-use
cleanup becoming dependency-ordered cleanup (§5) is a straight improvement.

## Blocking

**D1. Stages 3 and 4 produce cross-repository changes that cannot be installed until
a release §11 defers.** The migrations depend on the stage-1 core facility. §11 keeps
`engulf-api`, `engulf`, and `PLUGIN_API_MAJOR` at their current versions, and §6 says
"dependency floor changes accompany a separately authorized release". Sibling plugins
declare floors in the style of `engulf-api>=1.0,<2`
(`plugins/engulf-plugin-list/pyproject.toml`), which an unbumped `engulf-api` 1.3.0
satisfies whether or not it has `operations`. So during stages 3–4 the migrated
plugins are installable against a core that lacks the facility, and §6's promise that
"mixed incompatible installations fail clearly" has no mechanism behind it — the only
mechanism is the floor bump that is deferred. The failure mode is an `AttributeError`
inside a plugin callback, which the runtime reports as that plugin's callback failure.
- **Recommendation:** state the cross-repo sequencing explicitly: what the sibling
  consumes during development (editable installs of an unreleased core, presumably),
  what runtime check produces the "clear failure" before floors can express it — a
  capability probe at setup is the usual answer — and which repository's change lands
  first. Until that is written, stages 3 and 4 have no defined delivery.

**D2. §6 presupposes an engulf-clab application change it never names.** Only the goal
can register operations (`GoalSetupAPI.register_operation`, §3), and §4 says "the base
goal factory installs services integration" and that the goal owns
`ServicesConfiguration` — accepted capability descriptors, defaults, local participant
access, grants. Every migration in §6 is a *plugin* change. None of them works until
the clab application's definition installs the facility and accepts the registry and
image capabilities, and §6 never mentions that file, that configuration, or who owns
it. Its migration ordering advice ("migrate each producer/consumer set coherently")
reads as if plugins could move independently; they cannot move at all before the
application does.
- **Recommendation:** add the application-side prerequisite to §6 as its first
  migration step, with the accepted-descriptor and access configuration it needs.

**D3. Three public contracts are frozen before any consumer exercises them.**
- Stage 1 ships `InvocationOperation`, `OperationClient`, `OperationHandler`, and
  `OperationAPI` into `engulf-api` — the workspace's stability anchor, described in
  `AGENTS.md:9-13` as the stable interface package — with its only consumer arriving
  in stage 2.
- The protocol specification and vectors land in stage 2; the Go client that would
  falsify them lands in stage 5, now with two migration stages in between. This is C2,
  and v3 has made the gap wider rather than narrower.
- The wrapper-api seam (§7) still gives parameter shapes without return types: what
  `step(ready)` returns, what `interests()` elements are, whether `launch` is a method
  or a value, what `close(end)` returns, and the name and shape of the `end` value.
  This is C3 unchanged, in a package already published at 1.2.1.
- **Recommendation:** pull one consumer forward into each freezing stage. For the core
  facility, land the stage-2 facade skeleton against it in stage 1 and treat compiling
  the two together as the gate. For the protocol, move a Go vector runner — decoder
  and encoder only, no transport — into stage 2. For the seam, write the signatures
  before stage 5 rather than during it.

**D4. v3 narrows a documented core guarantee for every application, not just services
users.** §3: a latched framework failure survives "transforming a result in
`after_goal`". Today `after_goal` is the last word: `run_after` returns `current`
(`application.py:824-830`) and the `finally` never revises the result.
`engulf/README.md:374-386` documents the pipeline as eight steps in which step 7 is
the last one that can change the outcome. v3 inserts a ninth behavior between 7 and 8
that outranks outer middleware, and applies it to applications that never register an
operation. §11's documentation list says "mandatory finalization" but does not say
that the outer-plugin result-transform contract is being narrowed.
- **Recommendation:** name the change, update the numbered pipeline in
  `engulf/README.md`, and decide explicitly whether the latch applies when no
  operation was ever registered. If it does, this is a core behavior change that
  deserves its own stage-0-style repair with its own tests, not a clause inside a
  services plan.

## v3-specific gaps

**D5. The nested-failure contract needs a concrete type decision.** §2 and §3 require
that C's defect is "reported as C through B/A" and that runners "must not relabel C's
failure as B's". `PluginCallbackError` carries exactly `plugin_id`, `phase`, `error`
(`errors.py:13-20`), so preserving an origin and a chain means either adding fields to
a published `engulf-api` exception or introducing a new type that dispatch and both
hook runners must learn to pass through unchanged. The plan does not say which. This
type's documented shape has already drifted once — the stale `completed_plugin_ids`
example at `engulf-api/README.md:266` and the matching prose at `AGENTS.md:139-140`
are in v3's own stage-0 repair list — so leaving it implicit is how that recurs.

**D6. Readiness now depends on preprocessing order, and the only mechanism to
guarantee it is the dependency edge v2 forbade.** §4: "Ordinary service requests
require the target to have successfully completed `before_goal`." For §6's consumers,
which call from `before_goal`, availability is therefore decided by the resolved
preprocess order. v2 §3 said "do not add plugin dependency edges merely to express
service preference"; under v3 a `before_goal` service call is a genuine callback
ordering dependency and the edge is the correct answer — but §4 only says "preserve
packaging dependencies", and §6 only says "preserve existing packaging order edges".
Neither says a consumer must *declare* one, so the first symptom is an intermittent
`ProviderNotReady` that depends on installed plugin set.

**D7. The scope dependency graph forbids B → A for the rest of the invocation once
A → B has happened, and the cost is not stated.** §5 rejects an edge that would create
a cycle "even when the earlier calls have already returned". Two providers that call
each other at different points in one invocation are therefore incompatible, the
rejection is a runtime error rather than a setup error, and it depends on call order
within the invocation, so it can be latent for a long time. The justification given is
cleanup ordering, which is real; the alternative — allow it and order cleanup by
strongly connected component or first use — is not discussed. Say why the stricter
rule was chosen, and say that the restriction exists, so capability authors can design
around it.

**D8. The 4 KiB minimum receive limit is defined without reference to what a directory
costs.** §9 sets the `hello` bootstrap payload limit and the minimum legal receive
limit both at 4 KiB, requires `ready` to carry the sorted granted provider/method
directory plus filtered defaults, and makes an oversized directory a hard handshake
rejection ("reject an unadvertisable directory"). §6's image capability advertises "each
supported recipe kind" with paths, authority, rejection, and fallback metadata — the
one capability in the plan most likely to exceed 4 KiB. A conforming minimal client
would then fail at handshake with no path forward short of raising its own limit.
- **Recommendation:** either set the floor from a worked directory size for the image
  capability, or define a directory-fetch operation so `ready` need not carry it all.

**D9. The 24-hour deadline cap is the wrapper's worst-case unresponsiveness bound.**
§9 caps `remaining_timeout_ms` at 86,400,000 with a 30,000 default. §9 also concedes
that "a synchronous call chain can delay polling beyond a transport turn's byte
budget", and §7 gives the wrapper a single-threaded pump. A 24-hour call is therefore
24 hours of no child polling. Nothing in v1's stated use cases needs minutes, let
alone a day. Justify the cap or lower it; it is the only number in the table that sets
a bound on how long the wrapper can stop responding.

## Not closed from the v2 critique

**D10 (was C8).** Proxy fan-in versus the default deadline is improved but not closed.
§9 adds deadline-aware admission for waiting callers and says proxies "reject expired
work before forwarding". Neither covers work that has not expired yet but cannot
possibly start in time: sixteen downstream connections serialized through one upstream
leg still means the last request needs everything ahead of it to finish inside its own
30-second budget. State that a proxy refuses work it cannot start within the request's
remaining budget, and that this refusal is recoverable rather than a session close.

**D11 (was C10).** `error.kind` is still undefined. §9 says errors carry "a stable
kind/code" and then enumerates cases that all read as codes. A Go client must switch
on `kind` and cannot know its range.

**D12 (was C13).** Still no operator-facing view of the service directory. v3 mentions
diagnostics only for error reporting (§3, §7, §9). The repo's own precedent is a
separate distribution publishing a diagnostic and a before-separator trigger
(`plugins/engulf-plugin-list/pyproject.toml`). With §6 adding grants, readiness, and
per-capability descriptors, "why did this request return `not_granted` / `not_ready`?"
becomes a question an operator will ask, and the plan has no answer that does not
involve running the goal under a debugger.

**D13 (was C4).** Capability payload interop is still unverified. §9's vectors cover
the envelope; §6 requires Go-side codecs for requirement parameters and every recipe
kind; nothing requires a capability package to ship its own cross-language vectors.
§10's "shared local/Python/Go vectors" conflates the two layers.

**D14 (was C1).** Proxies remain in v1 (§8, stage 5). The case for deferring them is
stronger now, not weaker: v3 has added a core facility and four migrations to the same
release, and proxies still serve no outcome in §1 beyond demonstrating themselves.

**D15.** The baseline is not reproducible. §2 pins Engulf `4bac606` and engulf-clab
`5f3afae`, then adds "together with the inspected working-tree state". A reviewer
cannot reconstruct an uncommitted working tree, so any §6 finding that rests on it is
unverifiable by construction — including by a future reader of this plan.

## What to do

| # | Action | Where |
| --- | --- | --- |
| D1 | Define cross-repo sequencing and the pre-floor compatibility check | §6, §10 stages 3-4, §11 |
| D2 | Add the clab application-definition prerequisite as §6's first step | §6 |
| D3 | Pull a consumer into each freezing stage: facade into 1, Go vectors into 2, seam signatures before 5 | §7, §10 |
| D4 | Name the `after_goal` narrowing, update the documented pipeline, decide whether it applies without operations | §3, §11, `engulf/README.md:374-386` |
| D5 | Decide whether `PluginCallbackError` gains an origin/chain or a new type is introduced | §3 |
| D6 | State that a `before_goal` consumer must declare a packaging order edge on its provider | §4, §6 |
| D7 | State the scope-graph restriction's cost and why it beats SCC-ordered cleanup | §5 |
| D8 | Set the receive-limit floor from a worked image-directory size, or add directory fetch | §9 |
| D9 | Justify or lower the 24-hour deadline cap | §9 |
| D10 | Proxies refuse work they cannot start within its remaining budget | §8, §9 |
| D11 | Define the `kind` taxonomy | §9 |
| D12 | Decide whether a service-directory diagnostic exists | §4 or §10 stage 6 |
| D13 | Require per-capability cross-language codec vectors | §9, §10 stage 2 |
| D14 | Defer proxies; keep their wire affordances reserved | §8, §10 stage 5 |
| D15 | Pin a committed sibling baseline or mark §6 claims as unpinned | §2 |
