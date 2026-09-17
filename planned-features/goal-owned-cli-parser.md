# Goal-owned CLI parser with tracked argv edits

Status: planned; implementation has not started.

## Objective

Let a goal supply a parser or command-tree object that the goal and its active,
compatible plugins share during argument registration. The goal chooses the CLI
framework and owns its parsing, help, and completion integration. Preserve the
existing attributed argv contribution model when plugins inspect or modify a call.

Supporting multiple frameworks means different goals can choose different parser
contracts. Plugins receiving a native framework object are coupled to that
framework through their goal-specific API. Cross-framework plugin portability
would require a separate common registration interface and is not a prerequisite.

## Existing foundations

- `Goal.setup()` and `GoalSetupAPI.dispatch()` already support typed registration
  phases. No parser-specific lifecycle hook in Engulf core is needed initially.
- `ExecutableWrapperGoal` already shares an `ArgumentRegistry` and a
  `CompletionRegistry` with its plugins during setup.
- `ArgumentRegistry` primarily contains completion metadata. Only options with an
  explicit environment binding are consumed by existing invocation normalization.
- Analyzers receive the same immutable original call and return `CallContribution`
  values. Dispatch associates each contribution with its stable plugin ID.
- The wrapper merges removals and additions after analysis, then supplies original
  and effective arguments to preparation and finalization.
- Completion currently reads the wrapper registries and completion providers; it
  does not automatically inspect arbitrary parser objects.

Relevant sources:

- [Goal and phase contracts](../engulf-api/src/engulf_api/goals.py)
- [Setup dispatch contract](../engulf-api/src/engulf_api/plugin_api.py)
- [Wrapper plugin contract](../engulf-executable-wrapper-api/src/engulf_executable_wrapper_api/plugin.py)
- [Argument and completion registries](../engulf-executable-wrapper-api/src/engulf_executable_wrapper_api/registry.py)
- [Call events and contributions](../engulf-executable-wrapper-api/src/engulf_executable_wrapper_api/models.py)
- [Wrapper setup, normalization, and merge](../engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py)
- [Completion runtime](../engulf-executable-wrapper/src/engulf_executable_wrapper/completion.py)

## Proposed design

### Goal-owned registration

The goal creates one parser definition per application, registers its own options,
and passes the same object through a goal-specific setup event to plugin
registration callbacks in preprocessing order. Define the parser type in the
goal's plugin contract so compatibility is explicit; do not replace the existing
wrapper registry parameter with an untyped arbitrary object.

Use stable phase IDs and module-level forwarding callbacks through managed
dispatch. Attribute registration failures to the plugin being called. Detect
duplicate declarations with a documented policy and retain registration ownership
where needed for diagnostics and option consumption.

Registration ends when setup completes. Treat the definition as read-only after
that point; document how each adapter enforces or limits late mutation. Repeated
invocations receive fresh parse results and edit contributions. Sharing the live
parser is an explicitly in-process setup contract, like the existing registries.

### Parsing and token provenance

The goal's framework adapter exposes immutable parsed values and occurrence records
that identify the original argv token indexes used by each explicitly supplied
argument. A frozen outer container must not expose mutable nested parse values.

For the executable wrapper, the authoritative index space remains `wrapper_args`
after existing logging and environment-option normalization. Those indexes do not
refer to the raw process argv before normalization. If an adapter uses another
token view internally, it must map back to this authoritative tuple.

Occurrence mapping must distinguish:

- `--option=value` from `--option value`;
- aliases and repeated occurrences, even when their values are identical;
- positionals, subcommands, variable-length values, and the `--` separator;
- explicit CLI values from defaults and environment-derived values, which have no
  removable CLI occurrence in this normalized input;
- multiple logical options sharing a token, such as bundled short options.

Do not infer source indexes by matching parsed values against argv or by diffing a
reserialized namespace. Untouched tokens retain their original spelling and order.
For edits affecting part of a shared token, the adapter must define a lossless
rewrite within the contribution model or reject that convenience operation. Raw
index-based contributions remain available.

The wrapper must continue accepting arguments belonging to the wrapped executable.
Parser integration needs a defined partial-parse policy and must not newly reject
unknown child arguments, execute commands during parsing, or silently consume
ordinary registered options.

### Attributed argv modification

For each invocation:

1. Preserve the immutable authoritative argv tuple and derive the parsed snapshot
   and token provenance from it.
2. Dispatch analysis with the same original arguments and parsed view for every
   plugin. No analyzer sees another plugin's pending modifications.
3. Let parser-aware helpers translate selected occurrences into immutable
   `CallContribution` removals and additions. Helpers may use a private builder,
   but returned contributions remain the integration boundary.
4. Let dispatch attach the plugin identity, then validate and merge all edits after
   analysis completes.
5. Continue existing preemption, preparation, execution, and finalization behavior
   using the merged arguments. If effective parsed values are needed, derive a
   separate snapshot after merging without rerunning plugin analysis.

Example:

```text
Original argv:  ["deploy", "--profile", "dev", "--verbose"]
Indexes:             0          1        2          3

Parsed occurrence: profile="dev", source_indexes=(1, 2)
Contribution from com.example.profile:
  removals = {1, 2}
  additions = ("--config", "dev.yaml") before the separator

Effective argv: ["deploy", "--verbose", "--config", "dev.yaml"]
```

Preserve existing merge semantics: removals reference original indexes and are
unioned; identical added groups are coalesced with the first placement retained;
distinct groups retain contribution order; additions are not coalesced against
original tokens. Preserve plugin-attributed validation errors and the original
and effective arguments already exposed by call events.

Attributed contributions currently identify edit authors during dispatch and merge;
the merge returns only the effective tuple. A durable or public per-token audit
trail would be a further contract decision. Do not imply it already exists. If
introduced, retain all contributing identities when equivalent edits coalesce.

### Completion and help

The goal's adapter uses the completed parser definition to provide help and
completion. Completion must accept incomplete input, preserve the empty current
word and cursor context, and avoid execution or preparation side effects.

For the executable wrapper, bridge parser-derived candidates into the existing
completion registry/provider path. Preserve wrapper-only argument filtering,
candidate deduplication, native executable completion preference, and explicit
opt-in for sourcing native completion. The constructor's binary completion provider
is a fallback when native completion is absent; parser-derived wrapper candidates
must remain available when native executable completion is present.

Completion does not commit argv edits. Its filtered child-completion context is
separate from the invocation's authoritative argv and contribution merge.

## Implementation sequence

1. Define the typed goal-specific registration event and adapter contract, including
   immutable parse results, occurrence provenance, and unsupported syntax behavior.
   Choose a reference framework; exact public names remain to be designed.
2. Implement registration through existing setup dispatch. Preserve the default
   wrapper registry path and existing plugins through an explicit additive design.
3. Implement provenance and parser-aware contribution helpers. Keep index-based
   edits working and keep framework selection out of the generic runtime.
4. Integrate parsing into the wrapper's analysis events with a documented timing
   relative to normalization and outer lifecycle hooks. Preserve normalization and
   existing help-mode, preemption, and preparation-unwind contracts.
5. Connect parser help and completion, including composition with existing plugin
   registrations and native executable completion.
6. Demonstrate a second framework through a small goal/adapter example to verify
   that the integration contract does not depend on the reference framework.
7. Document authoring, limitations, compatibility, and migration in the owning
   package READMEs, then run the workspace-required checks.

Goal-specific contracts belong in their API package and implementations in their
runtime package. Generic packages must not import wrapper or CLI framework
implementations. Keep `engulf-api` dependency-free, public packages typed, and API
packages OS-independent. Do not bump existing versions during first-release work.

## Acceptance and validation

- The goal and selected compatible plugins register against the same definition;
  unselected plugin modules stay unimported. Setup ordering and attributed failures
  remain deterministic.
- Two frameworks can supply goal-owned registration and completion integrations
  without adding framework-specific behavior to Engulf core.
- Existing wrapper plugins and default argv behavior continue to work unchanged.
- Tests cover source indexes for assignments, separate values, aliases, repeats,
  defaults, environment bindings, positionals, subcommands, separators, shared
  tokens, and unknown child arguments, including unsupported edit failures.
- Tests cover normalization followed by index-based and parser-aware edits in the
  same invocation, analyzer isolation, invalid indexes, duplicate removals and
  additions, placement, preemption, help mode, and preparation failure.
- Repeated invocations cannot retain parsed values or pending edits from earlier
  calls; untouched argv tokens remain exact.
- Completion tests cover partial input, trailing empty words, wrapper filtering,
  native completion composition, and absence of execution/preparation side effects.
- Add contract/runtime tests in the owning packages. Run the commands required by
  [AGENTS.md](../AGENTS.md); if package metadata changes, also run `make build` to
  build and validate all five distributions.

## Decisions to resolve during implementation

- The first supported framework and the public adapter and event names.
- Whether framework-specific plugin contracts use a new goal API package or an
  explicit compatible extension of an existing contract.
- How each framework supplies reliable provenance and handles shared tokens.
- Whether parsed data is needed in outer lifecycle hooks; do not introduce a
  generic parser capability solely to expose it there.
- Whether modification tracking needs a public audit record beyond the existing
  attributed contributions and original/effective argv snapshots.
