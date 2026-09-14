# Critique: optional plugin services, implementation plan v2

Reviews [plugin-services-v2.md](plugin-services-v2.md) against the runtime at commit
`4bac606` (current `master`), the [original critique](plugin-services-critique.md),
the [synthesis](plugin-services-critique-synthesis.md), and the
[synthesis review](plugin-services-synthesis-review.md). Line references point at that
commit. `goal.py` means
`engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py`.

Status: open. Findings below are `C*`; `B*`/`S*` are the original critique and `R*`
the synthesis review.

## Verdict

v2 is a large improvement and most of it is correct. I spot-checked every anchor in
§2 plus fifteen further claims (listed under "Verified") and found one trivial
imprecision. The design fits the runtime: broadcast setup with attributed filtering,
targeted invocation dispatch, a goal-owned helper, an explicit failure latch, and
explicit close traversal are all the right reading of what the code actually does.
§11 discharges every `B*`/`S*`/`R*` finding, which is what R8 asked for.

The problem is now the opposite of v1's. v1 was underspecified; v2 declares itself
*closed* — §7 says its choices are "fixed for that document, not open implementation
questions", and §11 "closes architecture decisions for implementation". That claim is
not yet earned. Five findings block a stage start (`C1`–`C5`), seven are
contradictions, undefined behavior, or wrong reasoning inside sections that declare
themselves fixed (`C6`–`C11`, `C18`), and five are omissions in the touch list and the
deliverables (`C12`–`C16`). None of them is architectural: the shape of the design
survives all of them. They are the difference between a plan an implementer can follow and a plan an
implementer has to finish.

Separately: v1 is still 709 lines of work before anything ships, and the largest
single block of it — descendant proxies — serves no stated outcome. That is `C1`.

## Verified

These held up exactly as written, so do not re-litigate them:

- Every §2 anchor: `plugin_api.py:125-136` and `143-156`, `goals.py:218-226`,
  `_dispatch.py:224-265`/`226`/`230-240`, `application_definition.py:106-133`,
  `application.py:798-845` and `623-665`, `plugin_api.py:79-91`, `errors.py:13-20`,
  `goal.py:375-415`/`433-475`/`837-904`/`851-868`/`335-344`/`854`, `ci.yml:27-34`.
- `framework_failed()` really has no `value` parameter (`goals.py:94-101`), and the
  direct `GoalResult` constructor accepts `value` with `FRAMEWORK_FAILED`
  (`goals.py:39-56`). The plan is right to name the constructor.
- `diagnostics.failure()` only emits a mandatory record (`diagnostics.py:336-363`); it
  cannot change a result. §4's insistence on an explicit latch is well-founded, and
  §8 is right that `isolate_failures=True` swallows status: `_dispatch.py:230-241`
  drops the failing plugin's contribution and returns, and a close phase contributes
  `None` anyway, so an isolated close failure is indistinguishable from success.
- `edition(..., require_plugins=...)` and `required_plugin_ids` exist under exactly
  those names (`application_definition.py:106-133`, `34`), and `fork()` preserves
  `goal_factory` (`135-169`).
- `describe` is a real private action (`completion.py:30-42`, `completion_cli.py:37`)
  and is the correct carrier for `environment_removals`.
- `test_goal.py:729-814` is the readiness/signal harness and `270-306` is the
  environment-overlay test. Both citations are right way round.
- `completed_plugin_ids` is stale in both places named: the example at
  `engulf-api/README.md:266` and the prose at `AGENTS.md:139-140`.
- The CI omission is a present failure, not future work:
  `examples/encryption-app` declares `engulf-encryption-example-core>=0.1,<1`,
  `ci.yml:27` installs it `--no-deps` without `examples/encryption-core`, and
  `engulf_encryption_example/__init__.py:5` imports the core at module import before
  `ci.yml:34` runs it.
- Counts and touch points: `README.md:7,50,115`, `AGENTS.md:353`,
  `goal-owned-cli-parser.md:195`; `Makefile` `PACKAGES` + `DIR_<pkg>`; local ruff
  already covers `plugins`/`examples` (`AGENTS.md:348-349`), so "two new top-level
  directories" is exactly right; `engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper`
  is the real catalog (`plugins/engulf-plugin-list/pyproject.toml`).
- "local-execution contracts" is the repo's own term
  (`engulf-executable-wrapper-api/README.md:510-513`), and `engulf/README.md:214-216`
  is the privilege-separation broker v2 correctly disclaims.

One imprecision: §2 cites `_ActivationState` as "lines 88–116". The class is
`_capabilities.py:66-133`; 88–116 is its activate/require block. Harmless, but the
plan's authority rests on anchors being checkable.

## Blocking

**C1. Descendant proxies are the largest thing in v1 and serve no stated outcome.**
§1's outcome is "a portable Python goal and a wrapped Go executable will exercise the
same capability with two interchangeable providers". Proxies are not needed for that.
They are, however, the source of most of the protocol's difficulty: the 16-connection
cap, fair round-robin scheduling, the 32 MiB aggregate accounting, upstream/downstream
ID remapping, `remaining_timeout_ms` decrementing, downstream revocation cascades,
directory sub-filtering (§4), the dedicated I/O thread (§6), and a whole stage-5 test
column. `C6` and `C7` below are both proxy-only problems.
- **Recommendation:** implement the direct-child case in v1 and defer proxies. Keep
  the *wire* affordances that make proxies additive later — the `id` field, grants as
  a filtered triple set, `remaining_timeout_ms` — and mark them reserved in the
  normative document so adding proxies is not a protocol break. Drop the scheduling,
  aggregate accounting, connection cap, and cascade rules from v1. If proxies must
  stay, say which use case requires them; "a descendant might want access" is a
  capability, not a requirement.

**C2. The protocol is frozen in stage 1 and the second language does not appear until
stage 5.** §7 correctly calls v1 "a cross-language commitment", and stage 1's gate is
"reviewed request/reply/handshake schemas and numeric/resource limits" — reviewed by
reading. The claims most likely to be wrong are exactly the ones only a compiler can
check: `json.Number` handling, `-0` sign preservation, `1e400` rejection, the safe
integer range applied "after parsing the agreed JSON number grammar", and whether
`ready` can be encoded inside the bootstrap bound. Discovering any of those in stage 5
means a protocol v2 or a silent divergence.
- **Recommendation:** move a minimal Go encoder/decoder — no transport, no client,
  just the vectors — into stage 1, and make "the Go vector runner passes" a stage-1
  gate. It is a few hundred lines and it is the cheapest possible insurance against
  the one class of error this plan cannot absorb.

**C3. The wrapper-api seam is new public frozen API and the plan defines only half of
it.** §5's table gives parameter shapes for eight members and a return type for
exactly one (`open()` → session or `None`). Unspecified: what `step(ready)` returns
(nothing? work-performed? a request for an immediate iteration?); what `interests()`
elements are; whether `launch` is a method or a value; what `close(end)` returns and
what "reports cleanup failure" means at the type level; the name and shape of the
`end` value that "distinguishes preparation failure, spawn failure, child exit,
infrastructure failure, and termination" and "carries the actual call outcome when one
exists"; whether `open()` raising is a legal disabled path alongside returning `None`.
This lands in `engulf-executable-wrapper-api`, which is already published at 1.2.1, so
it is the one part of this plan that cannot be revised later without a major.
- **Recommendation:** write the protocol definitions and the frozen value types out in
  full before stage 3 starts, and put them in §5 rather than leaving them to the
  implementer. §5 already gets the hard parts right (`setup` stores immutable
  configuration only — correct, since the runtime closes the setup API at
  `application.py:663`; `spawned(pid)` receives no `Popen` — correct, that is B3). The
  signatures are the cheap part and they are the part that gets frozen.
- Related mechanism gap: §5 says "distinguish provider termination exceptions" and
  "do not wrap provider dispatch in that special handler", but the wrapper cannot tell
  where a `KeyboardInterrupt` was raised from the outside. Say that provider dispatch
  runs inside its own guard that tags the exception, or implementers will reproduce
  today's ambiguity in a new place.

**C4. Envelope interop is verified; capability payload interop is not.** §7 puts
conformance vectors in `engulf-services/protocol/` for framing, JSON, and envelopes,
and says "trusted capability packages supply executable local codec bindings". The Go
child must independently implement each capability's request/result codecs. Nothing in
the plan requires a capability package to ship vectors for its own payloads, and
stage 5's gate ("shared vectors and real Python↔Go traffic") conflates the two layers.
The demo will pass because the same person writes both halves; the second capability,
written by someone else, has no conformance story at all.
- **Recommendation:** define a per-capability vector layout in stage 1 alongside the
  protocol vectors, require it of capability packages in the capability-author
  documentation, and make the demo capability the reference implementation of that
  requirement.

**C5. The disabled wait loop is not stated to be unchanged, and §3 puts the helper in
every wrapper application.** §3 says the base factory *always* constructs
`ExecutableWrapperGoal(..., execution_support=WrapperServicesSupport(...))`. §5 then
describes one "wrapper-owned wait/pump loop" with `Popen.poll()` and 100 ms selector
waits, with no statement that a no-session launch keeps today's blocking
`process.wait()` (`goal.py:858`). Read literally, every wrapped command in every
wrapper application gains a 10 Hz wakeup loop and a different `KeyboardInterrupt`
delivery site — raised out of `select()` rather than `wait()` — whether or not a
broker is installed. Stage 3's gate only checks that those paths "create no session".
- **Recommendation:** state that with no session the wrapper takes the existing
  blocking wait unchanged, and make "the disabled path's wait, signal, and interrupt
  behavior is unchanged" a stage-3 gate with the harness at `test_goal.py:729-814`.

## Settled sections that are not settled

**C6. §4's "always raises" has no exception-in-flight carve-out, and §5 grants one.**
§4: the `ServicesSession` context-manager exit "always closes the session and raises a
typed latched-framework error after cleanup". §5, for the wrapper path: an escaping
`SystemExit` or `KeyboardInterrupt` "stops services and triggers exceptional child
cleanup, then propagates unchanged". §8 adds a third phrasing: "Preserve the primary
termination exception, or the first ordinary error if there was none." These govern
different objects — §4 is the goal-side session, §5 the wrapper's scoped guard — but
they answer the same question differently, and read literally §4 means a Ctrl-C inside
a portable goal's `with session:` body is replaced by the latched error with the
interrupt demoted to `__context__`. That is R2's failure mode in a new place. The
ordinary case is ambiguous too: body raises, framework failure latched — §4 says the
latch wins, §8 says the first ordinary error does.
- **Recommendation:** give §4 §5's carve-out explicitly: the exit raises the latched
  error only when nothing is propagating out of the body; otherwise it closes,
  reports, and lets the original through. Then the wrapper's step 7 is the only place
  that converts a latch into `FRAMEWORK_FAILED`.

**C7. The aggregate budget and the advertised per-connection limit cannot both hold.**
§7 caps a proxy at 16 downstream connections, gives each "one bounded input and one
bounded output frame", defaults a frame to 1 MiB, and sets aggregate buffering to
32 MiB "including charged decoded-envelope storage". A proxy also holds an upstream
leg, and §6 gives every connection "one reader and one serialized writer", so a full
proxy is 17 connections × 2 MiB = 34 MiB — over budget before a single decoded
envelope is charged to the same 32 MiB. Even at 16, there is exactly zero headroom for
charges the budget must absorb. Worse, `ready` advertises the effective per-connection
limit, so a client
is told it may send 1 MiB and then meets an admission failure caused by unrelated
peers — and none of §7's shared codes (`invalid_request`, `missing_provider`,
`ambiguous_provider`, `not_granted`, `unsupported_method`, `provider_failure`,
`broker_failure`) means "refused under resource pressure". "Admission stops before
allocation would exceed the budget" does not say whether the peer gets an error,
stalls behind backpressure until the 30 s incomplete-frame deadline kills it, or is
closed.
- **Recommendation:** either reserve a per-connection floor so the advertised limit is
  always honourable, or add a `resource_exhausted` code and state that the connection
  stays usable after it. Then fix the arithmetic so the defaults are simultaneously
  satisfiable. `C1` removes this problem entirely.

**C8. A proxy's serialized upstream leg cannot meet the default deadline.** §6: the
proxy "serializes local and descendant upstream calls". §7: one outstanding request
per connection, default call deadline 30 seconds, and expiry after transmission
"closes that client session and reports outcome unknown". With N downstream clients
sharing one serialized upstream leg, the last request in line only succeeds if
everything ahead of it finishes inside its own 30 s budget — about 1.9 s of average
provider time at the 16-connection cap. §7's deadline-aware admission is specified for
"local waiting callers", not for downstream peers, so a loaded proxy will admit doomed
work and then destroy the sessions of well-behaved clients.
- **Recommendation:** state that a proxy refuses a downstream request it cannot start
  within the request's own `remaining_timeout_ms`, and that refusal is a recoverable
  error rather than a session close. `C1` removes this too.

**C9. `remaining_timeout_ms` has no server-side rule.** §7 defines who sets it and
that proxies decrement it and never retry an expired call. It never says what the
terminal server does with it. Since §7 also says a synchronous provider cannot be
interrupted, the only useful server behavior is admission control — refuse before
dispatch if the budget is already spent — which is also what `C8` needs. Either say
that, or say the field is advisory and explain why it is on the wire.

**C10. `error.kind` is undefined.** §7 specifies `kind`, `code`, `message`, `data`,
and attribution, then enumerates values for `code` only. Nothing says what `kind`
ranges over (framework vs. capability-declared? transport vs. protocol vs. domain?) or
how a client decides whether a `code` it does not recognize is retryable-in-principle,
a caller error, or a provider defect. For a section that claims its choices are fixed,
this is the one field a Go client must switch on and cannot.

**C11. Minor, but state them:** launch grants must be documented as defaulting to
empty (§4 lists the field and never gives its default, and it is the security-relevant
one — §4 already says broker configuration "cannot expand goal grants", which is
exactly right). §5 calls `environment_removals` "frozen names" while §6 refers to
"dynamic removal names" the completion CLI "cannot know in advance"; pick one. §3
does not say whether one plugin may implement both participant mixins.

**C18. §4 misdescribes what core dispatch can attribute.** §4 calls "`None`, multiple
replies, and an invalid reply" provider contract failures that "take the same latch
path even though core dispatch cannot attribute them". Only `None` is actually
unattributable. `_append_contribution` runs *inside* the attributed `try`
(`_dispatch.py:229`), so once the call phase sets `contribution_type`, a wrongly typed
reply raises `TypeError` there (`275-291`) and returns as an attributed
`PluginCallbackError` (`230-238`) — indistinguishable from an ordinary provider
exception, which is the correct outcome. "Multiple replies" cannot occur: a targeted
dispatch selects exactly one plugin (`243-265`) and appends at most one value for it.
The defensive check is harmless, but the stated reason for it is wrong, and §4 leans
on that reason to justify a router-side rule the runtime already enforces.
- **Recommendation:** state that the call phase sets `contribution_type` so type
  violations arrive pre-attributed, and that the router's own check covers the
  empty-tuple case and nothing else.

## Omissions in the touch list

**C12. Stage 0 changes documented wrapper behavior and §10 does not update the
document.** `engulf-executable-wrapper/README.md:111-112` states the child "inherits
the wrapper's standard streams, environment, current directory, controlling terminal,
and process group" — false once §6's removals and additions apply, and false for
*every* launch, including help, because removals are unconditional. The outcome table
at `README.md:116-125` maps "Permission, recursion, or other spawn error" to
`FAILED`/126; stage 0 moves post-spawn `OSError` out of that row into
`FRAMEWORK_FAILED`/70, which is right but is a behavior change to a published package
landing before any service code exists. `README.md:127-128` ("`after_call` runs for
preemption, spawn failure, child signal, and normal child exit") also needs the new
infrastructure-failure path. §10's list names the workspace README, `AGENTS.md`, and
"owning READMEs", but enumerates only counts, boundary tables, and the new-package
items.
- **Recommendation:** name `engulf-executable-wrapper/README.md`'s behavior and
  outcome-mapping sections in §10, and make the stage-0 gate include the documentation
  change, so the repaired boundary ships documented rather than silently.

**C13. There is no operator answer to "why did my child get `not_granted`?"** The repo
already has the pattern: `engulf-plugin-list` is a separate distribution publishing a
diagnostic and a `--engulf-plugin-list` before-separator trigger. The service
directory — accepted capabilities, registered providers, resolved defaults, child
grants — is exactly the kind of state that pattern exists for, and the plan never
considers whether it is inspectable without running the goal. §9's tests exercise it;
an operator cannot.

**C14. The Go client has no status.** Stage 5 puts "a Go module/client and wrapped
demo" at `examples/services-go/`. §10's eight distributions do not include it, so it
is demo code — but §1's outcome and §7's cross-language commitment both rest on it.
Decide and say: is it a supported artifact with a module path, an owner, and a
versioning story, or reference code that third parties are expected to reimplement
from the spec? If the latter, the spec and its vectors are the deliverable and should
be reviewed as such, not as a by-product of stage 1.

**C15. §3's prose and table disagree about the child's install closure.** The table
requires `engulf-services` → `engulf-api`; the prose says "the Python child needs
services plus its capability API". The real closure is `engulf-services`,
`engulf-services-api`, `engulf-api`, and the capability API — so a child process
installs the goal/plugin API package to make a socket call that uses none of it. That
is the residual of S7, which §11 marks closed by "three distributions". It may well be
the right trade (`engulf-api` is dependency-free), but say so deliberately rather than
by omission, and note why the client half is not its own distribution.

**C16. There is no performance budget anywhere**, in a design whose every structural
choice — one outstanding request, 64 KiB work budgets, 100 ms selector caps, deferring
the response write to the next turn — is made for responsiveness. A round-trip target
would make the stage-4 and stage-5 gates mean something, and would catch the one
latency trap in §5: the deferred-write turn must register write interest so a reply is
not held for a full poll interval. §5 implies it ("buffered work requests an immediate
iteration") without tying it to the deferred response.

## Document hygiene

**C17. R9 is dispositioned but not solved.** §11 answers R9 with "no previous
plan/review is rewritten", which addresses authorship and not the failure mode R9
named. `plugin-services.md` still opens "Status: planned; implementation has not
started" and still describes the design v2 replaced; `plugin-services-critique.md`
still opens "Status: open. No finding has been addressed in the plan yet" and still
carries B1's setup-dispatch remedy and B4's `BaseException` path, both of which v2
overturns on verified grounds. The repo already has the convention — `privilege-opt-in.md`
carries "Status: implemented." — so this is one line per file, changes no content, and
rewrites nothing.

## What to do

| # | Action | Where |
| --- | --- | --- |
| C1 | Defer descendant proxies; keep `id`/grants/`remaining_timeout_ms` reserved on the wire | §1, §6, §7, §9 stage 5 |
| C2 | Move a Go vector runner into stage 1 and gate stage 1 on it | §9 stages 1, 5 |
| C3 | Write the wrapper-api seam's signatures, return types, and `end` value in full; state the provider-dispatch guard | §5 |
| C4 | Define a per-capability codec vector layout and require it of capability packages | §7, §9 stage 1 |
| C5 | State that a no-session launch keeps the existing blocking wait; gate it in stage 3 | §5, §9 stage 3 |
| C6 | `__exit__` raises the latch only when nothing is propagating | §4, reconciled with §8 |
| C7 | Reserve per-connection floors or add `resource_exhausted`; fix the 32 MiB arithmetic | §7 limits table |
| C8 | Proxies refuse work they cannot start within its remaining budget | §6, §7 |
| C9 | Define server-side `remaining_timeout_ms` behavior, or say it is advisory | §7 |
| C10 | Define the `kind` taxonomy | §7 errors |
| C11 | Default grants empty; settle frozen-vs-dynamic removals; broker+provider in one plugin | §3, §4, §5, §6 |
| C12 | Add `engulf-executable-wrapper/README.md` behavior/outcome sections to the stage-0 gate | §9 stage 0, §10 |
| C13 | Decide whether a service-directory diagnostic exists | §3 or §9 stage 6 |
| C14 | Decide the Go client's status, module path, and owner | §9 stage 5, §10 |
| C15 | State the child's real install closure and why the client is not separate | §3 |
| C16 | State a round-trip budget; tie the deferred write to an immediate iteration | §5, §7, §9 stages 4-5 |
| C17 | Add supersession status lines to v1 and the critique | `plugin-services.md`, `plugin-services-critique.md` |
| C18 | Correct the reply-validation reasoning: only the empty tuple is unattributable | §4 calls and error translation |
