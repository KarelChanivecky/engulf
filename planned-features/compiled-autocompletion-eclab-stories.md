# Eclab user stories for compiled completion

Status: design evidence and acceptance scenarios for
[compiled autocompletion](compiled-autocompletion.md), based on the inspected
`../engulf-clab` working tree. Existing declarations and providers are distinguished
from proposed improvements; no eclab code is changed by this design.

## What the current application exposes

The [wrapper guide](../../engulf-clab/engulf-clab/README.md#shell-completion)
describes native Containerlab completion combined with schema-backed wrapper
commands, flags, positional values, and paths. Its
[application definition](../../engulf-clab/engulf-clab/src/engulf_clab/app.py)
uses the executable-wrapper goal, declared plugin selection, and explicit native
completion sourcing. The runtime goal also chooses its executable using the
current environment and interpreter location.

Most plugins derive from `SchemaBackedPlugin`. The
[schema completion adapter](../../engulf-clab/plugins/engulf-clab-schema-api/src/engulf_clab_schema_api/completion.py)
converts declarations into three ordinary Python objects:

- `_CommandCompleter`: command names and aliases, scoped flags, positional counting,
  and values, mixing static decisions with path listing.
- `_ValueCompleter`: literals, explained values, defaults, booleans, and paths.
- `_CommandPredicate`: command-sensitive flag visibility.

These are the first integration targets for the proposed declarative export
protocol. Treating them all as opaque dynamic providers would load many plugins
for static requests and lose much of the intended benefit. There is no need to
run the topology/schema/skill compiler to export these completion declarations.
The schema API already requires registration to avoid those operations.

## Story matrix

Every row assumes a clean generated artifact. A dirty artifact first rebuilds the
declarations. "No plugins" means no goal-plugin activation by Engulf; the Python
helper and any native executable completer still have their own work to do.

| User story and input | Desired result | Source of candidates and required activation |
| --- | --- | --- |
| Discover installed commands: `eclab fr<TAB>` | Offer `freeze` only when its plugin is selected. | Compiled command table; no plugins. |
| Discover command flags: `eclab freeze --<TAB>` | Offer flags such as `--output=`, `--offline`, and `--external-image=` in the correct scope. | Compiled schema; no plugins. |
| Choose a license strategy: `eclab deploy --eclab-license-pool-strategy=<TAB>` | Offer `sticky`, `round-robin`, and `least-recently-used` with descriptions/default information. | Compiled literal values; no license allocation or plugin activation. |
| Choose a directory: `eclab init-license-pool ./lic<TAB>` | Offer matching directories from cwd, ending in `/`, plus the declared default where appropriate. | Generated path instruction executed by the library; no plugins. |
| Complete a positional after an option value: `eclab init-license-pool --kind fortinet_fortigate <TAB>` | Complete the pool-directory positional, not a second or third positional. | Compiled command/arity tables plus directory listing; no plugins. |
| Select an archive: `eclab defrost ./sha<TAB>` | Offer matching paths without extracting an archive. | Library path discovery; no freeze command execution. |
| Select the destination: `eclab defrost share.tar.gz --into ./la<TAB>` | Offer directories only, preserving the typed relative prefix. | Library path discovery selected by scoped flag; no plugins. |
| Choose a VM node: `eclab deploy -t labs/demo.clab.yml --eclab-vrnetlab-image <TAB>` | Offer `default=` and opted-in effective node names, omitting selectors already supplied. | Runtime slot owned by `engulf_clab.vrnetlab_build`, plus its mandatory dependency closure. |
| Choose that node's image: `eclab deploy -t labs/demo.clab.yml --eclab-vrnetlab-image edge-1=images/<TAB>` | Offer `edge-1=images/...` from the topology directory rather than the shell cwd. | Same plugin slot; fresh topology and path lookup. |
| Choose a build concurrency default: `eclab deploy --eclab-vrnetlab-build-jobs <TAB>` | Offer the declared default, currently `2`. | Lower the constant provider to literal instructions; no builder activation. |
| Continue native Containerlab completion: `eclab inspect <TAB>` | Retain native Containerlab suggestions alongside applicable wrapper additions. | Native shell completer and compiled wrapper rules; no fallback binary-provider activation if native exists. |
| Install/remove a feature plugin | Next TAB adds/removes its commands and flags without manually regenerating every shell file. | Fresh metadata validation, one schema rebuild, then clean evaluation. |

Concrete declaration sources:

- [License commands, strategies, and path values](../../engulf-clab/plugins/engulf-clab-license-pool/src/engulf_clab_license_pool/plugin.py).
- [Freeze/defrost commands, flags, and positional archive](../../engulf-clab/plugins/engulf-clab-freeze/src/engulf_clab_freeze/plugin.py).
- [Vrnetlab option registration and constant concurrency provider](../../engulf-clab/plugins/engulf-clab-vrnetlab-build/src/engulf_clab_vrnetlab_build/plugin.py).
- [Existing schema completion tests](../../engulf-clab/plugins/engulf-clab-schema-api/tests/test_completion.py), including skipping an earlier flag value when choosing a positional.

## Runtime story: topology nodes, then image paths

The existing
[`complete_image_option()` implementation](../../engulf-clab/plugins/engulf-clab-vrnetlab-build/src/engulf_clab_vrnetlab_build/options.py)
already performs the desired two-stage runtime lookup:

1. Select the topology using the full argument list or implicit cwd discovery.
2. Load its current contents through the shared parser helpers and find effective
   nodes with a nonempty vrnetlab-type environment setting.
3. Before the inner `=`, suggest `default=` and eligible node names. Inspect earlier
   occurrences of the repeatable image option to suppress used selectors.
4. After `NODE=`, validate the selector and list matching paths relative to the
   topology's parent; use cwd for the fallback when no topology was resolved.

The option itself is static metadata: `takes_value=True`, `repeatable=True`,
`suggest_assignment=False`, hidden from native binary completion, and normally
offered after `deploy` or `redeploy`. The node set and directory entries are runtime
facts. A compiled plan should therefore contain a narrow runtime slot at the value
position, while compiling the option name and its visibility predicate separately.
Do not load the builder merely to suggest the option's name.

Proposed registration, retaining the current declarations around the provider:

```python
registry.option(
    IMAGE_OPTION,
    takes_value=True,
    metavar="NODE=FILE",
    value_completer=Runtime("image-selector", complete_image_option),
    suggest_assignment=False,
    repeatable=True,
    when=Match.any_prior_word(("deploy", "redeploy")),
)
```

The exact markup API is provisional. `Match.any_prior_word()` here preserves the
current predicate's behavior; a future command parser must not be silently assumed.
Value-position matching is implied by `value_completer`. The provider receives the
same original words as today, with the current word transformed only for the outer
`--option=value` form. It must not receive only normalized binary words, because
those have lost the previous image selectors.

Use the existing
[image option tests](../../engulf-clab/plugins/engulf-clab-vrnetlab-build/tests/test_options.py)
as the first migration fixtures, then add:

- Run from a cwd different from the selected topology's directory; verify relative
  image paths still resolve from that topology.
- Complete both `--eclab-vrnetlab-image edge-1=im` and
  `--eclab-vrnetlab-image=edge-1=im`, including Bash splitting either `=`.
- Verify `default=` and directory `/` candidates keep the current word open.
- Change the topology's nodes and create/remove an image file between TAB requests;
  results change while the compiled schema generation stays the same.
- Verify inherited `defaults < kind < group < node` settings, environment expansion,
  and the parser's lab env-file behavior through its existing read functions.
- For absent, ambiguous, incomplete, or invalid topologies, retain the provider's
  coherent fallback (such as `default=`) without executing a deployment or fetching
  a URL/reading topology input from the terminal.

The [parser's source-selection and environment contract](../../engulf-clab/plugins/engulf-clab-lab-parser/USAGE.md)
owns accepted topology names, aliases for `-t`, env files, and inheritance. Keep
that domain logic out of the generic autocomplete compiler. If several matching
providers need this data, a completion preparation phase may share one read-only
snapshot for the request through declared context access; it must not invoke the
normal topology mutation session.

## Runtime story: respecting the real prerequisite graph

The current vrnetlab package's
[dependency declarations](../../engulf-clab/plugins/engulf-clab-vrnetlab-build/pyproject.toml)
include both `before` and `after` edges. Following mandatory dependencies in the
inspected source metadata yields:

```text
lab_parser -> ensure_vrnetlab -> vrnetlab_build -> image_build -> lab_writer -> schema
```

The arrow denotes required preprocessing order; additional direct edges are omitted
from this illustration. All six IDs are prefixed with `engulf_clab.`. The closure
comes from vrnetlab's direct requirements plus the dependencies declared by
[ensure-vrnetlab](../../engulf-clab/plugins/engulf-clab-ensure-vrnetlab/pyproject.toml),
[image-build](../../engulf-clab/plugins/engulf-clab-image-build/pyproject.toml),
[lab-parser](../../engulf-clab/plugins/engulf-clab-lab-parser/pyproject.toml), and
[lab-writer](../../engulf-clab/plugins/engulf-clab-lab-writer/pyproject.toml).

Under the current Engulf contract, this is the activation set for the image-selector
slot, even though only one provider returns its candidates. It excludes unrelated
WAN, sticky-IP, PKI, license, and container-collection plugins. Loading only
`vrnetlab_build`, `ensure_vrnetlab`, and `lab_parser` would drop mandatory `after`
dependencies. If six instances remain too costly, define a separate completion
presence contract later, rather than treating `after` as optional implicitly.

Activation must not run the normal work associated with these packages. In
particular, completion does not clone/update vrnetlab, build an image, write a
derived topology, or compile the full lab schema. The existing topology data is
read directly by the completion provider; normal parser `prepare_call()` need not
run merely because the parser is a dependency. New completion-only preparation
can move that shared read behind the normal `before` relationship.

## Runtime story: completion must not execute the command

Several eclab plugins implement their own commands in `before_goal()` rather than
executing Containerlab:

- License-pool initialization registers a pool in user state.
- Freeze/defrost creates or extracts files and can restore runtime/image inputs.
- [Consumption](../../engulf-clab/plugins/engulf-clab-consumption/src/engulf_clab_consumption/plugin.py)
  queries running resources and can poll continuously.
- [Reclaim](../../engulf-clab/plugins/engulf-clab-reclaim/src/engulf_clab_reclaim/plugin.py)
  stages resource deletion and completes it in its lifecycle.
- [Sudoless setup](../../engulf-clab/plugins/engulf-clab-ensure-containerlab/src/engulf_clab_ensure_containerlab/plugin.py)
  performs explicit host administration.

Completing any of these command lines, including during a cold schema rebuild,
must call neither their command implementation nor the ordinary outer hooks.
Use spies for state writes, Docker calls, filesystem extraction, privilege prompts,
and Git activity in acceptance tests. This follows from the actual lifecycle entry
points in the source; this review has not executed those commands to probe them.

## Edition and environment stories

As an edition author, I need declarations compiled for the concrete launcher even
when it shares `application_id` with eclab. The
[skill plugin](../../engulf-clab/plugins/engulf-clab-develop-eclab-lab/src/engulf_clab_develop_lab_skill/plugin.py)
only registers `install-develop-eclab-lab-skill` for the eclab short-product identity.
The [schema adapter tests](../../engulf-clab/plugins/engulf-clab-schema-api/tests/test_completion.py)
also exercise `{short_product}` expansion. Do not reuse one edition's generated
command set for another. Fixed `ECLAB_*` controls remain fixed wherever their source
declares them; do not mechanically rebrand every option or environment variable.

As a lab author, I need explicit topology selection to work independently of cwd.
The [workspace resolver](../../engulf-clab/engulf-clab/src/engulf_clab/workspace.py)
uses the selected topology's directory for state, while many CLI file paths remain
relative to the invocation directory. Carry both identities rather than replacing
the shell's cwd with the workspace before running a provider.

Environment-bound CLI options remain visible in original completion words. Fully
provided values may overlay a separate effective environment for discovery, while
an incomplete value under the cursor must not be applied as configuration. For
example, a topology-aware discovery phase should pass that effective environment
to the parser instead of temporarily changing `os.environ`.

The app's `binary_path()` also depends on `CONTAINERLAB_DIR` and the interpreter's
companion executable. Register these as declared bootstrap inputs, including
candidate-file existence, so switching that configuration invalidates the cached
native-completion descriptor without activating provisioning plugins. A clean
helper must not freeze the executable choice from the first installation forever.

## What is not currently declared

Some attractive dynamic stories need new provider declarations; compiling existing
metadata alone cannot create them:

- The current `pki` action positional is `ValueType.STRING`, with action names in
  explanatory text. It does not enumerate an action grammar for completion.
- `freeze --bundle-image` and `--external-image` declare an image-reference type.
  That type does not authorize or describe querying the Docker image catalog.
- A catalog of available license kinds, PKI identities, or registered labs would
  likewise need an explicit runtime slot, selector, and owner.

Do not infer shell candidates or I/O from prose, invoke a command's help/parser to
guess them on every TAB, or enumerate Docker just because a type is named
`IMAGE_REFERENCE`. The new runtime markup is how authors add those data sources.

## Design consequences

These stories make the minimum useful delivery more specific:

1. Accept existing registries, and give schema-backed provider objects an explicit
   way to export static decisions and built-in dynamic instructions.
2. Compile command context and option names separately from runtime values, so
   typing `--` does not activate every plugin with a dynamic value completer.
3. Preserve complete original arguments, nested assignments, path bases, and
   effective request environment across runtime slots.
4. Compute dependency presence and ordering separately; the real vrnetlab fixture
   must prove both selective import and mandatory prerequisites.
5. Keep all ordinary command lifecycle work out of clean evaluation and rebuilds.
6. Test both fresh runtime data without a rebuild and plugin/environment changes
   that must invalidate a compiled generation.
