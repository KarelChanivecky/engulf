# Executable design models

Back to [delivery](../README.md).

Run from the Engulf workspace with the standard library only:

```console
.venv/bin/python planned-features/plugin-services/delivery/models/check_design.py
```

[check_design.py](check_design.py) is an executable planning artifact, not an Engulf
implementation or an imitation of its runtime test suite. It checks counterexamples
and bounded properties that informed this design:

- an active same-thread ancestor passes generation-only checks but fails a current
  execution-frame check;
- every acyclic directed graph on four labeled participants yields a valid stable
  caller-before-dependency cleanup order, and an edge that closes a path is rejected;
- cleanup continues after failures and preserves the first termination;
- a managed failure latch survives a later success result while preserving outcome;
- a complete immutable inventory larger than one default frame is paged into small
  frames, and later source changes do not change an existing snapshot;
- a failed observation batch never opens the modeled deletion barrier;
- nested budgets cannot extend a parent deadline, and queued-unsent expiry can
  progress while another upstream request is outstanding.

The model uses synthetic records, in-memory state and explicit fake time. It does
**not** prove runtime activation, actual persisted writes, lock release, provider
cleanup, signals, allocation bounds or wire interoperability. Those require the
real [acceptance tests](../verification.md). Its purpose is to reject inconsistent
algorithms before they become a public contract.
