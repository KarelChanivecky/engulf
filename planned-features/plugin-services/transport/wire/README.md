# Wire protocol v1 design

Back to [transport](../README.md). Field spellings here are the proposed B protocol
baseline and must be frozen with executable Python/Go vectors before publication.

## Framing and negotiation

Each message is a four-byte unsigned network-order payload length followed by strict
UTF-8 JSON. Zero length and lengths above the current receive bound are rejected
before allocating the advertised body. Bootstrap HELLO is limited to 4 KiB.
Minimum supported receive capacity is 4 KiB; standard maximum is 1 MiB.

```json
{"type":"hello","protocol_major":1,"max_receive_bytes":1048576}
```

The host answers READY with `protocol_major`, `max_request_bytes`,
`max_response_bytes`, and `providers`, in addition to `type: "ready"`. The request
bound is the host's permitted receive bound; the response bound is the minimum of
host send policy and child's advertised capacity. READY itself must fit that
response bound. Descriptors contain only granted IDs, accepted method identities,
codec versions and necessary public capability metadata, never Python import paths.

Serialize real directory fixtures at the 4 KiB floor and 1 MiB default. Reject an
unadvertisable directory with a bounded handshake error and close. Directory paging
is deferred until evidence requires it; registry data paging is a separate domain
contract. A handshake error has no request ID. A duplicate HELLO or CALL before
READY is a protocol error.

## Calls and replies

```json
{"type":"call","id":1,"capability":"org.example.inventory","major":1,"provider":"org.example.registry","method":"read_page","remaining_timeout_ms":30000,"payload":{}}
```

```json
{"type":"result","id":1,"payload":{"records":[],"next_cursor":null}}
```

```json
{"type":"error","id":1,"kind":"domain","code":"inventory_unavailable","message":"Inventory could not be read."}
```

Each envelope has an exact allowed field set. A CALL cannot contain a caller, scope,
endpoint, codec import target, private control request or grant override. Each
connection permits one outstanding CALL and strictly increasing positive safe
integer IDs. Keep only the last accepted ID, not an ever-growing history. Reject
reuse/out-of-order responses; close before ID exhaustion rather than wrap. No
notifications, remote callbacks, batching, cancellation, automatic retry or reconnect
are defined in v1.

`remaining_timeout_ms` is a positive integer no greater than 86,400,000. The host
clamps it to application policy, initially 30 seconds, and to any inherited budget.
The 24-hour ceiling is validation, not permission or a promise about execution.

## Closed error-kind taxonomy

| `kind` | Code ownership and behavior |
| --- | --- |
| `request` | Services admission: denied/missing/ambiguous/not-ready/unsupported/invalid request, scope cycle/depth, lock order, deadline before dispatch, resource exhaustion. Recoverable when a correlated response can be sent. |
| `domain` | Codes declared by the capability. Recoverable; no framework latch. |
| `provider` | Owner callback/return defect. Host records the original managed failure; return a bounded safe explanation if the channel is viable. |
| `infrastructure` | Internal host/router/transport failure. Latch host failure and revoke when the channel cannot remain sound. |
| `protocol` | Malformed framing/JSON/envelope/order. Close the faulty peer; peer misuse itself does not latch a host framework defect. |

An error can include a request ID only if a valid ID was parsed reliably. Do not
invent ID 0 for malformed input. Detailed tracebacks/payloads remain host diagnostics;
wire messages have bounded safe text and only metadata visible to that caller.

Channel disappearance, absent endpoint and uncertain completion are typed **client**
errors, not synthetic replies received from a server. A validated correlated
`deadline_exceeded` before dispatch is known not started; disappearance/expiry after
transmission begins without such a reply is conservatively outcome-unknown.

## Recursive review

Test duplicate JSON keys, UTF-8 errors, unknown fields, bad numeric forms, zero/huge
lengths, partial headers/bodies, unexpected reply IDs, CALL before READY, multiple
outstanding calls, ID exhaustion, oversized directory, bounded error serialization,
and a peer that never reads. Run the same vectors in Python and Go and separate
capability vectors for registry records/pages and every image recipe variant.
