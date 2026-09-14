# Reentrant routing and private child controls

Back to [service runtime](../README.md).

## Request variants

The one generic operation accepts a closed internal base request type. Public
API-only facades create `Describe`, `Resolve` and `LocalCall` values. The optional
host helper creates private `OpenChild`, `ExecuteChild` and `CloseChild` values.
These names describe proposed internal variants, not a commitment to public
constructors in A.

Private control requires `OperationAPI.caller.participant_kind == GOAL`, checked
against runtime-produced facts in the current handler window. A plugin cannot
claim goal authority in its payload or borrow the still-active ancestor goal's
client. Opaque child tokens are bound to the handler/invocation and helper session;
tokens from another invocation are rejected even if their text happens to match.
Wire frames cannot represent control variants, caller identities or scope tokens.

## Scope and caller propagation

```text
handle(request, op_api):
    if private_control(request):
        require actual current goal caller
        if OpenChild: return create_child_scope(grants, host_session_identity)
        if CloseChild: close_scope(resolve_owned_token(request.token), op_api)
        if ExecuteChild:
            scope = resolve_owned_open_token(request.token)
            validate child request against that scope's grants
            with request_context(scope, initiating_origin=CHILD):
                return route(request.business_call, immediate_caller=CHILD, op_api)
    else:
        scope = context_stack.top.scope if nested else invocation_scope
        origin = context_stack.top.origin if nested else actual local caller
        with request_context(scope, origin):
            return route(request, immediate_caller=op_api.caller, op_api)

route(call, caller, op_api):
    validate identity, access, method, request codec and remaining budget
    resolve one canonical provider binding without activating it
    validate service scope state and dependency cycle
    reserve dependency edge and mark provider touched before dispatch
    derive fresh ServiceCallContext(scope, caller, origin, deadline, result_budget)
    replies = op_api.dispatch(CALL, local_event(binding, payload, context),
                              plugin_ids=(provider_id,))
    require exactly one attributed encoded reply from that provider
    check deadline on return; preserve uncertain completion if expired
    return canonical reply
```

The handler is synchronously reentrant: B may request C while the outer handler is
suspended in B's dispatch. Each entry pushes/pops context in `try/finally`; no handler
API is stored in the handler, directory or provider. A fresh window is supplied on
every entry. Immutable scope/deadline data can be retained; callback APIs cannot.

`Describe`/`Resolve` do not add DAG edges or mark providers touched. Service admission
errors before dispatch do not create resource ownership. Core entered/depth/lock
checks occur inside `OperationAPI.dispatch`; the handler has no hidden API for
inspecting core's entered set. Once dispatch is attempted, retaining an edge/touched
entry is conservative even if core rejects before activation. Finalization attempts
an idempotent close; a runtime `target_not_ready` rejection for that exact owner
means it never entered and needs no service close. Other close failures are retained.
Domain failure is not proof that nothing was allocated.

## Wrapper session lifetime

The public `ExecutionSession.step` has no API parameter. The helper therefore stores
a **callback-bound goal operation client** obtained in
`open(event, goal_api, platform_support)`, valid
only during that same `goal.achieve` activation. This is intentional callback-local
retention, not a setup/global capability. `step`, `stop` and `close` run on the goal's
invocation thread; business dispatch occurs only when the goal is the current frame.
Clear the client on session close. The core handler's later finalizer uses its own
fresh `OperationAPI`, not the closed session's retained client.

Platform strategy availability is checked by the helper before it creates a child
scope. Local routing never imports/selects a transport or process strategy, so the
Windows IPC stub does not affect local managed calls.

This detail is necessary: pretending the helper holds only a token leaves it no
sanctioned way to invoke `ExecuteChild` from the fixed `step` signature. Do not solve
that by publishing a free-standing dispatcher callback in shared context.

## Recursive review

| Counterexample | Resolution |
| --- | --- |
| Provider sends `OpenChild` directly through the generic client. | Goal-kind check rejects it before allocation. |
| Provider uses retained goal client during its activation. | Core current-frame check rejects ancestor impersonation. |
| Child adds a `caller` or `scope` field to CALL. | Strict envelope parsing rejects it; host connection supplies origin/token. |
| B calls C while serving a child. | B's access policy, child's scope, inherited nonextendable deadline. |
| Child scope closes while an operation is executing. | Same-thread execution is cooperative; mark revocation when observed, discard replies/queued work, then close after callback returns. |
| Local calls occur after the child has exited. | Invocation scope is still open through `after_goal`; child revocation is scoped. |
| A callback catches a failure from C and returns a domain success. | Core already recorded the defect before the handler regained control. |
