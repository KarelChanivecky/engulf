# Managed operations

Core supplies a synchronous invocation operation that can dispatch a goal's selected
participants under their own capabilities. It is useful before `goal.achieve`, when
consumption and reclaim already execute. A helper callable installed only inside the
goal would miss those consumers. See [source evidence](../evidence.md#core-contracts-and-dispatch).

| Subcomponent | Responsibility |
| --- | --- |
| [Contracts](contracts.md) | Public API definitions reserved in A |
| [Activation](activation/README.md) | Current frame, generation/thread checks, ancestor lock rules |
| [Dispatch](dispatch/README.md) | Canonical phases, entered targets, execution endpoint, attribution |
| [Lifecycle](lifecycle/README.md) | Factories, nested calls, failure accumulation and exhaustive finalization |

Implementation belongs in `engulf-api`, `engulf._dispatch`, `engulf._capabilities`
and Application's invocation resource wiring. A small internal operation coordinator
may have its own module; it must not duplicate plugin traversal or expose live
implementations. `RuntimePluginAPI` remains the facade. Generic core imports no
service, wrapper, socket or POSIX-specific execution code.

## Interaction

```text
setup.register_operation(definition)      # goal-owned, frozen after setup
Application.invoke(invocation):
    coordinator = new per-invocation coordinator(frozen definitions)
    handlers = coordinator.create_handlers(invocation)
    run existing before_goal traversal   # operation clients already usable
    run goal if not preempted
    run entered after_goal traversal
    finally:
        close every created handler
        finalize every queued workspace destruction
        close every participant/goal API
        preserve termination, else apply actual managed/cleanup failure

api_A.operations.request(id, request):
    validate callback ownership and request
    enter fresh handler window
    handler.handle(request, operation_api)
        operation_api.dispatch(canonical_phase, event, plugin_ids=(B,))
            activate B; endpoint.dispatch_phase(..., api_B); deactivate B
    validate response; leave handler window; resume A
```

This does not expose `GoalAPI.dispatch` to every plugin. Each operation has its own
phase allowlist, request/response classes, handler instance and failure attribution.
The service router is one possible operation handler.

## Review conclusions

The generation-only guard fails for active ancestors; the activation page adds the
current-frame guard. A phase ID alone is not an adapter allowlist; the dispatch page
freezes exact phase objects. A `finally: deactivate()` can hide the provider's
exception; the lifecycle page captures outcomes before cleanup. All three changes
are needed before reporting functional support.

Multiple operation handlers do not imply a second generic resource-dependency
framework. Handlers close in reverse construction order; cross-operation resource
dependencies are unsupported. During core finalization only nested requests to
the operation currently closing may proceed. Services intentionally use one handler
to own their complete dependency graph. This keeps generic cleanup predictable
without making core understand service scopes.
