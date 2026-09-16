# Child environment and completion

Back to [executable support](../README.md).

## Environment construction

```text
child_environment = fresh copy of os.environ
for name in frozen support.environment_removals:
    child_environment.pop(name, None)
if session exists:
    child_environment.update(validated session.launch.environment)
owned_launch = strategy.prepare_launch(snapshot_launch, session_owner)
strategy.spawn(resolved_call, child_environment, owned_launch)
```

Do not forward the whole normalized `Invocation.environment`. It includes callback
option overlays that the existing wrapper consumes internally. Launch additions
are explicit and immutable. Scrub helper-owned names even when transport is absent
and `open` returns `None`. An installed services helper owns
`ENGULF_SERVICES_ENDPOINT`; it replaces it only for its intended direct child.

Without a helper, preserve the current environment behavior. A stale endpoint string
alone grants nothing: the selected client strategy validates endpoint identity and
ownership before using it, and native launch strategies restrict inheritance.
No mutation of the user's interactive shell or parent `os.environ` is needed.

## Resource ownership

The transport strategy creates an owned endpoint pair. The helper supplies opaque
launch attachments; only the corresponding execution strategy translates them to
native inheritance settings. Release the redundant host copy after spawn, and all
resources if spawn never completes. The wrapper retains shared idempotent cleanup
records so helper failure cannot leak an attachment or cause double closure.
The execution strategy verifies session-owned allocation records before translating
attachments. The Unix `pass_fds` set must be a subset of that session's live owned
descriptors, never merely a tuple of well-formed live integers. W-ENV rejects an
unrelated open descriptor, including a state/lease lock, before spawn.

The [Unix strategy](../../transport/strategies/posix/README.md) owns `pass_fds`,
non-inheritable sockets, device/inode checks and reused-fd protection. Windows has
an unavailable strategy with no inheritance changes. Generic environment code
only scrubs helper-owned names and adds the strategy-produced bounded bootstrap.
Native resource data never enters service payloads or capability descriptors.

## Completion integration

Carry removal metadata through completion description/rendering and the executable
bootstrap paths. Completion probes do not allocate a service session. Native
completion remains an explicit opt-in and runs only the trusted wrapped binary's
documented completion command, with the Linux strategy's existing restricted
descriptor inheritance and a scrubbed endpoint value.
Preserve existing shell completers, empty-word handling and shell-free execution.

Test an inherited stale endpoint, helper installed without broker, a live intended
child endpoint, normalized invocation-only options, bootstrap completion, all
supported rendered shell paths, and unrelated fd reuse. An integration test should
inspect the actual child environment/fd set, not just a fabricated launch mapping.
