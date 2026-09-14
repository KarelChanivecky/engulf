# Canonical phase and endpoint dispatch

Back to [managed operations](../README.md).

## Registration and readiness

Freeze operation definitions at the end of goal setup. Build a lookup by operation
ID and, within each definition, phase ID → **canonical phase object**. Reject duplicate
operation IDs and duplicate phase IDs within a definition. A request supplies no
callback. If `OperationAPI.dispatch` receives another phase object with the same
ID, reject it; never execute a replacement object's `local_callback`.
Across operation definitions, reusing a phase ID is allowed only for the same
canonical object; different callbacks cannot claim one future dispatch identity.

`GoalPhase` has no runtime setup/invocation kind field. Its generic annotation is
not inspectable compatibility metadata. A's constructor validates values; B's
bridge supplies an invocation API and only supports invocation adapters. A
misdeclared adapter fails through normal attributed dispatch. Do not change the
existing `GoalPhase` constructor just to infer annotations.

Core knows three target facts: selected, currently active, and successfully entered
through `before_goal`. Services adds descriptor registration and method readiness.
An entered provider stays eligible through `after_goal` and operation finalization;
service-owned resources must not disappear merely because its outer hook ran.
A provider still executing `before_goal` is not entered and is an active ancestor;
it cannot be called recursively. Preserve packaging order for early consumers.

## Pseudocode

```text
operation_dispatch(window, supplied_phase, event, targets):
    require_current_handler_window(window)
    canonical = window.definition.phases_by_id.get(supplied_phase.phase_id)
    if canonical is not supplied_phase: reject invalid_request
    validate targets: nonempty, unique, selected, entered, not active ancestors
    validate invocation stack locks and managed depth
    return existing_phase_dispatcher.dispatch_invocation(
        canonical, event, plugin_ids=targets, managed_context=window
    )

call_service_adapter(plugin, event, owner_api):
    reply = plugin.call_service(event, owner_api)
    require exact ServiceReply variant and matching method/result contract
    # None is a defect here, although generic GoalPhase contributions may omit it.
    return reply

close_service_adapter(plugin, event, owner_api):
    plugin.close_service_scope(event, owner_api)
    return explicit close acknowledgment
```

Adapters remain module-level forwarding/contract-validation functions. Directory
selection, scope graphs and business routing stay out of them. The endpoint still
owns access to the live implementation. No helper receives a `LoadedPlugin` or
calls a registered provider object.

## Attribution and failure handling

Validate provider replies while its activation is open so a bad return is attributed
to the owner. Local result codec validation must also be inside that owner adapter;
the handler can round-trip the validated payload afterward. A typed method's
explicit `NoOpinion` is valid data; a missing contribution is not.

On an ordinary endpoint or return-validation defect, construct/preserve the owner's
`PluginCallbackError`, create one `OperationFailure`, and record it in core **before**
returning control to the optional handler. A handler cannot turn a caught provider
defect into an unlatched domain success. If an inner operation already carries C's
failure through B, do not wrap it as B, then A. Preserve identity/origin and add
diagnostic traversal information without inventing a new originating provider.

Activation, deactivation and endpoint infrastructure defects may have no provider
callback origin. Record them honestly as managed infrastructure failures; do not
forge a `PluginCallbackError` merely to fill a field. Termination is never wrapped.

## Review

Test exact phase identity, unselected IDs, duplicate targets, a provider not yet
entered, an adapter returning `None`, a wrong response type, C failing beneath B/A,
and deactivation failing after a provider error. Verify the unselected plugin was
never imported and every callback reached the execution endpoint. Targeted cleanup
dispatch must attempt each provider separately so a termination exception cannot
prevent the remaining callbacks from being attempted.
