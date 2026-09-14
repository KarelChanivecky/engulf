# Critique: Optional plugin service broker

Reviews [plugin-services.md](plugin-services.md) at commit 4bac606. Line references
point at that commit. In this file, `goal.py` means
`engulf-executable-wrapper/src/engulf_executable_wrapper/goal.py`.

Status: open. No finding has been addressed in the plan yet.

## Verdict

The direction is sound and fits the core. A request can already be routed to a
single provider, running under that provider's own callback-bound API, with
`GoalAPI.dispatch(..., plugin_ids=(provider,))`
(`engulf-api/src/engulf_api/plugin_api.py:142-156`,
`engulf/src/engulf/_dispatch.py:243-265`). Provider identity comes from
`AttributedContribution` (`engulf-api/src/engulf_api/goals.py:218-226`). So the claim
that `engulf-api` and `engulf` stay unchanged holds up.

Other choices that hold up:
- The trust statement matches the README's "Execution And Trust" section.
- No listener, no PID-based authorization, and no automatic retry.
- Plugin priority never silently picks a provider.
- Scoping resources with `try`/`finally` rather than relying only on `after_goal`
  is correct: an interrupt raised out of `achieve` skips `run_after`
  (`engulf/src/engulf/application.py:798-831`).

The plan is **not ready to implement**. The wrapper integration, the wire protocol,
and the child-process lifecycle are underspecified, so implementers would have to
make architecture decisions mid-build. One plausible reading of `execution_support`
also breaks repo invariants.

## Blocking — resolve in the plan first

**B1. The boundary between broker and goal is undefined.** "`execution_support` is
defined in the wrapper API and implemented by the broker" has two readings. Both
break something.
- *Reading 1: a live object that the wrapper calls directly.*
  - Plugins can only be reached through endpoint dispatch
    (`engulf/src/engulf/_plugin_execution.py:81-87`, `AGENTS.md:331-336`).
  - Callback APIs fail outside a callback
    (`engulf/src/engulf/_capabilities.py:108-112`). Broker code running there has no
    logger and no API.
  - It can't route requests to providers either: `InvocationAPI` has no `dispatch`,
    only `GoalAPI` does.
- *Reading 2: a collaborator passed to the goal's constructor* (like
  `completion_provider`).
  - An edition can't enable it, because `edition()` can't change `goal_factory`
    (`engulf/src/engulf/application_definition.py:106-133`).
  - It duplicates the plugin adapter, so the two can disagree.
- **Recommendation:**
  - Keep the broker a plugin. Plugin selection is the only thing an edition can
    change, so this is the only way an edition can turn services on.
  - Make every step from goal to broker a wrapper `GoalPhase`, dispatched with
    `plugin_ids=(broker_id,)`.
  - Have the goal route each request with
    `dispatch(SERVICE_CALL, ..., plugin_ids=(provider_id,))`.
  - Let the broker keep its sockets in instance state between phases.
  - Declare contributions that carry descriptors as local-only, as the wrapper
    already does for its registries
    (`engulf-executable-wrapper-api/README.md:510-513`).
  - Allow at most one active broker.

**B2. The wrapper-side contract is under-scoped.**
- Collecting declarations "using existing `GoalPhase` dispatch" needs three wrapper
  changes. The plan names only `execution_support`:
  - a setup phase in `ExecutableWrapperGoal.setup` (`goal.py:317-333`);
  - a provider hook on `ExecutableWrapperPlugin`;
  - a provider-call phase in `achieve`.
- The types those phases use force a new dependency edge. Either wrapper-api depends
  on services-api (for types only), or the types get duplicated as generic ones.
- "Goals publish their capability interfaces" can't hold for a generic wrapper around
  an arbitrary executable. That is the flagship case: the Go child.
- **Recommendation:**
  - List those phases and hooks in the plan.
  - Add the new edge to the dependency diagram (`AGENTS.md:17-23`).
  - Restate ownership: whoever publishes a capability package owns it (a goal, an
    application, or a third party). Each goal decides what it routes; the wrapper
    routes whatever its plugins declare.

**B3. Nobody is assigned to wait for and reap the child.**
- Today the wrapper blocks in `process.wait()` (`goal.py:851-868`).
- If broker code waits or reaps with `os.waitpid`, `Popen` later gets `ECHILD` and
  records exit status 0. Failed children would silently report success.
- **Recommendation:**
  - The wrapper owns the wait loop and the reaping.
  - It multiplexes a child-exit descriptor (`os.pidfd_open`; Linux-only is fine for
    the wrapper) with the broker's readiness descriptors.
  - The broker exposes only a non-blocking step.
  - Framing is incremental and non-blocking, so a descendant holding an inherited
    descriptor mid-frame can't hide the child's exit.

**B4. A broker failure while the child is running is unspecified.**
- The plan covers spawn failure and interrupts, but not a broker or transport
  exception during the wait. Today that would leave the child unreaped and end in
  framework exit 70.
- **Recommendation:**
  - Report a diagnostic attributed to the broker.
  - Close the parent end, so the child sees the connection drop.
  - Continue the ordinary wait with signal forwarding.
  - Keep the exit-code mapping (`engulf-executable-wrapper/README.md:116-125`).
  - A `BaseException` follows the existing `KeyboardInterrupt` path.

**B5. Protocol v1 is missing essentials.** v1 is a cross-language commitment, so gaps
fixed later mean a v2.
- **Request IDs.** Without them:
  - a Go client can't pipeline requests;
  - a proxy can't multiplex several descendants over one upstream connection;
  - a client-side timeout desynchronizes the stream.

  "Fail pending calls" already assumes several calls can be in flight.
- **Handshake.** It should carry:
  - the protocol version (the existing internal protocol versions every message:
    `engulf/src/engulf/_diagnostic_worker.py:74,123`);
  - the negotiated size limit;
  - the connection's grant and defaults. A Go client needs them for `providers()` and
    `require()`, and a proxy needs them to know what it may sub-grant.
- **JSON dialect.**
  - UTF-8.
  - `allow_nan=False`: Python emits `NaN` by default, and Go rejects it.
  - No duplicate keys.
  - Integers stay within ±2^53.
- **Local and remote must agree.** In-process calls should round-trip through the same
  encoder and decoder. Otherwise tuples, non-string keys, and `NaN` pass locally and
  fail across processes.
- **Framing violations.**
  - An oversized length or a malformed frame closes the connection, since
    resynchronizing is impossible.
  - A well-framed but invalid request gets `invalid_request`, and the session
    continues.
- **Recommendation:** add a normative protocol section or spec with shared
  conformance vectors, and say where the Go client and demo live.

**B6. Declared service errors must be returned, not raised.**
- Every exception from a phase callback is logged through `diagnostics.failure` and
  wrapped in `PluginCallbackError` (`engulf/src/engulf/_dispatch.py:230-238`). Raised
  declared errors would therefore show up as plugin failures.
- **Recommendation:**
  - The provider adapter catches declared errors inside the callback and returns them
    in the reply.
  - Only an unexpected `Exception` becomes `provider_failure`.
  - A `BaseException` propagates and ends the session.
  - Define the error envelope: kind, capability, api_major, method, provider_id, code,
    message, data.

## Significant gaps

**S1. Endpoint hygiene.**
- **Problem:** a descriptor number passed through an environment variable goes stale
  for descendants. A services-aware process further down the tree could then write
  frames into an unrelated descriptor.
- **Recommendation:**
  - Put the descriptor *and* the socket's identity in the variable. On Linux that's
    `fstat` `st_dev`/`st_ino`; elsewhere, at least `S_ISSOCK` plus
    `AF_UNIX`/`SOCK_STREAM`. Clients verify it before the first write.
  - Clients and proxies scrub or replace the variable for their own children.
  - A missing or invalid variable means "services unavailable". That also covers
    help mode, where the child starts without preparation or a connection
    (`goal.py:394-404`).
  - Allow only one writer per connection.
  - Document that proxy sub-grants hold only if every intermediate process is
    services-aware.

**S2. The child's base environment.**
- The child inherits the wrapper's environment
  (`engulf-executable-wrapper/README.md:111-112`). `Popen` is given no `env`
  (`goal.py:854`).
- Overlay the additions on `os.environ` at spawn time, not on
  `Invocation.environment`. The latter would start leaking environment-option
  overlays to the child.
- Define collision rules, for example replacing an inherited upstream endpoint
  variable.

**S3. Provider callbacks vs signal forwarding.**
- **Problem:** while requests are being served, signals sent to the wrapper are
  forwarded to the child and don't interrupt the wrapper (`goal.py:188-250`).
  - A blocked provider makes the wrapper uninterruptible.
  - The child can die mid-call, so the reply write fails with `EPIPE`.
- **Recommendation:** keep forwarding, require providers to bound their waits (lease
  timeouts), discard replies to dead peers, and add a test for this.

**S4. Lifetime.**
- Scope services to the direct child. When it exits, stop reading, drop unprocessed
  requests, and close. Descendants that outlive it lose access.
- Leases end with every call: `engulf/src/engulf/plugin_api.py:79-85` force-releases
  them on deactivate.
- Resources that span calls therefore need state plus ownership markers, cleaned up
  in `after_call` or `after_goal`.
- State plainly that providers get no "session closed" hook.

**S5. Default resolution vs editions.**
- **Problem:** "use the sole provider" becomes an ambiguity error in the middle of a
  child run as soon as an edition adds a second provider through `include_plugins`.
- **Recommendation:**
  - Check for ambiguity at setup, right after the directory is frozen.
  - An inactive configured default is a missing-provider error, with no fallback.
  - Say where defaults live and whether an edition can change them.
  - Pin the enumeration order, for example sorted by `plugin_id` rather than by
    priority.

**S6. Who may call.**
- **Problem:** a plugin calling a service re-enters a participant's API. Activating a
  participant that is already active raises `PluginPhaseError` before the attributed
  `try` block (`engulf/src/engulf/_capabilities.py:93-96`,
  `engulf/src/engulf/_dispatch.py:226`), so the error is blamed on the caller.
- **Recommendation:**
  - In v1, the only clients are the goal and the children it launches.
  - If plugin callers are added later, reject self-calls and cycles with a services
    error.
  - Sessions are tied to one thread and become invalid once `achieve` returns.

**S7. Package layering.**
- **Problem:**
  - If the goal-agnostic package also exports the wrapper adapter, every non-wrapper
    goal ends up depending on wrapper-api.
  - A Python client running in the child would drag in the plugin stack.
- **Recommendation:** split it into four layers:
  1. contracts;
  2. goal-side in-process routing, so Python goals need no broker for in-process
     calls;
  3. the cross-process transport and broker plugin;
  4. the wrapper adapter.

  Keep wrapper dependencies and the `engulf` runtime out of layers 1–3, and keep the
  client importable from a child's environment.

**S8. Security framing.**
- Privilege opt-in landed in 4bac606. Holding an endpoint means using in-process
  providers with the application's full authority. In elevated applications, pass an
  endpoint to a child only when the goal opts in for that launch.
- Rename "broker" or disclaim it explicitly. `engulf/README.md:214-216` already
  recommends a separate privilege-separation "broker", which is a different concept.

**S9. Build and CI touch list.**
- `Makefile`: `PACKAGES` and `DIR_...`.
- Root `pyproject.toml`: mypy `mypy_path` and `files`.
- `tests/test_documentation.py`: `DOCUMENTED_PACKAGES`.
- `.github/workflows/ci.yml`, including the Windows core job for the stub and
  portable-import tests.
  - CI's ruff step omits `plugins/`, and its build step omits `engulf-plugin-list`. A
    package placed under `plugins/` would go unlinted in CI.
- The "five distributions" wording and the editable-install line in `AGENTS.md` and
  `README.md`.
- Either a Go toolchain (`actions/setup-go`) or a raw-socket Python client for
  conformance testing.

**S10. Versions.**
- The plan leaves versions unchanged, but it adds public wrapper-api surface and
  changes the wrapper runtime.
- Commit 3eef1dc bumped versions for exactly this reason: the package host rejects
  filenames it already has, and dependency floors must track contracts.
- If wrapper-api 1.2.1 and wrapper 0.3.0 are already published:
  - `execution_support` needs wrapper-api 1.3.0 and wrapper 0.4.0;
  - the adapter's dependency floor must reference those versions.
- `AGENTS.md:35` says "do not bump", which conflicts with that practice. Decide
  explicitly.

## Minor

- Reuse `engulf_api.validate_global_identifier` for capability IDs and method names.
- Capability versions:
  - Let one provider implement several majors of the same capability.
  - Define how the method set evolves within a major (`unsupported_method`).
  - Check for conflicts when providers disagree on a capability's methods.
- "Supported clients end the affected invocation": spell out what a client does
  (report the lost connection, never reconnect) and what a nested Engulf application
  does.
- A nested Engulf application running as a child never merges in upstream providers;
  proxying must be explicit.
- Relate the service codecs to the future goal-owned transport codecs
  (`engulf-api/README.md:279-283`), so the repo doesn't end up with two codec systems.
- The 1 MiB default matches `DiagnosticIsolationConfig.protocol_limit_bytes`
  (`engulf/src/engulf/diagnostic_extensions.py:40`). Say who configures it, and
  advertise it in the handshake.
- Reuse existing test assets:
  - the readiness-file signal harness
    (`engulf-executable-wrapper/tests/test_goal.py:729-814`);
  - `examples/encryption-core` for the Python-goal demo (CI already runs it on
    Windows).
- Coordinate with [goal-owned-cli-parser.md](../../goal-owned-cli-parser.md). Both plans
  extend `ExecutableWrapperGoal.setup` and the wrapper-api surface.

## Suggested revisions by plan section

| Plan section | Findings |
| --- | --- |
| Summary; Packages and public interfaces | B1, B2, S7, S10 |
| Registration and goal integration | B1–B4, S2–S6 |
| RPC, process relationships, and failures | B5, B6, S1, S4 |
| Validation and defaults | S9, S10, minor items |
| New: Security | S8; move the trust bullet here |
