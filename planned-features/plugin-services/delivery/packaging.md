# Packaging and compatibility rollout

Back to [delivery](README.md). The [inventory](package-inventory.md) is a source
snapshot, not a complete list of externally owned downstream products or a claim
that proposed versions are unused on a package index.

## Current baseline and future release manifest

| Distribution | Observed at `4c7e95e` | Future A release marker | Required direct floors at that release |
| --- | --- | --- | --- |
| `engulf-api` | 1.0.0 | A_API | None; dependency-free |
| `engulf` | 0.1.0 | A_CORE | Selected A_API version, `<2` |
| `engulf-executable-wrapper-api` | 1.0.0 | A_WRAPPER_API | Selected A_API version, `<2` |
| `engulf-executable-wrapper` | 0.1.0 | A_WRAPPER | Selected A_CORE, `<1`; A_WRAPPER_API, `<2` |
| Owned plugins, capability APIs, apps, examples, aggregate and skill packages | Refreshed inventory | Per-package release decision | Raise only applicable direct floors; retain justified upper bounds |

The previous 1.3/0.3 observations and derived 1.4/0.4 candidates are superseded by
the beta reset. The markers above are release-manifest variables, not pip version
specifiers or assertions that an index contains a release. The user chose a future
coordinated package/floor rollout while preserving catalogs; current development
still follows AGENTS.md's no-bump rule. This documentation revision changes no
package metadata. A3 must reread both trees and assign actual unused versions when
that release work is performed; a snapshot is not a release authorization.
Keep `PLUGIN_API_MAJOR = 1`, existing goal catalog majors, plugin IDs and application
IDs. Existing domain API packages may already have different distribution majors;
do not conflate those with the framework entry-point namespace.

Before implementing/releasing, refresh the inventory from both repositories and
explicitly supplied owned downstream roots. For every package record its current
version, proposed unused version, direct dependencies/extras, entry-point groups,
source origin and validation gate. Include launcher/core, aggregate requirements,
examples, MCP and skill wheels so pins cannot hold back the coordinated set.
Do not add runtime dependencies to API-only plugin wheels to force an upgrade.

## Functional runtime floors

B_CORE and B_WRAPPER denote the later functional releases. Local applications need
B_CORE; child integration also needs B_WRAPPER. Assign exact floors from the tested
release manifest, not old numeric candidates. A runtime-only availability change
does not inherently change an API package, but any B addition to an API wheel
(including the planned Unix binding declarations) needs its own compatible release
and updated direct floor. Do not promise that every API version is unchanged in B.
Optional services versions are chosen at their consumer gate.

| Package role | B dependency direction |
| --- | --- |
| `engulf-services-api` | Foundation `engulf-api` definitions |
| `engulf-services` base | Core API + services API; no concrete Engulf/wrapper imports in the child-client closure |
| Optional wrapper integration extra/module | Adds wrapper API dependency; application already supplies functional wrapper runtime |
| `engulf-plugin-services` | Core API, wrapper API, services API; returns immutable transport configuration only |
| Domain provider/consumer | Own capability API + applicable goal/API packages; runtime implementation not required |
| Hosting application | Functional core floor and local integration; functional wrapper/extra additionally for child integration; accepted capability APIs/codecs |
| Python child | Services client/runtime package + services/core/domain APIs; no concrete host runtime requirement |

Unrelated plugins do not undergo a second blanket catalog migration in B. Actual
service adopters still require new source/package releases and coherent capability
dependency floors. Removing an old capability API surface must follow that package's
own compatibility rules; retaining an old helper symbol temporarily is acceptable
only if migrated application paths cannot fall back to foreign calls/deferred writes.

## Clean-install matrix and detection points

| API / core / wrapper API / wrapper combination | Consumer/application | Expected detection or result |
| --- | --- | --- |
| A / A / A / A | Old consumer and custom API subclasses | Existing behavior; new members have concrete unsupported defaults |
| A / A / A / A | Updated metadata-only plugins | Existing discovery/context/help/completion |
| A / pre-A / A / pre-A | Legacy application | Can be valid for old calls; no blanket API-ahead-of-runtime rejection |
| A / pre-A / A / pre-A | Services-aware application | Resolver floors reject normally; forced environment refused by bootstrap before goal construction |
| A / A / A / A | B local services application | Functional core floor rejects at install; forced environment fails availability preflight |
| A / B / A / pre-A | Child-integrated B application | Wrapper floor rejects; forced environment preflight rejects before passing `execution_support=` |
| A / B / A / A | Local-only B application | Works via goal setup/subclass; no process-support requirement |
| Compatible / B / compatible / B | Existing unchanged plugin, no services installed | B-COMPAT: ordinary behavior plus explicitly documented cleanup deltas |
| A / B / compatible / compatible | Definition-only consumer, no registered operation | First request is `unknown_operation` |
| Compatible / B / compatible / compatible | Migrated consumer + old unintegrated application | Resolver may accept; consumer preflight maps missing registration to actionable application-upgrade error before business work |
| Compatible / B / compatible / compatible | New application + selected legacy context reader/provider | Application checks immutable selected metadata after construction and before invoke; names incompatible plugin and required upgrade |
| Compatible B set | Local services + no broker, or broker with empty grants | No child scope/endpoint; local services work |
| Compatible B set | Provider wheel installed but unselected | No import, registration or activation |
| API-only or Python child closure | Provider/consumer/child | No accidental host-runtime import/dependency |

For each row resolve/install built wheels in a fresh environment, run `pip check`,
then the corresponding construction/invocation smoke test. Include deliberate
`--no-deps` skew fixtures to check diagnostic timing. `engulf-check-packaging` checks
plugin dependency distribution names and order metadata, not version satisfaction;
run it as an additional packaging check with dependency wheels installed. Do not
add a universal runtime version-pair veto: compatible API-ahead combinations exist.
Hosting bootstrap checks actual required definitions/flags before optional imports
and new constructor calls, including help/completion entry paths.

Migrated plugins retain API-only dependency direction. Their package versions alone
cannot force an old application's goal to register services. Ship a documented
coordinated installation set and typed consumer preflight; do not pretend that a
capability-API major bump alone makes all incoherent app/plugin sets unresolvable.
Deprecate removed context contracts before migration, inspect
`Application.active_plugins[*].metadata.context_reads/context_writes` through the
public immutable descriptors, and close the constructed app on refusal. Both app
construction paths run this check before invoking. Keep any legacy compatibility
symbols out of migrated operational paths. B-MIGRATE includes external old-plugin
fixtures; an owned-source inventory cannot establish universal compatibility.

Build the
current five public distributions for A using `./build.sh`; update that build list
to eight only when the three optional packages arrive in B. Build/test affected
downstream distributions and examples according to their owning workflows. Do not
hand-edit generated archives or imply that documentation validation built new wheels.

## Independent compatibility axes

| Axis | Owner/check | Mismatch or extension rule |
| --- | --- | --- |
| `PLUGIN_API_MAJOR` / goal catalog major | Framework/goal API; installed discovery and contract checks | Existing catalogs remain 1; incompatible contracts require an explicit major/catalog migration |
| Managed operations major | Core API; hosting bootstrap | Refuse required unsupported major; optional future features need an additive probe, not a changed support property |
| Execution support major / binding IDs | Wrapper API/runtime and concrete strategy | Validate generic definitions separately from implementation and native binding availability |
| Capability major | Domain API and accepted application descriptor | Reject incompatible registration/calls; a newly installed provider cannot expand accepted application schemas |
| Codec ID/version | Capability API and application codec catalog | Require exact accepted binding; wire names never import code |
| Wire protocol major | Client/host handshake | Refuse mismatch; new required envelope semantics require a versioned negotiation change |
| Bootstrap/backend version | Local strategy | Exact local match before native resource claim; no backend-selected imports |
| Distribution versions/floors | Package owners, resolver and clean-install CI | Select actual releases independently of API majors; test partial upgrades and functional flags |

Application acceptance of new capability schemas is deliberately an application
release/configuration decision. Editions may select more already accepted providers;
they do not silently add trusted codecs or a new authorization policy. An open
third-party capability catalog is deferred until it has its own trust and composition
contract.
