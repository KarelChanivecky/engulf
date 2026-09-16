# Application composition and policy

Back to [eclab adoption](../README.md). Source:
[both construction paths](../../evidence.md#images-and-application-composition).

## Composition

Create one application-owned configuration factory that builds the accepted registry/image
descriptors, installed recipe codecs, local caller policy and conditional required
services. Use it in both `_containerlab_goal()` and `ContainerlabApp.__init__`.
Preserve executable resolution, completion provider/opt-in, metadata, workspace
resolver, plugin policy and side-effect-free import behavior.

```text
make_containerlab_services_configuration():
    return ServiceConfiguration(
        accepted_capabilities=(REGISTRY_V1, IMAGE_OFFERS_V1),
        codecs=explicit_registry_and_recipe_codecs,
        local_access=application_service_policy,
        required=registry_when_consumption_or_reclaim_selected,
        child_grants=empty, child_executable_opt_in=empty,
        elevated_child_grants=empty, permitted_broker_ids=empty
    )

ContainerlabServicesGoal(ExecutableWrapperGoal):
    setup(api):
        super().setup(api)
        install_services(api, configuration=make_containerlab_services_configuration())

_containerlab_goal():
    verify_functional_core_and_service_definitions_before_goal_construction()
    return ContainerlabServicesGoal(binary_path(), source_completion=True)

ContainerlabApp.__init__(...):
    verify_functional_core_and_service_definitions_before_goal_construction()
    goal = ContainerlabServicesGoal(selected_binary, existing_completion_options)
    construct Application with existing metadata/policy/workspace options
```

The factory itself creates only configuration. Actual service setup runs in
goal setup, after selected plugin discovery and help collection. Editions can add
providers or the broker through normal selection without replacing the goal factory.
Forks retain their separate application/state/lease identity. Branding is never a
service authorization identity.

`engulf_services.install_services(api: GoalSetupAPI, *, configuration:
ServiceConfiguration) -> None` is the B local integration entry point. It validates
availability, freezes setup contributions and registers the operation exactly once.
It imports no wrapper/transport strategy. `Goal.setup` is overridable, so this
app-owned subclass permits local adoption after B1/B3, without B2's process seam.
Because elevated startup checks the exact concrete goal class, the app's owning
wheel must declare and pass the existing privilege opt-in for this subclass; the
wrapper goal's opt-in is not inherited.

Later B2/B6 integration may use the same configuration through
`ServicesExecutionSupport.setup`. Choose either subclass registration or helper
registration, never both. The later bootstrap checks wrapper support availability
before passing `execution_support=`; local-only construction needs no such keyword.
Cross-plan X-CLI tests both composition modes with parser/help/completion setup.

## Policy baseline

| Caller | Allowed local service use |
| --- | --- |
| `engulf_clab.consumption` | Registry inventory and complete-observation commit |
| `engulf_clab.reclaim` | Same registry methods under its existing Docker lease |
| `engulf_clab.image_build` | Enumerate/call accepted selected wrapper image-offer providers |
| Goal helper | Private child-scope controls from the actual goal frame; only configured child grants |
| Other providers/consumers | Only application-declared local dependencies, no automatic transitive direct grant |
| Wrapped Containerlab child | Empty grants for these initial migrations |

The registry is required only when selected consumers need it. No image default is
configured: image-build requests all domain offers. Broker absence disables only
child transport. Minimal/custom policies without those consumers remain viable.

## Compatibility gates

The local application requires B's functional Engulf and services integration, plus
the wrapper version supporting its existing subclassed behavior. Child integration
also requires B's functional wrapper and integration extra. Bootstrap verifies
definition imports and concrete availability before goal construction; missing
flags/old constructor versions produce actionable availability errors. An A runtime
must reject this integration explicitly. Merely importing new names or selecting
the broker does not prove availability.

Test standard definition construction, an edition, direct `ContainerlabApp`, custom
binary/completion, minimal allow-only policy, missing required registry, no broker,
and import without discovery. Verify module origins in development to avoid mixing
installed API wheels with unrelated source runtimes.

A separately upgraded service consumer can still be installed with an old hosting
application: plugin metadata cannot express that the goal registered an operation.
The consumer therefore performs its typed service preflight before command business
work and reports the required application update. This case is tested explicitly
in packaging; API-only wheels do not acquire a dependency on the application runtime.
