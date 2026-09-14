# Critique: goal-owned CLI parser with tracked argv edits

Reviews [goal-owned-cli-parser.md](goal-owned-cli-parser.md) against the Engulf
workspace at `4bac606` (current `master`). Line references point at that commit.
`goal.py` means `engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py`;
`completion.py` means the sibling module in the same package.

Status: open. Findings are `G1`–`G11`. `G1`–`G3` block step 1.

Scope: this repository only. Every anchor and behavioural claim below was executed or
read, not inferred. The merge traces in `G2` are real output from `_merge_edits`.

## Verdict

The plan is unusually well grounded in the parts it chose to verify. All seven source
links resolve, and every claim in "Existing foundations" is true: the registries are
shared at setup (`goal.py:323-325`), `ArgumentRegistry` really is completion metadata
except for `environment`-bound options (`registry.py:75-80`, `goal.py:477-521`), merge
semantics are restated correctly down to first-placement coalescing — which the wrapper
README already documents in the same words (`engulf-executable-wrapper-api/README.md:207,222`)
— and the completion section correctly describes the constructor provider as a fallback
gated on `native_available` (`completion.py:64-92`). The worked example on lines 112-122
produces exactly the output it claims. That is a higher hit rate than most plans in this
directory.

The problem is what the plan did not check. Its spine is the occurrence record:
"immutable parsed values and occurrence records that identify the original argv token
indexes." Two things have to be true for that spine to hold — a framework has to be able
to supply index provenance, and the contribution model has to be able to act on it.
Neither is true today, and the plan defers both: the first to "Decisions to resolve
during implementation," the second not at all. Steps 1-3 would freeze a public contract
around a capability that does not exist on either side of it.

The rest (`G4`-`G8`) are gaps where the plan names an existing contract to preserve but
the preservation mechanism it proposes cannot reach that contract.

## G1 — no candidate framework supplies token provenance; the adapter is a second parser

**Blocking.** The design requires occurrence records that "identify the original argv
token indexes used by each explicitly supplied argument," and correctly forbids the two
cheap ways to fake it: "Do not infer source indexes by matching parsed values against
argv or by diffing a reserialized namespace." Both prohibitions are right. Neither is
costed, because the plan never asks whether anything can satisfy the requirement.

Nothing in the mainstream Python CLI ecosystem exposes token indexes. `argparse` has no
public provenance API at all — reaching it means subclassing `_parse_known_args`,
`_get_values` and `take_action`, all private and all reshaped between minor versions.
`click` exposes `ParameterSource` (COMMANDLINE / ENVIRONMENT / DEFAULT / DEFAULT_MAP /
PROMPT), which does satisfy exactly one bullet of the plan's occurrence-mapping list —
"explicit CLI values from defaults and environment-derived values" — and none of the
other five. `typer` wraps `click` and inherits the same ceiling.

So the adapter, not the framework, must compute provenance. The plan says as much
("If an adapter uses another token view internally, it must map back to this
authoritative tuple") without drawing the consequence: an adapter that derives index
provenance is a **second parser**. It must independently know every option's arity,
alias set, bundling rules, `nargs`, subcommand boundaries and `--` handling, and it must
stay in agreement with the framework's own parse forever. The plan budgets this as half
of step 3, alongside the contribution helpers.

The failure mode is silent divergence: the shadow parser and the real parser disagree
about which tokens produced a value, so a plugin removes the wrong index and the wrapper
runs a subtly different command. No acceptance criterion targets this. The listed tests
are all example-based ("assignments, separate values, aliases, repeats, ..."), which
test the shadow parser against the plan author's expectations rather than against the
framework. What is needed is differential: generate argv, parse with the framework,
derive provenance with the adapter, assert the reconstruction agrees — as a property
test, not a table. Add it to step 3, not step 7.

Resolve before step 1, because the answer decides the shape of the public contract: if
provenance must be hand-built anyway, the framework object may not belong in the plugin
contract at all.

## G2 — the contribution model cannot express an in-place edit

**Blocking.** `AdditionPlacement` has exactly three values (`models.py:16-19`) and
`_merge_edits` resolves all three globally (`goal.py:799-805`): PREPEND before every
surviving token, BEFORE_SEPARATOR immediately before the first surviving `--`, APPEND at
the very end. There is no placement at or near an original index.

"Let parser-aware helpers translate selected occurrences into immutable
`CallContribution` removals and additions" therefore describes an operation that reads
as in-place at the call site and is not in-place in the result. Traced against the real
`_merge_edits`:

```text
1. the plan's own example (lines 112-122)
   in : ['deploy', '--profile', 'dev', '--verbose']
   out: ['deploy', '--verbose', '--config', 'dev.yaml']      # correct, but relocated

2. rewrite the first of two positionals
   in : ['copy', 'src.txt', 'dst.txt']
   out: ['copy', 'dst.txt', 'src2.txt']                      # positionals swapped

3. option that must precede positionals (docker-run shape)
   in : ['run', '--rm', 'img', 'cmd']
   out: ['run', 'img', 'cmd', '--rm=false']                  # flag now after the command

4. edit a token after the -- separator
   in : ['a', '--', 'child', '--flag']
   out: ['a', '--flag=off', '--', 'child']                   # child arg became a wrapper arg
```

Case 1 is the plan's own example and it is already relocating — harmlessly, because
both survivors are order-free options, which is what hides the defect. Case 2 is
silently wrong output. Case 4 is a semantic inversion, and the plan explicitly lists the
`--` separator among the distinctions occurrence mapping must make.

The plan's only acknowledgement is scoped to shared tokens: "For edits affecting part of
a shared token, the adapter must define a lossless rewrite within the contribution model
or reject that convenience operation." The problem is not confined to shared tokens.
It applies to every edit whose token has position-dependent meaning, which is every
positional and every subcommand-scoped option — and the acceptance criteria demand tests
covering "positionals, subcommands" that this design cannot pass.

Two things to fix, both cheap relative to the rest of the plan:

- **State the relocation rule.** Parser-aware edits are remove-here / insert-at-a-boundary,
  never in-place. Name the operations the helpers will refuse: positional replacement,
  and any option the wrapped executable requires before a subcommand.
- **Fix the default placement.** Case 4 is recoverable: `AdditionPlacement.APPEND` does
  land after the separator. The helper must pick placement from the occurrence's position
  relative to `--`, and `BEFORE_SEPARATOR` — the `ArgumentAddition` default
  (`models.py:122`) — is the wrong default for a post-separator occurrence. That default
  is the trap; a helper that just forwards it will produce case 4 for every plugin.

If in-place edits are actually required, that is a fourth placement (an `AT_INDEX`
anchored to an original index) and a change to `_merge_edits` — a wrapper API change the
plan does not currently contain, and a much better thing to discover now than in step 3.

## G3 — "multiple frameworks" is trivially true where the plan proves it, and excluded where it would matter

**Blocking, cheap to fix — it is mostly a scoping error.** The Objective says
"different goals can choose different parser contracts," and acceptance criterion 2 asks
that "two frameworks can supply goal-owned registration and completion integrations
without adding framework-specific behavior to Engulf core."

That criterion is satisfiable without testing anything. Goals already own their plugin
contracts and Engulf core already knows nothing about parsers; `examples/encryption-core`
is *already* a goal that owns an `argparse` parser (`goal.py:83-95` in that package) and
core is untouched by it. Writing a second demo goal around a different framework proves
only that step 6 was performed.

The case that would matter — two applications on the **executable-wrapper** goal choosing
different frameworks — is structurally excluded by the mechanism the plan proposes.
`ExecutableWrapperPlugin` is one concrete ABC with fixed signatures (`plugin.py:31-84`)
under one goal id and one API major (`plugin.py:22-24`), and `GoalContract` binds a single
`plugin_type` (`goals.py:165-176`). Adding `register_parser(parser, api)` to that ABC bakes
exactly one parser type into `engulf-executable-wrapper-api` for every wrapper application
that will ever exist. "Define the parser type in the goal's plugin contract so
compatibility is explicit" and "the goal chooses the CLI framework" are consistent only if
"the goal" means the goal *id*, not the application.

This also makes "its active, **compatible** plugins" (Objective) undefined. There is no
per-plugin framework declaration anywhere in the model, and activation validates only
runtime type against `GoalContract.plugin_type`. A click-oriented plugin installed into an
argparse wrapper is activated normally and fails inside its registration callback —
attributed correctly, and fatal, since the setup phases do not set `isolate_failures`
(`goal.py:134-147`), so it aborts application construction.

Pick one and write it down:

- **(a)** Framework is fixed per goal API major. Say so in the Objective, drop "compatible"
  as if it were a filter, and delete acceptance criterion 2 — it tests nothing.
- **(b)** Per-application framework choice is a goal. Then it needs either a type parameter
  on the wrapper plugin contract or a new goal id, and step 6 becomes the load-bearing
  step, not the demo. Cost it.

Today the plan reads as (b) and specifies (a).

## G4 — a candidate-level completion bridge cannot preserve wrapper-only filtering

The plan says to "bridge parser-derived candidates into the existing completion
registry/provider path" while preserving "wrapper-only argument filtering." Those two
are not compatible, because the filtering is not candidate-level.

`_hidden_binary_indexes` (`completion.py:235-263`) walks the words against
`ArgumentRegistry`, and uses each `OptionSpec`'s `takes_value` and
`visible_to_binary_completion` to decide which **argv positions** to delete before the
word list is handed to the wrapped executable's native completer. `_normalize_for_binary`
(`completion.py:207-232`) then rebuilds the cursor index over the surviving words, and
the whole thing is exposed as its own protocol round-trip — the shell script calls the
wrapper once for `normalize` and again for `complete` (`completion.py:48-54, 56-71`).

So an option registered only with the parser is invisible to this transform. It stays in
the word list, the native completer sees a wrapper-private flag it does not recognise,
and child completion degrades or misfires — with no error anywhere. Registering
candidates does not help; the transform never looks at candidates.

Parser registration must therefore also yield `OptionSpec`-equivalent structure — names,
`takes_value`, `visible_to_binary_completion` — not just completion candidates. Either
the adapter mirrors parser options into `ArgumentRegistry` (which makes the registry the
single source of truth and the parser a front end, a defensible and much smaller design),
or `_hidden_binary_indexes` grows a second source. Decide in step 1; it changes what the
registration event has to return.

Note also that `visible_to_binary_completion` has no natural counterpart in any parser
framework. Every parser-registered option needs an explicit answer, and the safe default
is the current one — hidden.

## G5 — three interceptors run before the parser would; the plan names one and a half

"The goal ... owns its parsing" is not true of the tokens the goal actually receives.
Between `sys.argv` and `wrapper_args`, argv passes:

1. `matching_diagnostics` (`application.py:565-568` → `diagnostic_extensions.py:192-203`)
   — any raw token before `--` matching a diagnostic trigger diverts the whole invocation
   before the goal is reached.
2. `parse_logging_arguments` (`application.py:569-573` → `diagnostics.py:134-192`) —
   strips the two logging options in **core**, not in the wrapper.
3. `normalize_invocation` → `_normalize_environment_options` (`application.py:580`,
   `goal.py:477-521`) — strips `environment`-bound options.

and then inside `achieve`, `install-completion` is intercepted positionally at
`goal.py:366` before analysis, merge or anything else, with its completion hardcoded at
`goal.py:536-563`.

The plan names (2) and (3) — "after existing logging and environment-option
normalization" — and that phrasing is accurate. It misses (1) and `install-completion`
entirely. Both bite a goal that owns a *command tree*: a parser-registered subcommand
whose name collides with a diagnostic trigger never reaches the goal, and one named
`install-completion` is permanently shadowed. Neither collision is currently detectable
at registration time.

Worth stating explicitly that (2) happens in core: the wrapper registers the logging
options into `ArgumentRegistry` purely for completion (`goal.py:737-761`) while the
actual consumption happens upstream. A parser adapter has to reproduce that same
split — declare for help and completion, do not consume.

## G6 — parser-aware edits are inert in help mode, and parser-owned help contradicts the pass-through contract

`mode` is decided by a flat membership scan — `"--help" in wrapper_args`
(`goal.py:368`) — over every token including those after `--`. In HELP mode both the
merge **and** preemption are skipped (`goal.py:376-383`): `effective_args` is
`wrapper_args` unchanged.

Consequence the plan never states: any parser-aware contribution is silently discarded
whenever any token anywhere equals `--help`, including a `--help` after `--` intended
for the child. The acceptance list mentions help-mode tests, but the design section
never says edits are inert there, so a helper author has no reason to expect it.

Second, "the goal's adapter uses the completed parser definition to provide help and
completion" is in tension with the contract step 4 says to preserve. Today `--help` is
**passed through** to the wrapped executable, which runs, and the wrapper appends its own
block afterwards (`goal.py:417-418`, `_write_help` at `goal.py:942-960`). A parser that
owns help does the opposite — intercepts, prints usage, exits. Both cannot hold. Say
which one wins, and if it is pass-through, say that parser-derived help is an *additional
block* rather than a replacement.

## G7 — one parser built at setup versus "repeated invocations receive fresh parse results"

The design says registration "ends when setup completes" and the definition is read-only
after that, which means one parser object built once and reused for the life of the
application — and applications are long-lived across repeated `Application.invoke()`
calls. The acceptance criteria then require that "repeated invocations cannot retain
parsed values or pending edits from earlier calls."

The plan asserts the outcome without supplying the mechanism, and the two constraints
pull against each other. The concrete counterexample is `argparse`'s oldest sharp edge:
an `action="append"` argument with a non-`None` default appends into the **same list
object** on every `parse_args`, so invocation two sees invocation one's values. Reusing
one parser inherits whatever cross-parse state the framework carries; rebuilding per
invocation would mean re-dispatching plugin registration per invocation, which
contradicts "registration ends when setup completes" and would be a per-call dispatch
cost on the hot path.

The likely answer is: build once, and have the adapter deep-copy or rebuild the *result*
container per parse, never the definition. Whatever it is, it belongs in the design
section next to the read-only claim, with the `append` case named as the thing the test
must catch. "A frozen outer container must not expose mutable nested parse values" is
the right instinct and is aimed at the wrong target — it guards against a caller mutating
the snapshot, not against the framework carrying state between parses.

## G8 — "read-only after setup" has no enforcement seam

The plan asks each adapter to "document how each adapter enforces or limits late
mutation." Worth noting that the existing precedent offers nothing to copy: `_SetupEvent`
is frozen (`goal.py:71-75`) but holds two mutable registries, and a plugin can stash the
`ArgumentRegistry` reference from `register_arguments` and mutate it during
`analyze_call`. AGENTS.md's "retained loggers and APIs must fail outside their callback"
does not cover it, because the registry is not an API object and has no deactivation.

Inheriting that hole is defensible — it is in-process setup state, as the plan says —
but the plan should say it is inherited rather than imply adapters will solve it. A
parser object is a larger and more tempting thing to retain than a registry, and for
`argparse` specifically there is no freeze at all: `add_argument` keeps working forever.

## G9 — sequencing puts the validating step sixth

Step 6 ("demonstrate a second framework ... to verify that the integration contract does
not depend on the reference framework") is the only step that tests the plan's premise,
and it runs after the contract is defined (1), registration is implemented (2),
provenance and helpers are built (3), the wrapper is integrated (4), and help and
completion are connected (5). If the second framework cannot supply provenance — see
`G1` — that is discovered after five steps of contract work.

Move a provenance spike for **two** frameworks ahead of step 1. It is a day of work and
it is the cheapest possible test of `G1`, `G2` and `G3` at once.

## G10 — unmentioned prior art in this repo

Two existing pieces are directly relevant and go uncited:

- `examples/encryption-core/src/engulf_encryption_example_core/goal.py` is already a goal
  that owns an `argparse` parser, including a subcommand tree (`:83-95`) and an
  `ArgumentParser` subclass that converts `error()` into an exception instead of
  `SystemExit` (`:28-30`). That last detail is exactly the "must not execute commands
  during parsing" requirement from the plan's partial-parse paragraph, already solved.
  It is also the natural host for step 6's second framework.
- `engulf-executable-wrapper/src/engulf_executable_wrapper/completion_cli.py:15-28` builds
  an `argparse` parser inside the wrapper package already.

Neither changes the design, but step 1's "choose a reference framework" has a default
sitting in the tree, and the `error()`-override pattern should be a stated requirement of
the adapter contract rather than something each adapter rediscovers.

## G11 — smaller notes

- The plan's paragraph on attribution is careful and correct: contributions identify
  authors during dispatch and merge, `_merge_edits` returns only the effective tuple
  (`goal.py:764-805`), and no per-token audit trail exists. Keeping "Do not imply it
  already exists" in the text is the right call.
- Cross-placement coalescing is worth one explicit sentence in the helper contract, not
  just in the restated merge semantics. Two plugins contributing the identical group at
  different placements yield one token at the **first contributor's** placement — traced:
  `('x',)` with APPEND from plugin A and PREPEND from plugin B gives `['x', '--f']`. A
  parser-aware helper that generates canonical spellings will collide far more often than
  hand-written contributions do, so this goes from a curiosity to a regular occurrence.
- "The wrapper must continue accepting arguments belonging to the wrapped executable" is
  the single most important sentence in the design and it has no acceptance criterion of
  its own. "must not newly reject unknown child arguments" deserves a named test, because
  the default behaviour of every framework listed is the opposite.
- Invalid-index handling already exists and is attributed (`goal.py:776-784`, raising
  `IndexError` naming the plugin). Negative indexes are rejected earlier, in
  `CallContribution.__post_init__` (`models.py:143-147`). The acceptance line "invalid
  indexes" should say it is asserting existing behaviour survives, not new behaviour.

## Unrelated, but blocking everything

`engulf/src/engulf/plugin_loader.py:213` is committed on `master` with a Python 2-style
`except OSError, RuntimeError, TypeError, ValueError:`. `import engulf` raises
`SyntaxError`, so `engulf`, `engulf-executable-wrapper`, and the workspace test suites
cannot run at all — including the validation commands this plan's step 7 depends on.
The fix is parentheses. Flagging it here because it was found while tracing `G2`; it has
nothing to do with this plan.
