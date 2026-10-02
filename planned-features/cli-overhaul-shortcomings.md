# CLI overhaul shortcomings

The first attempt at a goal-owned CLI (argparse-backed `NativeCLIAdapter`,
`register_cli`, `CLIView`, semantic edits, and invocation routing) is archived on
branch `archive/cli-adapter-argparse`. It was abandoned because its parser model
does not fit a wrapper. This note records what went wrong so the next design starts
from these requirements rather than rediscovering them.

## Parser model

A wrapper knows only the parts of the wrapped CLI it cares about. Functioning with
an unknown CLI is the core requirement. argparse is a closed-grammar parser and
fights that requirement:

- Declaring any command turns every other first word into an "invalid choice".
  The adapter then fell back to an empty partial view with no occurrences, so
  semantic edits stopped working on ordinary wrapped command lines.
- `parse_known_args` reports every undeclared token as unknown, which made
  `partial` true on practically every real command line. Routing returned "all
  plugins" and never engaged.
- Top-level options that appear after an undeclared command word are never
  seen.
- The adapter scanned the tokens a second time to recover occurrence indexes and
  reconciled the two passes with an `incomplete_provenance` heuristic.
  argparse contributed little beyond command resolution, positional counts,
  choice checks, and help formatting.

Requirement: a single-pass scanner over the declared subset. Unknown tokens are
opaque by default and never cause an error. Occurrences carry original indexes
directly. `partial` means genuine ambiguity, not "tokens I don't own". Only
malformed use of a declared element is a usage error.

## Inherent ambiguities

These need an explicit policy before implementation:

- Arity of undeclared options: in `wrap --foo deploy`, is `deploy` a command or
  `--foo`'s value? Consider foreign-arity hints that describe an option without
  claiming ownership, and flag ambiguity only when it changed the reading.
- Where a declared command word may resolve: in `wrap build deploy` with only
  `deploy` declared, is `deploy` a command?
- Short-option clusters and attached values (`-abc`, `-n5`).

## Participation

Declaring an option, positional, or command opted the plugin *out* of every
invocation that did not use it. A plugin that must run on `deploy` whether or not
its flag is present had no way to say so. A command declared with
`executes=False`, for help or completion only, excluded its owner from every
invocation. Participation must be explicit, declared, and separate from
ownership: always, for listed commands, or when an owned element is used. The
archive's `CLIBuilder.participate()` / `CLIParticipation` is a usable shape.

## Goal-owned commands bypassed the framework

`install-completion` predates the parser and remains a string check in
`achieve()` with its own tokenizer, usage text, and completion branch. Overhaul
routing hard-coded "no plugins" for it. That regressed the earlier behavior where
plugins' outer hooks run on it, which engulf-clab's `develop_lab_skill` relies
on. `--help` is special-cased the same way. Requirement: the goal declares its
own commands and options through the same builder, like a meta-plugin. Parsing,
routing, participation, help, and completion then derive from those declarations.
Plugins join goal-owned commands by the ordinary participation rules.

## Invocation flow

- The re-parse after plugin edits was unguarded. A plugin adding a second
  occurrence of a non-repeatable option crashed the invocation instead of
  exiting 2.
- Routing was computed twice, once in `Application` and again in `achieve()`,
  over different eligible lists. The runtime should hand its decision to the
  goal (the archive adds `GoalAPI.participant_ids`).

## Release hygiene

The public API changed without version bumps or new dependency floors. The
package index holds engulf and engulf-executable-wrapper 0.1.2 and both API
packages at 1.0.2. The next attempt bumps the minor versions and raises the
floors together with the API change.

## Open gaps

- Declarative completion providers (`when=` matchers, runtime value completers)
  so consumers can retire `register_arguments()`.
- Persisting the compiled CLI artifact (store, fingerprint, restore path) so
  consumers stop hand-rolling their own completion artifact stores.

## Worth keeping from the archive

- Portable, data-only declarations in `engulf-api`.
- Attributed conflict detection across plugins.
- Occurrence handles with original token indexes.
- Semantic removals and replacements.
- The `participate()` shape.
- `GoalAPI.participant_ids`.
