# Portable values and codec boundary

Back to [service contracts](../README.md).

## Canonical value domain

The wire value domain is null, booleans, valid Unicode strings, safe integers,
finite binary64 floats, arrays, and string-keyed objects. Apply the same limits
and encode/validate/decode round trip to local business calls.

| Rule | Required behavior |
| --- | --- |
| Integer token | Within `[-(2**53 - 1), 2**53 - 1]`; booleans do not count as integers |
| Floating token | Finite binary64; use decimal/exponent form so an integral-looking float remains distinguishable; preserve signed floating zero |
| Integer `-0` | Normalize to integer zero |
| Unicode | Strict UTF-8, reject unpaired surrogates and invalid sequences |
| Objects | Reject duplicate keys; reject unknown envelope fields; domain unknown-field policy belongs to its versioned codec |
| Complexity | Depth at most 64, at most 65,536 value nodes per message, bounded strings/collections by frame and domain limits |
| Unsupported values | No arbitrary objects, bytes, paths, sets, callables, APIs, exceptions, handles or NaN/Infinity without an explicit domain representation |

Capability API packages define explicit conversions: paths to a documented string
form, image ID sets to sorted arrays, recipes to tagged versioned records, and
acknowledgments to immutable values. Canonical paths are resolved by the owning
domain using invocation context, not by a remote decoder's current directory.
JSON determinism is for reproducibility and conformance, not a signature scheme.

## Catalog and binding ownership

Keep `CodecCatalog` separate from `ServiceDirectory`. The directory contains only
descriptors and attributed IDs. The catalog contains trusted codecs installed by
application code through its capability API imports. This is the one intentional
place for local encode/decode behavior; registrations and wire IDs cannot import
code or install codec callables.

An immutable local `MethodBinding` couples a validated descriptor to its catalog
codecs. A service phase event carries that binding to the owner adapter so result
validation happens before deactivation. The binding captures no invocation state,
provider implementation or runtime API. Only the portable request/response values
cross the child protocol. A future remote execution endpoint must resolve approved
binding IDs at the remote owner; serializing a Python callable is not permitted.

```text
client input
    -> capability request encode
    -> canonical value/size validation
    -> router admission
    -> owner adapter decode
    -> provider method(owner API)
    -> owner adapter result encode/validate
    -> canonical reply
    -> client result decode into fresh immutable records
```

No local fast path may return the provider's mutable object directly. Optimization
may avoid repeated serialization only after conformance proves equivalent
validation, detachment and size accounting. Cache immutable descriptor/binding
lookups, not arbitrary method results or provider object graphs.

## Size budgeting

Business calls use the standard 1 MiB frame-equivalent ceiling locally. Child calls
use their negotiated smaller ceiling. The router computes a result-payload budget
after reserving envelope/error overhead and exposes that value in host context;
providers cannot override it. Domain paging must size actual encoded payloads, not
guess from record count. The [registry snapshot design](../../eclab/lab-registry/snapshots/README.md)
addresses the unbounded inventory currently returned by `records()`.

Do not add directory paging simply because domain inventory paging is useful.
READY describes a bounded setup directory and must fit the negotiated envelope;
oversized configurations fail handshake with a bounded explanation.

## Recursive review and conformance

Python alone is insufficient to validate the claimed wire model. Run actual Python
encoders/decoders and independent Go codecs over shared envelope **and capability**
vectors: safe-integer boundaries, `-0`, `-0.0`, subnormal/finite floats, duplicates,
surrogates, paths, sorted image IDs, every recipe variant, unknown tags, truncation,
nesting and node-count limits. A generic Go JSON parser proves only envelope parsing.

Before the B contract release, verify real accepted recipe/registry fixtures at the
4 KiB receive floor and 1 MiB default. The design does not claim those fixtures have
passed yet. Oversized single registry records require a declared domain error or
an explicitly versioned finer-grained domain API; generic streaming RPC is deferred.
