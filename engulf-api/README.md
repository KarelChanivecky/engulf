# Engulf API

`engulf-api` is the dependency-free, versioned plugin contract for Engulf. Plugin
packages import `engulf_api`; they do not need to import or depend on the `engulf`
runtime package.

```python
from engulf_api import Plugin, PluginDependency


class AuditPlugin(Plugin):
    plugin_id = "com.example.audit"
    priority = 75
    plugin_dependencies = (PluginDependency("com.example.identity"),)
    context_reads = frozenset({"com.example.identity.principal"})

    def help(self) -> str:
        return "  --audit-log PATH   Record this invocation"

    def before_call(self, event, api) -> None:
        principal = api.require_context("com.example.identity.principal")
        api.add("--audit-principal", str(principal))


plugin = AuditPlugin
```

Plugin wheels should declare `engulf-api>=1.2,<2`. The contract follows semantic
versioning: compatible additions increment the minor version, while changes that
break plugin implementations or event consumers increment the major version.
`PLUGIN_API_MAJOR` is also encoded in installed-plugin entry-point groups such as
`engulf.plugins.v1.example_app`.

This package owns the plugin base class, lifecycle events, call-scoped `PluginAPI`,
dependency descriptors, argument and completion registries, completion value types,
and related enums. Process execution, plugin discovery, and shell integration remain
in `engulf`.

## Plugin Metadata

Every plugin declares a globally unique, lowercase, dot-qualified `plugin_id`.
Plugin and context identifiers use the same form, for example
`com.example.audit` and `com.example.identity.principal`.

Every plugin has an integer `priority` with a neutral default of `50`. Priority is a
tie-breaker among plugins currently available in a dependency graph: higher values
run first, and equal values retain deterministic discovery order.

Hard plugin dependencies are declared with `PluginDependency`. Its `preprocess` and
`postprocess` fields independently specify where the dependency runs relative to the
declaring plugin:

```python
from engulf_api import DependencyPosition, PluginDependency


PluginDependency(
    "com.example.identity",
    preprocess=DependencyPosition.BEFORE,
    postprocess=DependencyPosition.AFTER,
)
```

Those are the defaults and produce middleware order: identity preprocesses before
audit, while audit postprocesses before identity. Either phase can be `None` to omit
its ordering edge. The dependency remains a hard presence requirement even when both
phases are `None`.

`context_reads` and `context_writes` are `frozenset[str]` declarations enforced by
the runtime. During either active hook, `PluginAPI` provides `get_context`,
`require_context`, and `set_context`. Preprocess hooks additionally receive argument
editing and preemption capabilities through `remove`, `remove_range`, `add`, and
`preempt`. A retained API object cannot be used outside its active hook.

See the Engulf runtime's
[plugin-authoring guide](../engulf/README.md#creating-an-installed-plugin) for a
complete package tree, `pyproject.toml`, implementation, build commands, installation,
and discovery verification.
