# Image-offer migration

Back to [eclab adoption](../README.md). Evidence:
[image API, resolver and adapters](../../evidence.md#images-and-application-composition).

The current `IMAGE_PROVIDER_CONTEXT` path carries foreign operational objects into
image-build's activation. The DockerImage goal already supplies the sanctioned
`PROVIDE_IMAGE_PHASE`: owner logic, owner activation, owner API. Wrapper services
use that same shape through the wrapper adapter's service phase. They do not call
the separate DockerImage adapter outside its goal or merge unrelated catalogs.

## Adapter inventory

The reviewed working source currently has direct registration sites in these six
wrapper adapters; the initial seed's count should be re-inventoried, not assumed:

| Active wrapper provider ID | Preparation/behavior |
| --- | --- |
| `engulf_clab.image_archive` | Prepared archive request map; current domain priority 72 |
| `engulf_clab.vrnetlab_build` | Prepared vrnetlab request map; current domain priority 75 |
| `engulf_clab.containers` | Selected collection-backed image provider; current priority 85 |
| `engulf_clab.pki_linux_core` | Capability-free image recipe provider |
| `engulf_clab.pki_linux_debian` | Capability-free image recipe provider |
| `engulf_clab.pki_linux_fedora` | Capability-free image recipe provider |

The default pull in `engulf-docker-image-core.provision` is synthetic domain fallback,
not another selected provider plugin. Existing separate image-goal IDs such as
`engulf_clab.pki_linux_core.images` remain in that goal's catalog. Wrapper services
attribute work to the wrapper ID. Legacy domain preference/tie order must be made
explicit in the image capability metadata when ID translation could alter a tie.

## Offer contract and lookup seam

Return exactly one `Offer`, `Reject`, or `NoOpinion`. The image capability API owns
typed requirement/recipe codecs and domain preference metadata; generic services
only provides deterministic ID enumeration and authorized addressing.

```text
image_build.prepare_call(event, api):
    graph = existing final-topology roots + immutable graph fragments
    providers = image_domain_order(services(api).providers(IMAGE_OFFERS_V1))

    def lookup(requirement):
        responses = []
        for provider in providers:
            reply = typed_image_client(provider).offer(requirement)
            if reply is NoOpinion: continue
            responses.append(AttributedImageResponse(provider.provider_id,
                                                       to_existing_response(reply)))
        return tuple(responses)

    provision_image_graph(graph, api=api, provider_lookup=lookup,
                          max_workers=existing_jobs_option)
    existing derived-topology image-pull-policy update

provider.call_service(request, own_api):
    if required prepared state is absent: return declared domain error offer_not_ready
    return own_domain_offer_logic(request.requirement, own_api)
```

The lookup closure runs synchronously inside image-build's active preparation, and
each offer call reactivates the selected owner. It is a goal-local orchestration
closure over a live caller API, not a provider implementation published to context
or a worker. The existing provisioner response cache and resolver receive detached
data. Build workers receive resolved recipes only.

This matches the rechecked sibling implementation: `provision.py` calls
`resolve_image_graph(..., provider_lookup=lookup)` synchronously before
`build_resolved_graph`; `build.py::_build_batch` submits only `_build_image(image)`.
Passing `api` and `lookup` to the orchestration function does not submit them to its
pool. Preserve this sequence on every candidate-fallback iteration. I-WORKER records
thread IDs on real lookup calls and inspects submitted arguments to ensure no API,
provider handle or client-bearing closure reaches a worker; a mocked provisioner
alone is insufficient. This refutes S25's claimed violation, while retaining its
useful regression case.

## Preserve domain behavior

Authority ranking, terminal rejection, explicit graph provisions, deterministic
ties, recursive dependency resolution, conflicts, local-or-pull fallback, candidate
failure exclusion, and opt-in build fallback remain in image core. Domain fallback
after a failed recipe build is not an RPC retry. Unexpected provider defects must
not be caught as ordinary candidate failures and hidden behind a lower-ranked offer.

Keep provider preparation ordering after relevant topology mutators and before
image-build, then writer serialization. Service registration/entered status is not
proof the archive/vrnetlab map is ready. Reset method readiness per invocation;
populate in the owner's prepare, clear on its self-failure, later preparation failure
and after-call. After clearing, reject dependent offers as not ready rather than
reuse an earlier invocation's map or silently substitute a pull.

Pure offer helpers may remain private implementation objects owned by their adapter.
What disappears is publishing/calling them from another participant's activation.
Preserve the existing standalone DockerImage goal adapter and `PROVIDE_IMAGE_PHASE`.

## Recursive review and acceptance

Test owner API/logger/state attribution, prepared-map readiness, repeated calls and
invocations, all response variants, terminal rejection suppressing fallback,
authority and tie order, archive/vrnetlab failure policy, graph conflicts/cycles,
candidate build fallback and the synthetic pull. Compare pre/post migration fixtures
for domain results, while explicitly updating wrapper attribution IDs.

Prove no callables/providers remain in `IMAGE_PROVIDER_CONTEXT`, no raw lookup
fallback executes foreign code, and no build worker receives a managed API. Inspect
metadata and tests of every current producer and consumer together. Immutable image
graphs and schema contributions need not become services merely because they share
context.

The adapter list is repository-scoped, not an inventory of private third-party
providers. Follow B-MIGRATE's deprecation and selected-metadata refusal before
removing the old context key. A selected external legacy provider must trigger an
actionable migration diagnostic, not disappear from offers and silently change
the chosen image recipe.
