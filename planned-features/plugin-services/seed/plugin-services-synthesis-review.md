# Review: critique synthesis for the optional plugin service broker

Reviews [plugin-services-critique-synthesis.md](plugin-services-critique-synthesis.md)
against the [plan](plugin-services.md), the
[original critique](plugin-services-critique.md), and the runtime at commit
`4bac606` (current `master`). Line references point at that commit. `goal.py` means
`engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py`.

Status: open. Findings below are `R*`; `B*`/`S*` refer to the original critique.

## Verdict

The synthesis is a net improvement on the critique as a *judgement*. Its three
substantive corrections are all verified correct against the runtime, and it adds two
findings the critique missed — one of which is a pre-existing wrapper defect that has
nothing to do with services.

It regresses as an *instrument*. It strips the evidence anchors and the plan-section
mapping that made the critique actionable, drops four findings without saying they
were considered, and settles S10 against verified repository practice. After reading
both documents, no single document states what changes in `plugin-services.md`, and
the number of open decisions is higher than before. The plan remains not
implementable, which both documents agree on.

## Verified — the synthesis corrects the critique correctly

**R1. Setup dispatch (synthesis B1).** Confirmed. `GoalSetupAPI.dispatch()` takes only
`phase` and `event` (`engulf-api/src/engulf_api/plugin_api.py:131-136`); `plugin_ids`
exists only on `GoalAPI.dispatch()` (`142-156`). Critique B1's "make every step from
goal to broker a wrapper `GoalPhase`, dispatched with `plugin_ids=(broker_id,)`"
cannot hold in setup.

The synthesis stops one step short. It leaves the remedy as "the existing broadcast
interface **or** explicitly propose an API extension", but no extension is needed:
`GoalSetupAPI.plugin_ids` (`plugin_api.py:127`) exposes the active set, and every
returned `AttributedContribution` already carries `plugin_id`
(`engulf-api/src/engulf_api/goals.py:218-226`). Broadcast-then-filter is sufficient
for collecting immutable declarations. Say so and close the option.

**R2. Termination exceptions (synthesis B4/B6).** Confirmed, and the danger is real.
`goal.py:856-866` catches `KeyboardInterrupt`, forwards `SIGINT`, waits, and returns
the child's return code — it *swallows* the exception rather than re-raising. Critique
B4's "a `BaseException` follows the existing `KeyboardInterrupt` path" would therefore
discard a `SystemExit` raised anywhere in the wait. The synthesis's split — release
resources and reap, then preserve the termination exception, and specify interrupts
separately — is right.

**R3. Constructor injection and editions (synthesis B1/B2).** Confirmed on both sides.
`edition()` (`engulf/src/engulf/application_definition.py:106-133`) `replace()`s only
metadata, `plugin_policy`, and `required_plugin_ids`; `goal_factory` is untouched, so
the critique's objection is factually correct. The synthesis's reconciliation — the
base factory always installs the optional integration, and plugin selection activates
it — is viable, but only if the plan states that the base factory installs it
unconditionally. Left implicit, the two readings from B1 return.

Also verified as stated: `after_call` can be skipped
(`engulf-executable-wrapper/README.md:127-128`), and so can `after_goal` —
`run_after` skips plugins not in `entered` (`engulf/src/engulf/_dispatch.py:150-161`)
and is itself skipped when a `BaseException` leaves `achieve`, since
`application.py:812` catches only `Exception`. Per-callback leases release on
deactivation (`engulf/src/engulf/plugin_api.py:79-85`). Reentrancy blames the caller,
because `api.activate()` precedes the attributed `try`
(`_dispatch.py:226-227`, `_capabilities.py:93-96`).

## New findings the synthesis contributes — give them IDs

**R4. The `OSError` narrowing is the sharpest item in the document and it is buried.**
Verified: in `goal.py:843-904` the `except OSError` at `893` wraps the *entire* block,
including `_SignalForwarder`, `Popen`, and `process.wait()`. It returns
`SPAWN_FAILED`, exit 126, `process_started=False`. So a post-spawn transport `OSError`
is already misreported today as a spawn failure, and `after_call` receives
`process_started=False` for a child that actually ran. This is a pre-existing wrapper
defect, independent of services, and it is a prerequisite rather than a consequence of
the plan. It deserves its own finding ID and its own fix, not a sub-bullet of B4.

**R5. Aggregate bounds and backpressure** are correctly identified and correctly
scoped (the 1 MiB limit bounds one message, not outstanding work). It is filed as an
unnumbered "Additional finding"; number it so the implementation plan can cite it.

**R6. The Go/JSON correction is right but incomplete.** `json.Number` can indeed
preserve numeric text, so ±2^53 is a policy and not a Python–Go requirement. The
practical consequence still needs stating: Go's default decode into `interface{}`
yields `float64`, so preserving `int64` requires the client to opt into
`json.Number`. Whatever the policy, it constrains the client, not only the wire.

## Regressions in usefulness

**R7. Evidence was stripped.** The critique anchored roughly forty claims at
`file:line` against a pinned commit. The synthesis replaces them with four
section-level "Evidence:" links to whole files. Every claim I checked was true, but a
reader cannot confirm any of them without redoing this work — "`after_call` and
`after_goal` can be skipped" is one sentence that required three separate sources to
verify. Restore per-finding anchors; the synthesis already pins the commit in its
header, so the cost is small.

**R8. There is no longer a mapping into the plan.** The critique ended with a table
from findings to `plugin-services.md` sections. The synthesis drops it and states it
does not amend the plan, so no document now says which plan sections change. The repo
already has the pattern worth copying: `goal-owned-cli-parser.md` carries a
"Decisions to resolve during implementation" section in the plan itself.

**R9. The critique's status is now misleading.** `plugin-services-critique.md` still
reads "Status: open. No finding has been addressed in the plan yet" and still carries
the two remedies the synthesis overturned (B1's setup dispatch, B4's `BaseException`
path). Anyone reading it alone implements the wrong thing. It needs a header pointer
to the synthesis, or the superseded remedies marked in place.

## Findings dropped without disposition

**R10. `validate_global_identifier` reuse.** Verified present at
`engulf-api/src/engulf_api/identifiers.py:9` and already the convention for
`plugin_id` (`goals.py:226`). Capability IDs and method names should use it. Dropped
entirely from the synthesis.

**R11. Nested Engulf applications never merge upstream providers; proxying must be
explicit.** The synthesis keeps only the environment-variable half of this in S1. The
semantic rule is the part that prevents a nested application from silently inheriting
a parent's provider set.

**R12. Conflicting method sets across providers of one capability.** B5's
"unsupported methods" survives; the conflict check when two providers disagree about a
capability's methods does not.

**R13. Concrete test assets.** The readiness-file signal harness
(`engulf-executable-wrapper/tests/test_goal.py:729-814`) and `examples/encryption-core`
became "suitable example assets". The specific references were the useful part.

## S10 is settled against the evidence

This is the one place the synthesis rules the wrong way.

Verified current versions: `engulf-api` 1.3.0, `engulf` 0.3.0,
`engulf-executable-wrapper-api` 1.2.1, `engulf-executable-wrapper` 0.3.0,
`engulf-plugin-list` 0.1.1. The critique's hypothetical ("if wrapper-api 1.2.1 and
wrapper 0.3.0 are already published") is exactly the current state.

Commit `3eef1dc`, three commits before `HEAD`, bumped all five *during first-release
development* and gives the reason in its own message: "Every distribution here has
changed since its version was last set, so each of them is unpublishable at its
declared version: the repository refuses a filename it already hosts." It also moved
floors with contracts — `engulf-api>=1.2,<2` → `>=1.3,<2` and `engulf>=0.2,<1` →
`>=0.3,<1`.

The synthesis's reply — historical bumps "identify a release concern; they do not
override the current instruction" — treats demonstrated practice as history. The
situation recurs immediately under this plan: `execution_support` adds public surface
to a `engulf-executable-wrapper-api` 1.2.1 that is already hosted, and the wrapper's
floor is still `engulf-executable-wrapper-api>=1.2,<2`
(`engulf-executable-wrapper/pyproject.toml:24`), which would happily pair the new
runtime with a contract that lacks `execution_support`.

The critique asked for an explicit decision and it is still owed. `AGENTS.md:35`
should be scoped to what `3eef1dc` actually practices — do not bump for unpublished
changes — rather than cited as settling the question.

## CI: one synthesis item is a present failure, not future work

"Ensure both example packages are installed for the Python demo" understates what is
there. `.github/workflows/ci.yml:27` installs `--no-deps -e examples/encryption-app`
and never installs `examples/encryption-core`, while
`examples/encryption-app/src/engulf_encryption_example/__init__.py:5` imports
`engulf_encryption_example_core` at module import and `ci.yml:34` runs
`python -m engulf_encryption_example`. Nothing else in the workflow supplies the
package. Confirm whether that step passes today before treating it as new work.

The rest of S9 verified, with one correction to each document:

- Ruff omits `plugins/` in CI (`ci.yml:66-67`) but not locally (`AGENTS.md:348-349`);
  the build step (`ci.yml:71-78`) omits `engulf-plugin-list`. Both true.
- `Makefile` (`DIR_engulf-plugin-list`, line 10), root `pyproject.toml`
  (`mypy_path`/`files`, lines 24 and 33), and `tests/test_documentation.py`
  (`DOCUMENTED_PACKAGES`) already carry `plugins/` and both examples. For these three,
  new packages are additions, not repairs — the synthesis implies otherwise.
- Counts to update are `README.md:7,50,115` and `AGENTS.md:353` ("five"). The
  critique's "editable-install line" is imprecise: the only such text is prose at
  `README.md:58`. The synthesis inherited the imprecision as "development installation
  instructions".

## Terminology

Use the repo's existing term. `engulf-executable-wrapper-api/README.md:510-513` calls
mutable-registry and callable-bearing registration "local-execution contracts"; the
synthesis says "local-only contracts" for the same concept in B2/S7.

## What to do

| # | Action | Where |
| --- | --- | --- |
| R1 | Close the setup option: broadcast plus `plugin_ids` filtering, no API extension | synthesis B1; plan "Registration and goal integration" |
| R3 | State that the base goal factory always installs the optional integration | plan "Registration and goal integration" |
| R4 | Split the post-spawn `OSError` misreport into its own finding and fix it first | `goal.py:893`; plan or a separate defect |
| R5, R6 | Number the aggregate-bounds finding; state the client-side `json.Number` policy | synthesis "Protocol and validation" |
| R7 | Restore per-finding `file:line` anchors | synthesis throughout |
| R8 | Add a findings-to-plan-section table, or fold decisions into the plan | synthesis end; plan |
| R9 | Point the critique at the synthesis and mark superseded remedies | `plugin-services-critique.md` header, B1, B4 |
| R10–R13 | Reinstate or explicitly dismiss the four dropped findings | synthesis |
| S10 | Decide the version policy and scope `AGENTS.md:35` to unpublished changes | `AGENTS.md:35`; synthesis S10 |
| CI | Check whether `ci.yml:34` passes today before scheduling it as new work | `.github/workflows/ci.yml:27,34` |
