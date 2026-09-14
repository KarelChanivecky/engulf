# Application composition and policy

Back to [eclab adoption](../README.md). Source:
[both construction paths](../../evidence.md#images-and-application-composition).

## Composition

Create one application-owned helper that builds the accepted registry/image
descriptors, installed recipe codecs, local caller policy and conditional required
services. Use it in both `_containerlab_goal()` and `ContainerlabApp.__init__`.
Preserve executable resolution, completion provider/opt-in, metadata, workspace
resolver, plugin policy and side-effect-free import behavior.

```text
make_containerlab_execution_support():
    return ServicesExecutionSupport(
        accepted_capabilities=(REGISTRY_V1, IMAGE_OFFERS_V1),
        codecs=explicit_registry_and_recipe_codecs,
        local_access=application_service_policy,
        required=registry_when_consumption_or_sleep_selected,
        child_grants=empty
    )

_containerlab_goal():
    return ExecutableWrapperGoal(binary_path(), source_completion=True,
        execution_support=make_containerlab_execution_support())

ContainerlabApp.__init__(...):
    goal = ExecutableWrapperGoal(selected_binary, existing_completion_options,
        execution_support=make_containerlab_execution_support())
    construct Application with existing metadata/policy/workspace options
```

The helper factory itself creates only configuration. Actual service setup runs in
goal setup, after selected plugin discovery and help collection. Editions can add
providers or the broker through normal selection without replacing the goal factory.
Forks retain their separate application/state/lease identity. Branding is never a
service authorization identity.

## Policy baseline

| Caller | Allowed local service use |
| --- | --- |
| `engulf_clab.consumption` | Registry inventory and complete-observation commit |
| `engulf_clab.sleep` | Same registry methods under its existing Docker lease |
| `engulf_clab.image_build` | Enumerate/call accepted selected wrapper image-offer providers |
| Goal helper | Private child-scope controls from the actual goal frame; only configured child grants |
| Other providers/consumers | Only application-declared local dependencies, no automatic transitive direct grant |
| Wrapped Containerlab child | Empty grants for these initial migrations |

The registry is required only when selected consumers need it. No image default is
configured: image-build requests all domain offers. Broker absence disables only
child transport. Minimal/custom policies without those consumers remain viable.

## Compatibility gates

The application requires B's functional Engulf and wrapper versions and services
integration dependency/extra. Bootstrap verifies the expected generic operation
major and concrete `implemented` flags before provider business work. An A runtime
must reject this integration explicitly. Merely importing new names or selecting
the broker does not prove availability.

Test standard definition construction, an edition, direct `ContainerlabApp`, custom
binary/completion, minimal allow-only policy, missing required registry, no broker,
and import without discovery. Verify module origins in development to avoid mixing
installed API wheels with unrelated source runtimes.
