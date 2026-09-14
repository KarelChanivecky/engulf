# Critique synthesis: Optional plugin service broker

Status: reviews consolidated; implementation decisions remain open. This document
does not amend the service plan or mark its findings resolved.

Synthesizes the [service plan](plugin-services.md), the
[original critique](plugin-services-critique.md), and the subsequent review of that
critique against the runtime at commit `4bac606`. Finding IDs such as B1 and S4
refer to the original critique. Corrections and additional findings from the
follow-up review are incorporated below.

## Overall assessment

The proposed service broker fits Engulf's existing dispatch model. Provider
attribution, callback-bound APIs, plugin selection, and managed state can remain
core responsibilities without adding service-specific behavior to `engulf-api` or
`engulf`. Existing invocation dispatch can target one active provider and execute
its callback under that provider's API.

The plan needs a concrete integration contract, process-lifecycle rules, and an
interoperable protocol before implementation. The original critique correctly
identifies these gaps, but some of its remedies are design choices rather than
consequences of existing contracts. Adopt the supported requirements below while
making the remaining choices explicitly.

Retain explicit provider selection, deterministic enumeration, no automatic
retries, private connections, and non-import of unselected plugin implementations.
Preserve the distinction between broker grants and operating-system isolation:
participating goals, plugins, and proxy code remain trusted, and an authorized
participant can forward requests outside the broker's control.

## Integration and selection

- **B1/B2 — Clarify ownership without excluding valid integration patterns.**
  A goal-owned `execution_support` helper can use the goal's active dispatch
  bridge while every actual plugin callback remains behind an execution
  endpoint. Calling such a helper is different from exposing and invoking a live
  plugin implementation. Constructor injection is compatible with editions when
  the base factory already installs optional integration that plugin selection
  activates. Specify who creates the helper, how broker selection activates it,
  and how it avoids retaining callback APIs beyond their lifetime.
- **B1 — Correct the setup-dispatch assumption.**
  `GoalSetupAPI.dispatch()` has no `plugin_ids` parameter. Setup must collect
  immutable declarations through the existing broadcast interface or explicitly
  propose an API extension. `GoalAPI.dispatch()` supports targeting an
  established provider during invocation. The recommendation to target the broker
  in every phase cannot apply unchanged to setup.
- **B2/S7 — Specify an extension contract and dependency graph.**
  Describe the registration, provider-call, execution-session, and cleanup
  interfaces. Service-specific phases and provider adapters can live in the
  optional integration package while wrapper-api defines a service-independent
  execution-support interface. A wrapper-api dependency on services-api is not
  inevitable, nor must service types be duplicated. Keep portable client imports
  separate from wrapper-specific implementation imports, and distinguish module
  boundaries from distribution boundaries. Descriptor-bearing contributions and
  callable dispatch bridges must be described as local-only contracts.
- **B2 — Clarify capability ownership.**
  A goal, application, or third party may publish a capability package. Each goal
  controls which compatible provider interfaces it routes. Specify how wrapper
  plugins expose these interfaces while plugins with no services remain valid.
- **S5 — Preserve multiple-provider use cases.**
  Validate configured defaults during setup; an inactive or incompatible default
  should fail clearly. An unqualified `require()` raises a missing-provider error
  when none is available, or ambiguity when multiple providers remain without a
  configured default. Multiple providers alone must not reject startup: callers
  may enumerate providers or specify `provider_id` on every lookup. Earlier
  resolution is appropriate for requirements explicitly declared by a goal.
  Document default ownership and a stable enumeration order independent of plugin
  priority.
- **S6 — Define supported callers and session lifetime.**
  Restricting v1 callers to goals and their children is a reasonable proposed
  scope, not a consequence that every plugin-to-plugin call is invalid.
  Reentrancy failures concern already-active participants and cycles. State
  thread affinity and session invalidation rules; if plugin callers are included,
  reject self-calls and cycles through an explicit service error rather than
  leaking an activation failure.

Evidence: [dispatch API contracts](../../../engulf-api/src/engulf_api/plugin_api.py),
[phase dispatch](../../../engulf/src/engulf/_dispatch.py),
[activation guards](../../../engulf/src/engulf/_capabilities.py), and
[edition construction](../../../engulf/src/engulf/application_definition.py).

## Process lifecycle and failure handling

- **B3 — Give the wrapper exclusive ownership of child reaping.**
  Broker transport work must not independently consume the child's exit status.
  The wrapper's `Popen` object remains authoritative. Incremental, nonblocking
  transport handling must allow the wait loop to observe child termination even
  when a peer leaves a frame incomplete. `pidfd` is an implementation option;
  adopting it requires an explicit availability and fallback policy.
- **B4 — Separate spawn failures from failures during execution.**
  Narrow the existing spawn-error handlers before adding request pumping. A
  transport `OSError` after successful spawn must not become `SPAWN_FAILED` with
  `process_started=False`. Define diagnostics, connection closure, child reaping,
  and result precedence so broker infrastructure failure cannot silently become
  success when the child exits zero. Preserve framework exit 70 for framework
  failures and conventional child/spawn outcomes when no framework failure occurs.
- **B4/B6 — Preserve termination exceptions.**
  Catch exceptions as needed to release resources and reap the child, but do not
  send every `BaseException` through the existing `KeyboardInterrupt` path. That
  path forwards SIGINT and returns the child's result; applying it to
  `SystemExit` would swallow the original exit request. Preserve termination
  exceptions after cleanup and specify interrupt behavior separately.
- **B6 — Translate declared service errors inside the provider callback.**
  A provider implementation may raise a declared service exception; its adapter
  catches that exception before it escapes phase dispatch and returns a
  structured reply. Unexpected provider exceptions retain plugin attribution and
  become provider failures. Distinguish these from invalid requests, transport
  loss, broker failures, and termination exceptions.
- **S3/S4 — Separate connection cleanup, provider-resource cleanup, and recovery.**
  Closing a transport does not release arbitrary external resources. Per-callback
  leases are released on API deactivation; resources spanning calls need their
  own ownership and lifetime rules. `after_call` and `after_goal` can be skipped,
  so they cannot be the sole cleanup mechanism. The goal–service contract must
  provide exception-safe cleanup and appropriate recovery records. Do not rule
  out a session-close mechanism before resolving those responsibilities.
- **S4 — Define child and descendant lifetime.**
  The proposed wrapper policy ties access to the direct child's execution:
  after it exits, stop accepting work, close the session, and revoke descendant
  access. Specify treatment of queued work and calls already in progress.
  Explain how supported clients report parent-channel loss and end the affected
  invocation without reconnecting or retrying an operation of uncertain outcome.
- **S1/S2 — Preserve descriptor and environment semantics.**
  Validate inherited endpoints before using them, prevent unintended descriptor
  inheritance, serialize writes, and scrub or replace stale endpoint variables.
  Describe missing endpoints in help and other execution modes without services.
  Overlay launch additions on `os.environ` at spawn time so invocation-only
  environment-option values do not newly leak to the child. Define collision
  handling, including inherited upstream endpoint variables in nested processes.
- **S3 — State responsiveness limits.**
  Synchronous provider callbacks run on the thread that pumps requests. Signal
  forwarding alone does not interrupt a blocked callback. Define cooperative
  bounds on provider waits, including lease waits, and handle peers disappearing
  before a response is written. Nonblocking transport does not guarantee
  nonblocking provider execution.

Evidence: [wrapper execution and signal forwarding](../../../engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py),
[outer lifecycle and cleanup](../../../engulf/src/engulf/application.py),
[callback lease release](../../../engulf/src/engulf/plugin_api.py), and
[documented exit semantics](../../../engulf-executable-wrapper/README.md#behavior).

## Protocol and validation

- **B5 — Specify concurrency, ordering, timeouts, discovery, and compatibility.**
  Request IDs and a handshake are useful recommendations, not the only possible
  designs. A proxy can serialize upstream calls; an ordered protocol can
  associate responses without IDs. Choose the supported concurrency model first,
  then define correlation and timeout behavior. Clients need a specified way to
  discover providers, grants, defaults, the protocol version, and effective
  limits, whether through initial exchange or explicit operations. Define how
  each connection's grants are enforced and narrowed by proxies.
- **B5 — Define one JSON and codec contract for local and remote calls.**
  Specify UTF-8, non-finite numbers, duplicate keys, numeric representation,
  request validation, and structured error envelopes. Apply equivalent codec and
  validation semantics locally and remotely, with shared conformance vectors.
  A 53-bit integer limit is a compatibility policy rather than a Python–Go
  requirement: Go's `json.Number` can preserve numeric text and parse `int64`
  values. See [Go JSON number handling](https://pkg.go.dev/encoding/json#Number)
  and [RFC 8259, numbers](https://www.rfc-editor.org/rfc/rfc8259.html#section-6).
  Specify capability and method compatibility within and across API majors,
  including unsupported methods.
- **B5 — Distinguish framing corruption from invalid payloads.**
  Invalid JSON inside an intact length-delimited frame does not inherently
  destroy the next frame boundary. Document when the connection closes and when
  an error reply permits continued use. A close-on-invalid-payload policy can be
  chosen without claiming that recovery is always impossible.
- **Additional finding — Bound aggregate work.**
  The 1 MiB default limits one message, not total outstanding work or memory.
  Define limits for pending requests, connection counts, and buffered responses,
  together with backpressure and scheduling behavior. Bound both reads and
  writes so a busy or stalled peer cannot indefinitely starve child-exit handling
  or other clients.
- **B3–B6/S1–S6 — Test the lifecycle and protocol together.**
  Use deterministic coordination for partial frames, blocked writes, provider
  errors, child exit during a call, broker failure followed by child exit zero,
  `SystemExit` and interrupts, stale descriptors, restricted descendant proxies,
  repeated invocations, and cleanup. Cover multiple providers with explicit
  selection, invalid defaults, and unqualified ambiguity. Preserve wrapper
  signal, terminal, process-group, and environment behavior.
- **S9 — Exercise actual interoperability.**
  Keep the Python-goal and Go-child demonstrations with interchangeable providers.
  Raw-socket Python tests supplement shared vectors but cannot replace the Go
  test. Cover portable local calls, client imports, the Windows transport stub,
  inactive-provider exclusion, and non-import of unselected plugins.

## Scope and follow-up decisions

The integration contract, failure precedence, resource ownership, and protocol
behavior above need resolution before implementation. Treat one active broker,
broker-free local routing, additional distributions, per-launch privilege
authorization, and a provider session-close hook as explicit proposals. Their
tradeoffs must be settled without presenting them as existing requirements.

**S8 — Keep privilege policy precise.** The existing
[goal privilege opt-in](../../../engulf/README.md#elevated-goal-opt-in) authorizes
application construction. Per-launch authorization would add policy beyond that
gate. Holding a service endpoint permits invoking the granted provider operations
with the application's authority; it does not create a sandbox. Keep the term
service broker clearly distinguished from a separate privilege-separation broker.

**S10 — Separate implementation constraints from release verification.** Follow
the [plan](plugin-services.md) and [AGENTS.md](../../../AGENTS.md): start new
distributions at `0.1.0` and leave existing versions and API majors unchanged
during this work. Before releasing, verify published artifacts and dependency
floors against the new interfaces. Historical version bumps identify a release
concern; they do not override the current instruction or prove that particular
version numbers must be chosen now.

**S9 — Carry the build and CI work into the implementation plan.** Update
[Makefile](../../../Makefile), root [typing configuration](../../../pyproject.toml),
[documentation checks](../../../tests/test_documentation.py), and
[CI](../../../.github/workflows/ci.yml) for the eventual package graph. CI currently
omits `plugins/` from Ruff and `engulf-plugin-list` from its builds; explicitly
include relevant plugin packages. Ensure both example packages are installed for
the Python demo. Add a Go toolchain for interoperability coverage, preserve the
Windows core job, update package counts and development installation instructions,
and run the required workspace checks and build/Twine validation for package
changes.

Coordinate wrapper setup and API changes with the
[goal-owned CLI-parser plan](../../goal-owned-cli-parser.md). Reuse existing signal-test
coordination and suitable example assets. Clarify how service codecs relate to
future goal-owned transport codecs without assuming they must become one system.
