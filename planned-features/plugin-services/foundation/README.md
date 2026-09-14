# A — unavailable foundation

This is an independently complete release. It reserves generic managed-operation
and executable-support contracts, upgrades owned packages and dependency floors,
and leaves the runtime explicitly unable to perform those operations. The user
chose this stop point so the ecosystem rollout can precede commitment to services.

The authoritative proposed definitions live in
[operation contracts](../managed-operations/contracts.md) and
[execution contracts](../executable-support/contracts.md). Only those pages' A
definitions are frozen here. The three optional services packages, capability
schemas, scope routing, concrete OS strategies, child transport, and actual consumer
migrations are B work. A reserves the portable attachment/readiness contracts; B
implements the Unix/Linux strategies and explicit Windows stubs.

## Availability and compatibility

| Surface | A behavior | B behavior, after its tests pass |
| --- | --- | --- |
| `MANAGED_OPERATIONS_API_MAJOR` | `1`, describing definitions | Same definition major |
| `GoalSetupAPI.operation_support` | `OperationSupport(1, False, reason)` | Reports concrete operation implementation |
| `GoalSetupAPI.register_operation` | Checks setup lifetime, then raises `OperationUnavailableError`; stores nothing | Validates and freezes a definition |
| `InvocationAPI.operations` | Concrete legacy fallback; guarded runtime stub | Callback-bound synchronous client |
| `OperationClient.request` | Checks runtime lifetime/thread when using Engulf's facade; raises unavailable | Uses the current execution frame and registered operation |
| `EXECUTION_SUPPORT_API_MAJOR` | `1` | Same definition major |
| `EXECUTION_SUPPORT_IMPLEMENTED` | `False` in wrapper runtime | `True` only after generic fake-helper acceptance |
| `ExecutableWrapperGoal(execution_support=None)` | Existing behavior | Existing blocking path |
| `ExecutableWrapperGoal(execution_support=helper)` | Constructor immediately raises `ExecutionSupportUnavailableError` | Integrates the helper lifecycle |
| Opaque execution resources and `ExecutionPlatformSupport` | Portable definitions only; no strategy selection or resource creation | Strategy supplies binding availability, validates resources and owns native mechanisms |

Definition availability is separate from implementation availability, operation
registration, provider presence, access, and readiness. Do not collapse these into
one `has_services` boolean. Existing third-party API subclasses remain instantiable:
new members on existing ABCs have concrete unsupported defaults, not abstract
requirements. Their fallback cannot promise Engulf's internal activation guards.

All existing plugin catalog groups retain framework major 1 and their existing
goal major. New capability majors are independent. Package versions/floors change
as described in [packaging](../delivery/packaging.md); this documentation task does
not edit versions or publish artifacts.

## Definition freeze gate

1. Freeze names, record fields, exception fields, keyword-only construction and
   ownership/lifetime semantics in the two contract pages.
2. Include the new `OperationCallerKind`/`participant_kind` refinement before A:
   distinguishing an actual goal caller is needed for B's private child controls.
   It is a change to an unpublished proposal, not a retrofit to a released record.
   Include the strategy refinement too: opaque attachments/wait resources and a
   support snapshot replace raw `pass_fds`/`fd` fields. Generic consumers must type
   check using resources with no integer handle or `fileno()` method.
3. Type-check small consumers against definitions using fake interfaces. Assert
   they cannot mistake unsupported registration for success. These are contract
   consumers, not a hidden implementation of managed operations.
4. Exercise old API subclasses and the full existing framework/wrapper/plugin
   behavior with the upgraded package set. Keep help, completion, metadata, and
   repeated invocation unchanged when new surfaces are unused.
5. Complete the owned-package manifest and clean-install checks, then stop. No B
   handler, failure latch, service discovery, socket, or environment mutation is
   needed to complete A.

See [stub pseudocode and review](stubs.md). The residual risk is explicit: publishing
unused interfaces before a real implementation may reveal a later contract change.
The user accepted that tradeoff. The detailed B design and pre-freeze model reviews
reduce it without quietly turning A into a services implementation.

The [goal-side failure-reporting gap](../executable-support/process/README.md#preserving-the-real-outcome-and-the-failure-latch)
remains an A freeze blocker: `GoalResult.error` accepts text, so the withdrawn
exception-valued carrier cannot be used. Resolve and validate its generic reporting
boundary against real API objects before publishing definitions. This is independent
of the user's settled choice to stub Windows IPC behind a strategy.
