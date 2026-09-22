# Managed sudo: design review and feasibility

Status: planning continued on 2026-09-18. Runtime implementation has not started.
Limited unprivileged smoke-test evidence is recorded below. No sudo helper, host
privileged operation, or complete containment profile has been tested.

Back to the [feature plan](managed-sudo-access.md).

## Scope of the next work

Keep the proposed initial product limited to reviewed operations with exact command
previews. An arbitrary-command interface can enforce consent to a top-level root
launch, but cannot also promise to bound all behavior of that approved program.
These are different guarantees and need different acceptance criteria.

The next implementation slice should establish isolated discovery and endpoint
execution using a minimal reference goal. Follow it with a fixed, non-mutating
privilege probe in a disposable VM. A bridge operation remains an illustrative
product use case; it needs separate ownership and recovery design before adoption.
Do not begin with a generic sudo runner and infer containment from its successful
command tests.

## Findings and proposed resolutions

These are design corrections, not implemented security fixes.

| ID | Counterexample | Resolution / gate |
| --- | --- | --- |
| MS01 | A caller supplies a known application/plugin ID on a private socket. | IDs do not authenticate packages. Freeze application configuration in the trusted launcher and bind each worker endpoint to one selected descriptor; reject identity fields from worker payloads. Verify the helper bootstrap separately. G-IDENTITY. |
| MS02 | A sandboxed plugin asks a host API to read a secret, write executable configuration, or launch code for it. | Review all delegated capabilities, including state, goal phases, completion, and services. A safe syscall profile cannot make an unrestricted host API safe. G-CAPABILITIES. |
| MS03 | Plugin code or a `.pth` hook executes before the worker sandbox exists. | Keep untrusted installations outside the coordinator's import environment; split catalog selection from materialization. Test startup and factory side effects as well as callbacks. G-IMPORT. |
| MS04 | A child inherits the plugin channel, changes session, or forks after its parent exits. | Attribute channel holders to the same worker scope; enforce quotas and revocation at the host. Supervise all descendants independently of process-group membership. G-TREE. |
| MS05 | Cancel and approve cross in transit, or the helper crashes after launching but before replying. | Use a helper-owned state machine with durable approval consumption. Report unknown completion, never automatically execute the request again. G-COMMIT. |
| MS06 | A retained client sends a valid request during analysis, setup, or another invocation. | Host-owned current callback, invocation generation, and operation grants control admission. The worker never chooses its phase. G-LIFETIME. |
| MS07 | A file is hashed, then reopened after the worker changes it; or an open inode is modified in place. | Use protected immutable/staged inputs and trusted executables. Descriptor or hash checks alone are insufficient. Initial fixture has no input files. G-INPUTS. |
| MS08 | Worker output imitates an approval prompt or the privileged child inherits the helper protocol fd. | Separate output, protocol, and terminal roles; pause/buffer bounded worker output during consent. Every child gets only explicitly assigned descriptors. G-UI. |
| MS09 | Cleanup deletes a different bridge that reused the old resource name. | No generic name-based cleanup grant. Require domain-specific identity, precondition, and recovery guarantees; omit mutating operations until established. G-RESOURCE. |
| MS10 | Namespace creation succeeds, so the application silently assumes the complete backend is available. | Probe all required facilities and deployment assumptions before importing plugins. Partial support produces unavailable, with no local-execution fallback. G-PREFLIGHT. |

UNIX peer credentials report OS identity at connection/socketpair creation; they
do not attest installed application code. Descriptor passing can transfer access
to a channel. The proposed worker identity therefore follows its protected launch
and endpoint ownership, not a claimed ID or peer UID alone.
[Linux UNIX-domain socket documentation](https://man7.org/linux/man-pages/man7/unix.7.html)

## Trusted bootstrap and delegated authority

The coordinator remains trusted and unprivileged. Its installed Python environment,
configuration, goal implementation, and transport codecs must not be writable by
workers or load their startup hooks. Untrusted plugin trees are mounted read-only
only into the appropriate worker. Malicious code in an independent, unsandboxed
process under the desktop user's account remains outside the initial threat model.

The coordinator selects one installed helper profile from its trusted configuration.
The worker cannot choose a helper executable, policy file, application ID, cwd,
environment, or interpreter. The privileged helper independently loads and validates
its administrator-installed operation catalog. Plugin declarations can request
capabilities but cannot extend that catalog or confer trust.

Prototype the helper bootstrap with a fixed absolute sudo/helper command and
dedicated protocol stdin/stdout. Keep authentication and consent input on a
coordinator-owned terminal path; give plugins no terminal handles. The bootstrap
gate must cover sudo's fd closing, optional I/O mediation, authentication failure,
credential caching, and signal behavior. Do not assume arbitrary descriptors survive
sudo, and do not use `sudo -S`, worker-provided askpass, or inherited environment
preservation as shortcuts. The final protected channel and profile binding must be
verified before treating the helper as usable. The [upstream sudo manual](https://github.com/sudo-project/sudo/blob/main/docs/sudo.man.in)
describes the authentication and descriptor behavior to exercise.

The helper trusts the coordinator's attribution only within this protected session.
It does not independently authenticate a Python plugin from serialized metadata.
Supporting hostile unsandboxed callers would require a further identity/approval
design; a socket token or matching UID does not add that guarantee.

The first reference goal needs only fixed request/result values and attributed
logging. Reject unsupported state/context/registration features explicitly in that
experimental profile. Later capability projections must satisfy these rules:

- State access uses host-issued store identities bound to the current worker and
  invocation. Filenames remain single components; owner-private, link/reparse,
  locking, and atomic-write protections stay in the host runtime. No payload may
  select a state root, owner home, participant, or arbitrary absolute path.
- Existing `StateStore.directory` and `path()` return local filesystem paths.
  A worker cannot use the host pathname as a portable capability. Define a private
  mounted view or a distinct data contract before supporting such plugins; reject
  them meanwhile. Do not silently change existing in-process semantics.
- Context and phase values use fixed trusted codecs, with bounded schemas and no
  imported constructors selected by the message. Service providers and goal code
  validate requests before touching host resources or executing commands.
- Each request is checked against the current host-owned callback and the admitted
  operation set. Callback teardown revokes outstanding uncommitted work. A child
  holding the worker channel gets no additional identity or grants.
- Worker-provided output remains untrusted data even when forwarded by a trusted
  component. Do not execute worker-generated shell completion or interpret returned
  files as coordinator configuration.

These restrictions are an explicit experimental remote profile, not a claim that
all existing `InvocationAPI` or wrapper plugins are remotely compatible.

## Request state machine

The following names describe private protocol semantics; they are not frozen public
API types. Use one bounded request at a time per worker and one serialized approval
prompt per application initially.

| State | Meaning | Permitted next steps |
| --- | --- | --- |
| RECEIVED | Host admitted an operation request from the current worker callback. | Reject or obtain a helper-generated plan. No command may run. |
| PLANNED | Helper retains the immutable plan and expiry; coordinator may show it. | Deny, expire, invalidate, cancel, or commit that exact plan. |
| CONSUMED | Helper durably recorded that this approval/request has been used. | Attempt launch once, record a known launch failure, or retain unknown completion after failure. Never return to PLANNED. |
| STARTED | Helper confirmed launch of the approved executable. | Observe completion or supervise cancellation/timeout; retain uncertainty if observation is lost. |
| FINISHED | A terminal outcome and evidence were recorded. | Read the result. No replay or side effect from status queries. |
| CLOSED_UNSTARTED | Denied, expired, cancelled, or invalidated before consumption. | Read the disposition. A new action requires a new request and approval. |
| UNKNOWN | Evidence cannot establish whether launch/effects completed. | Reconcile from the protected journal or perform a separately authorized recovery action. No automatic retry. |

The host adds worker identity, invocation generation, and allowed phase; the worker
sends only the operation and typed parameters. The helper issues the plan/execution
ID and computes the canonical plan. Approval references that ID and canonical
digest on the protected coordinator channel. The digest is not an authorization
credential. Changing parameters, effective policy, executable, credentials, inputs,
environment, cwd, or permitted cleanup invalidates approval.

Before consuming approval, the coordinator checks that the worker callback is still
admitted and the helper checks its plan, policy, and preconditions. Use one
authoritative transition for commit versus cancellation. A cancellation processed
before consumption prevents launch. Once consumption wins the race, cancellation
is best effort until the helper has observed and recorded the outcome; do not
respond "denied, no work done" simply because the UI closed.

Record intent durably before launch. A crash between that record and the actual
system call can leave an UNKNOWN request even when no process ran. Prefer that
honest uncertainty over a duplicate privileged action. At-most-once launch per
consumed request does not mean exactly-once external effects or idempotence across
new requests. Reconnection never resubmits a consumed request. Recovery reads
must check their caller/profile and must not execute as a side effect.

The initial wire format should have a version, fixed message kinds, request IDs,
and strict length-prefixed UTF-8 JSON, with a maximum 64 KiB frame, bounded nesting
and collection sizes, no duplicate keys, nonfinite numbers, or unrecognized fields.
Validate the length before allocating or parsing. Keep one outstanding plan per
worker, explicit absolute deadlines, and bounded result/output retention. Freeze
the exact limits and serialization vectors with the implementation fixture; these
are proposed ceilings rather than a published general command protocol.

## Descendant and resource supervision

The initial Linux profile requires a delegated cgroup v2 subtree with usable pids
and memory controllers and `cgroup.kill`. The trusted launcher establishes the
worker group and limits before untrusted code starts. Its controls and migration
targets are neither mounted nor passed into workers. A trusted supervisor outside
the group observes lifecycle and kills the entire group when the scope ends.

Test supervisor failure as well as worker failure: a separately owned watchdog or
service scope must close admission and terminate abandoned groups. Reject a host
where only process-group termination is available. The Linux kernel documents
whole-subtree termination and concurrent-fork handling for `cgroup.kill`;
parent-death signals are cleared in forked children and alone do not cover a tree.
[Kernel cgroup v2 documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html),
[Linux parent-death signal documentation](https://man7.org/linux/man-pages/man2/PR_SET_PDEATHSIG.2const.html)

Do not claim a cgroup revokes all possible authority of an arbitrary root program.
Privileged children need their own reviewed capability, filesystem, syscall, fd,
and supervision profile. Unrestricted root commands can interfere with controls or
delegate work elsewhere; that behavior is excluded from the initial operation set.
Killing a tree also cannot undo a service request or filesystem/network mutation
that already reached the host.

For future resource operations, user-state leases coordinate cooperating clients,
while a worker-inaccessible helper journal records authoritative intent and effects.
Resource names and user-writable ownership markers alone cannot prove identity.
The operation must specify which external races it can tolerate and an atomic or
otherwise justified identity check at the action boundary. If that cannot be
established, it cannot promise safe automatic deletion. A separate recovery request
must revalidate ownership and obtain the required consent.

## First end-to-end fixture

Use a private test operation, `org.engulf.test.privilege.identity`, with no parameters.
Its installed manifest fixes a trusted `/usr/bin/id -u` executable/argv, root target,
cwd `/`, closed stdin, minimal explicit environment, bounded output, and a short
deadline. Adapt the manifest to the VM's trusted binary location at installation;
the worker cannot supply or change that path. Display exactly that invocation.

The fixture proves only privileged execution and consent plumbing. It creates no
bridge, files, services, persistent permissions, or cleanup grant. Do not ship it as
a generally useful operation or treat its success as resource-recovery coverage.

The VM scenario has two plugins with separate workers. Only one has the fixture
grant. Both can try the operation; the ungranted request is rejected without a
prompt. The admitted request shows the canonical plan and runs only after consent.
Replay, a forged plugin identity, a changed argument, a stale callback, and an
attempt to call sudo directly must not produce a privileged execution.

Establish the negative-control evidence too: the same installed sudo fixture works
under the VM's intentionally configured host policy outside the restricted worker.
Otherwise a failing worker sudo call could merely mean sudo was unavailable or
credentials were missing. Assert host privilege in the result; UID 0 inside a
worker's user namespace is insufficient evidence. No such privileged scenario was
executed during this planning work.

## Source changes and acceptance gates

| Slice | Owning source and concrete change | Acceptance gate |
| --- | --- | --- |
| 1. Execution policy and preflight | `engulf` plus an optional Linux backend: choose the explicit restricted profile before loading plugin targets. Probe required isolation, delegated controllers, and trusted installation. | G-PREFLIGHT: every missing facility fails before import, while ordinary applications retain their existing behavior. |
| 2. Selection versus materialization | [`plugin_loader.py`](../engulf/src/engulf/plugin_loader.py): preserve the application-scoped entry-point snapshot, selection/dependency rules, and provenance while moving imports, factories, and metadata evaluation into admitted workers. | G-IMPORT: malicious startup/import/factory fixtures cannot affect the parent; unselected targets remain unimported. Check goal/plugin runtime types inside the worker without treating that check as trust. |
| 3. Endpoint and capability projection | [`_plugin_execution.py`](../engulf/src/engulf/_plugin_execution.py), [`_dispatch.py`](../engulf/src/engulf/_dispatch.py), and capability collaborators: transport explicitly registered reference-goal values and preserve attribution and lifetime. | G-IDENTITY, G-CAPABILITIES, G-LIFETIME: forged routing, foreign stores, retained clients, and unsupported codecs fail with no extra authority. |
| 4. Worker supervision | Linux backend: private namespaces, restricted mounts/fds/syscalls, delegated process limits, and exhaustive cleanup. | G-TREE: double-fork/session changes, resource exhaustion, worker/supervisor failure, and repeated invocation leave no admitted descendants or live grants. |
| 5. Privilege and consent fixture | Separately installed helper and trusted coordinator adapter: fixed profile bootstrap, canonical plan, protected terminal, durable request transitions, and identity operation. | G-UI, G-COMMIT, G-INPUTS: positive/negative VM controls, denial, replay, mutation, interruption, authentication variants, and unknown completion have the stated effects. |
| 6. First product operation | Owning domain API/helper implementation: specify required effects, inputs, leases, ownership, and recovery before adding a bridge/service operation. | G-RESOURCE: concurrent replacement and recovery cannot target an unapproved object. A real consuming application and narrowed operation schema are required. |

Keep the minimal goal separate from executable-wrapper migration. The wrapper's
mutable registration objects and inherited controlling terminal/process group need
an explicit compatible remote form; changing them incidentally to make the fixture
pass would change the existing goal contract.

No framework/API version bump or public name freeze is needed for this design work.
Read the owning package README before each implementation slice. Generic API/core
changes require the contract/runtime tests mandated by `AGENTS.md`; Linux execution
details stay in the optional strategy/backend, and wrappers remain outside core.
Run the full required workspace checks and packaging builds where applicable.

## Local feasibility evidence

Observed on 2026-09-18 in this restricted tool session:

| Probe | Observation | What it establishes |
| --- | --- | --- |
| Tool/process inspection | Bubblewrap 0.9.0, util-linux unshare 2.39.3; current process already had `NoNewPrivs: 1`, seccomp mode 2, and zero effective/permitted/ambient capabilities. | These tools exist in this session; it is not an unrestricted coordinator environment. |
| Disposable user/network/PID namespace command | `/usr/bin/unshare --user --map-root-user --net --pid --fork /usr/bin/true` exited 0. | Those namespace creation operations succeeded under this session's restrictions. |
| Bubblewrap requesting its own network namespace | Rejected while opening a NETLINK_ROUTE socket to configure loopback; the trusted probe body did not run. | This particular setup path is unavailable here; do not drop network isolation as a fallback. |
| Existing diagnostic-style namespace arrangement | An outer unshare created the private user/network namespace, then Bubblewrap isolated user/PID/IPC/UTS/cgroup namespaces and mounts, dropped capabilities, disabled nested user namespaces, and ran a trusted read-only Python probe. Exit 0. | A restricted process can start using the arrangement already present in [`diagnostic_extensions.py`](../engulf/src/engulf/diagnostic_extensions.py). |
| Worker observation in that arrangement | `NoNewPrivs: 1`, zero effective/permitted/ambient capabilities; no `/home`, `/run`, or `/sys`; private empty `/tmp`; environment contained only `LC_ALL=C` and Bubblewrap's `PWD=/tmp`. | Those specific observations held. No plugin, helper, root command, or hostile workload ran. |
| cgroup controller listing | The host view lists memory and pids controllers, among others. | Listing support does not prove delegation, enforceable limits, watchdog ownership, or tree cleanup. Those were not tested. |

The successful smoke command used read-only `/usr` and available loader directories,
private `/proc`, minimal `/dev`, and private `/tmp`, plus a new session and closed
stdin. It intentionally ran only trusted inspection code. It did not install or
validate the proposed per-worker seccomp filter, authenticate a broker channel,
exercise cgroup management, or expose real plugin APIs.

Because the parent already had `no_new_privs` set, the smoke result does not prove
that a future launcher sets it correctly from an unrestricted state. The VM gate
must show an unprivileged coordinator with the flag clear and restricted workers
with it set. The flag cannot be cleared by descendants, so this session cannot
exercise the sudo-capable coordinator/helper path.
[Kernel no-new-privileges documentation](https://docs.kernel.org/userspace-api/no_new_privs.html)

Feasibility remains partial. The smoke evidence supports continuing with slice 1;
it does not pass G-PREFLIGHT or any containment release gate.
