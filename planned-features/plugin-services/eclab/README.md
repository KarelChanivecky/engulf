# eclab adoption

These are the motivating service consumers, delivered only after functional core,
wrapper-support and local router gates. They do not require child transport. They
replace operational context objects coherently across producers and consumers;
legitimate immutable topology/schema/image-graph data remains under its existing
declared context contract.

| Component | Required outcome |
| --- | --- |
| [Application composition](application/README.md) | One configuration helper used by both goal-construction paths, compatible editions and minimal policies |
| [Lab registry](lab-registry/README.md) | Fresh persisted inventory and acknowledged observation commits in the owner's activation |
| [Consumption](consumption/README.md) | Fresh inventory on every poll; expected failure degrades explicitly |
| [Sleep](sleep/README.md) | Complete inventory and all commit acknowledgments before any Docker deletion |
| [Image providers](image-providers/README.md) | Owner-dispatched offers through the existing resolver lookup seam |

The source layout has evolved since the initial request. Registry code remains in
`plugins/engulf-clab-lab-registry/src/engulf_clab_lab_registry`; consumers now live
in separate `engulf-clab-consumption` and `engulf-clab-sleep` distributions. See
[source evidence](../evidence.md#registry-and-consumers). Re-inventory adapters and
metadata from the working checkout when implementing; do not hard-code a historical
plugin count into migration tooling.

## Shared migration rules

Keep existing plugin IDs, application IDs, state namespace and on-disk record
format unless a domain-specific schema change is separately justified. Service
capability IDs/majors do not move the plugin catalog to major 2. Preserve packaging
dependency edges that establish before-goal/preparation readiness. Provider and
consumer wheels add API dependencies; the application declares functional runtime
floors.

Do not retain a raw-context fallback, direct foreign callback fallback, deferred
registry-write fallback, or a silent "services unavailable means empty inventory"
path. Foundation-era consumers remain unchanged until their coherent B migration.
Once migrated, missing functional services is an installation/configuration failure
before business work.

The primary end-to-end proof is a real managed call from sleep's `before_goal` while
its external lease remains held, causing the registry's own short transaction to
complete, followed by an independent persisted-state read at the first fake Docker
deletion. A queue of mock call events cannot prove this ordering property.
