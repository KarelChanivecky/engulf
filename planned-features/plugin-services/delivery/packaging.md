# Packaging and compatibility rollout

Back to [delivery](README.md). The [inventory](package-inventory.md) is a source
snapshot, not a complete list of externally owned downstream products or a claim
that proposed versions are unused on a package index.

## Foundation candidates

| Distribution | Observed version | A source-based candidate | Required direct floors |
| --- | --- | --- | --- |
| `engulf-api` | 1.3.0 | 1.4.0 | None; dependency-free |
| `engulf` | 0.3.0 | 0.4.0 | `engulf-api>=1.4,<2` |
| `engulf-executable-wrapper-api` | 1.2.1 | 1.3.0 | `engulf-api>=1.4,<2` |
| `engulf-executable-wrapper` | 0.3.0 | 0.4.0 | `engulf>=0.4,<1`, wrapper-api `>=1.3,<2` |
| Owned plugins, capability APIs, apps, examples, aggregate and skill packages | Per inventory | Next unused patch where only compatibility metadata changes | Raise only direct dependencies that need the new coordinated floor; retain existing upper bounds unless justified |

The user explicitly chose package/floor bumps while preserving catalogs. This is
the planned rollout exception to the workspace's general first-release no-bump
guideline; it is not an instruction to edit versions in this documentation task.
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

If A used the candidates above, Engulf and wrapper 0.5.0 are source-based B candidates.
Confirm actual unused versions when preparing the release. The API packages need
no new version merely to flip concrete implementation availability if the frozen
interfaces still match. Optional services packages start at a version selected at
their consumer gate; 0.1.0 remains the seed candidate.

| Package role | B dependency direction |
| --- | --- |
| `engulf-services-api` | Foundation `engulf-api` definitions |
| `engulf-services` base | Core API + services API; no concrete Engulf/wrapper imports in the child-client closure |
| Optional wrapper integration extra/module | Adds wrapper API dependency; application already supplies functional wrapper runtime |
| `engulf-plugin-services` | Core API, wrapper API, services API; returns immutable transport configuration only |
| Domain provider/consumer | Own capability API + applicable goal/API packages; runtime implementation not required |
| Hosting application | Functional core/wrapper floors, services integration and accepted capability APIs/codecs |
| Python child | Services client/runtime package + services/core/domain APIs; no concrete host runtime requirement |

Unrelated plugins do not undergo a second blanket catalog migration in B. Actual
service adopters still require new source/package releases and coherent capability
dependency floors. Removing an old capability API surface must follow that package's
own compatibility rules; retaining an old helper symbol temporarily is acceptable
only if migrated application paths cannot fall back to foreign calls/deferred writes.

## Clean-install matrix

| Combination | Expected result |
| --- | --- |
| Old consumer/API subclass + A runtime | Existing behavior, concrete unsupported defaults for new members |
| Updated metadata-only plugin set + A runtime | Normal discovery under existing catalogs, existing context behavior |
| B services/application + A runtime | Explicit installation/availability refusal before provider business work |
| A-definition consumer + B runtime with no registered operation | Generic support implemented, request rejected as unknown operation |
| B local services + no broker | Local calls work; no child endpoint |
| B broker + empty child grants | Bounded handshake directory exposes no services |
| B provider wheel installed but unselected | No import, registration or activation |
| B API-only provider/child environment | No accidental concrete host-runtime dependency |

Run `engulf-check-packaging` with required dependency wheels installed. Build the
current five public distributions for A using `./build.sh`; update that build list
to eight only when the three optional packages arrive in B. Build/test affected
downstream distributions and examples according to their owning workflows. Do not
hand-edit generated archives or imply that documentation validation built new wheels.
