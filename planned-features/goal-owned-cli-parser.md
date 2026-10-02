# Native partial CLI framework for the executable wrapper

Status: planned; implementation has not started. This replaces the goal-owned
parser proposal that previously occupied this file.

## Objective

Give the executable-wrapper goal an Engulf-maintained CLI model for the parts of a
wrapped executable's command line that the goal and its plugins declare. The
wrapper must work with a partial view: it observes known syntax, expands calls
through attributed contributions, and forwards unknown child arguments unchanged.
The model applies automatically without an application opt-in. A plugin's CLI
declarations do not narrow its invocation participation unless it explicitly
requests narrower participation.

This is a framework plan. Consumer migration is separate. Work and inspection
for this plan are limited to this repository and `../engulf-clab`.

## Declarations and package ownership

Put immutable CLI declarations, parsed views, and a callback-local `CLIBuilder` in
`engulf-executable-wrapper-api`. Put the single-pass scanner, help rendering, and
completion integration in `engulf-executable-wrapper`. The generic `engulf-api` and
`engulf` packages receive only the goal routing seam; they must not import
executable-wrapper CLI types or runtime code.

Add `register_cli(builder, api)` to the wrapper plugin contract. Give each setup
participant its own builder, freeze it after its callback, then merge declarations
with attributed conflicts. The goal registers its own commands and options through
the same path, including `install-completion`, `--help`, and
`--engulf-plugin-help`. Goal-owned commands follow ordinary participation rules;
an always-participating plugin still receives its outer hooks for them.

The builder declares:

- nested command paths and whether a command belongs to the child or is handled
  by a plugin;
- option aliases, command scope, arity, repeatability, description, environment
  binding, default, choices, visibility to native completion, and placement before
  a command, after it, or both;
- permitted value forms per option: separate word, `--name=value`, or both;
- fixed-arity positional slots before a command and scoped positionals after it;
- foreign arity hints for child options that can precede commands, without
  claiming, validating, consuming, or hiding them;
- optional command-level rejection of unknown neighboring options and an opt-in
  to scan after `--` once that command has been resolved;
- participation rules: every invocation, selected command paths, or use of an
  owned element.

The default participation rule is every invocation, whether or not a plugin
declares commands or options. An explicit narrower rule is the only way to
filter its outer hooks and wrapper callbacks. A declared option supplied from its
bound environment variable counts as used; a default value alone does not.

The same option spelling may have different declarations on disjoint command
scopes. Overlapping declarations conflict unless they can be merged without
changing syntax. Existing `register_arguments()` entries reserve their spellings
across all commands during this merge, so a legacy and scoped declaration of the
same spelling is an attributed setup error. Legacy registrations retain their
current completion and environment behavior; they do not acquire new runtime
syntax validation. Migrating a shared spelling is therefore atomic across its
declarers. Keep `register_completions()` and the existing help callback as
compatibility paths.

## Scanning, invocation, and edits

Scan once per parsed view over the declared subset, recording immutable
occurrences with original argument indexes and explicit, environment, or default
value sources. The authoritative index space is the wrapper's argument tuple
after existing core logging and environment-option normalization. Preserve exact
tokens and ordering for everything not edited.

Support separate and assigned long-option values, unambiguous short clusters,
and attached short values. A declared valueless option with an assigned value,
a missing declared value, a prohibited value form, and an invalid repeat of a
declared nonrepeatable option are usage errors with exit 2. An undeclared
`--name=value` is opaque and self-contained. An unknown leading bare option that
could consume a later declared command leaves command resolution incomplete and
forwards the original argv; it does not cause a usage error. Use foreign hints to
resolve known child flags such as a root option followed by its value. A command
word used as an unknown option's possible value must not be guessed as a command.

By default, `--` ends declared scanning; the remaining tail is opaque and cannot
be mistaken for commands, wrapper options, or help. A resolved command may
explicitly opt into scanning its own tail. An option known only on another
command remains untouched and passes to the child. Command-level strictness
applies only to truly unknown options in that command's segment, before `--`
unless tail scanning was explicitly enabled.

After normalization, the goal asks core to route the invocation before
`before_goal`. Core filters outer hooks and goal dispatch by that one selected
set, including mandatory plugin dependencies, and exposes the selected IDs to
`achieve()`. Discovery, import, and setup still occur during application
construction. An unresolved or unknown command runs plugins whose explicit or
default participation is every invocation. A parser usage error returns exit 2
before invocation hooks and child execution.

Extend argument contributions with index-anchored insertions so semantic
replacement keeps its position. Parsed occurrences translate to immutable
contributions; every analyzer still sees the same original call. Reject a
semantic edit to only part of a shared short-option token unless it replaces the
whole token. Anchored edits cannot cross the `--` boundary. Revalidate only
declared syntax after merging and before `prepare_call`. Invalid declared syntax
returns exit 2 without preparation or child execution; unknown child syntax
remains the child's responsibility.

## Help and completion

`--help` before `--` selects wrapper help mode. Root help runs child help,
eligible analyzers and finalizers, then appends wrapper help and the full
unscoped plugin list. Command help includes the goal's and participating plugins'
command sections. A plugin-owned command's help does not launch the child.
`before_goal` preemption takes precedence over goal-rendered help. Analyzer
edits and preemption remain ignored in help mode, and preparation remains
skipped. `-h` continues to pass through to the child and is reserved from new
plugin declarations. A `--help` token after `--` does not select wrapper help.

`--engulf-plugin-help ID` and `--engulf-plugin-help=ID` display focused plugin
help without launching the child or leaking the selector into child argv.
Declarative command, option, and positional descriptions provide structured
help; a command-path-aware callback may add plugin prose. Existing unscoped
plugin help remains visible on root `--help`.

Extend the compiled completion artifact with command paths, placement, arity,
foreign hints, scoped spellings, and serializable command-aware selectors.
Dynamic completion for a scoped option activates only its provider owner and
mandatory dependency closure; static requests remain import-free. Keep
wrapper-only options and their values hidden from native child completion,
preserve opaque child words, and suppress child completion for plugin-owned
commands. Retain the existing native-completer preference, wrapper candidate
merge, and completion-sourcing opt-in.

## Verification and delivery

- Boot a real wrapper with two representative plugins declaring the same option
  on disjoint commands and a third plugin contributing help or completion to a
  command owned by another participant. No consumer repository migration is part
  of this implementation.
- Run a pass-through corpus with no plugin CLI declarations and assert the child
  receives byte-identical argv. Include leading child flags with and without
  foreign arity hints, unknown commands, a command word as an opaque option value,
  `--` tails, and a no-command line.
- Cover assigned and separate values, per-option form restrictions, short
  clusters, environment-only participation, scoped strictness, wrong-scope
  pass-through, anchored edits, and post-edit validation before preparation.
- Verify an always-participating collector receives outer hooks on
  `install-completion`, root help, and unknown commands. Cover child versus
  plugin-owned help, `before_goal` preemption, `-h` passthrough, and `--help`
  after `--`.
- Verify compiled completion activates exactly the matching owner and mandatory
  dependency closure, while static completion imports no plugin and native
  child completion receives only the intended normalized words.
- Run the workspace checks required by `AGENTS.md` and read-only compatibility
  checks in `../engulf-clab`. Follow the workspace rule against version bumps
  during first-release development. Do not publish changed packages under an
  unchanged version; plan a separate versioned release before distribution.
