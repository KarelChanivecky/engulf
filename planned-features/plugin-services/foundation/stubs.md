# Stub behavior and adversarial review

Back to [foundation](README.md).

## Pseudocode

```text
legacy GoalSetupAPI.operation_support:
    return unavailable_support("custom API has no managed operations")

legacy GoalSetupAPI.register_operation(definition):
    raise OperationUnavailableError(feature="managed operations", reason=...)

runtime setup.operation_support:
    require_setup_window()
    return unavailable_support("this Engulf release provides definitions only")

runtime setup.register_operation(definition):
    require_setup_window()
    raise OperationUnavailableError(...)       # no registry, no factory call

runtime invocation_api.operations:
    require_active_callback()
    require_current_thread(runtime_recorded_callback_owner_thread)
    return StubClient(activation, captured_generation, owner_thread)

StubClient.support / StubClient.request(...):
    activation.require_current(captured_generation)
    require_current_thread(owner_thread)
    if querying support: return unavailable_support(...)
    raise OperationUnavailableError(...)       # no provider lookup or dispatch

ExecutableWrapperGoal(..., execution_support=None):
    if execution_support is not None:
        raise ExecutionSupportUnavailableError(...)
    initialize_existing_goal(...)
```

The stub checks lifetime before reporting unavailability so stale-client misuse is
not confused with a missing feature. It does not perform B's nested stack checks:
there is no nested managed execution to authorize. The **contract** already says
the functional client will require the current execution frame.
Record the owner thread when runtime enters the callback, not when someone reads
`.operations`; otherwise a worker handed a live API could mint its own valid client.

The opaque execution resource definitions and platform-support record add no A
runtime behavior. Reject supplied support before selecting an OS strategy or
accessing an attachment. A's unavailable generic implementation and B's unavailable
Windows strategy are different stop points: B supports local managed calls on
Windows while its child IPC operations still raise.

## Review

| Counterexample | Decision | Acceptance evidence |
| --- | --- | --- |
| A custom `InvocationAPI` subclass implements only today's abstract methods. | Supply concrete unsupported defaults on existing ABCs. | Instantiate the old subclass unchanged; access new members predictably fails/reports unsupported. |
| A consumer ignores the support probe and registers a handler. | Registration raises; never acknowledge an unused handler. | A counting factory and dispatch spy both remain untouched. |
| A helper's constructor argument has side-effecting properties. | Reject non-`None` before reading properties, calling `setup`, or preparing a process. | Helper spies show no calls for normal/help/completion modes. |
| A reserves `pass_fds` as a universal launch field and later Windows needs another mechanism. | Freeze opaque attachments/wait resources and an availability snapshot instead; native subtypes belong to B adapters. | Non-fd fake consumers type check; A never imports or constructs a native strategy. |
| A consumer retains a runtime stub across callbacks or moves it to a worker. | Apply captured generation and thread guards even though work is unavailable. | Same callback succeeds in probing; later callback/worker fails lifetime checks. |
| A package advertises services because it imports the new names. | B bootstrap checks concrete availability and functional runtime floors. | A B consumer on an A runtime fails before provider business work. |
| To make a stub demonstration useful, a local callable fallback is added. | Reject this addition: it would create another foreign-owner execution path. | No handler storage, fallback callbacks, state writes, or sockets in the A diff. |

## Scope of release work

New API records can validate their own values without activating runtime behavior.
Keep generic `GoalPhase` semantics and `PluginCallbackError` fields unchanged.
Do not change old context users during A. Source and package changes needed for
working services belong to B even when they are easy to implement alongside a stub.
