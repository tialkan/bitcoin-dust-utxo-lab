# Finding 5: preferential peering works, and it is not free

Status: partly measured, partly derived from source, partly open
Base: Bitcoin Core v31.1 with a port of the Libre Relay peering mechanism
Reproducible via `scripts/exp6_preferential_peering.py`
Raw data: `results/exp6_preferential_peering.json`

## What was actually implemented

The DOG Mode announcement says preferential peering is "adapted from
Libre Relay". The reference is `petertodd/bitcoin`, branch
`libre-relay-v30.0`, commit `66518db`. Read from source rather than
described from memory, that commit does three things:

- adds a service bit, `NODE_LIBRE_RELAY = (1 << 29)`
- reserves 4 dedicated outbound slots (`MAX_LIBRE_RELAY_CONNECTIONS`)
  and a new `ConnectionType`
- disconnects such a peer at the version handshake if it does not
  advertise the bit

It does **not** touch eviction. `AttemptToEvictConnection` is unchanged.
Any analysis claiming this mechanism works by protecting peers from
eviction, including an earlier draft of my own, is wrong about the
implementation.

Note also that the latest Libre Relay branch is v30.0 while DOG Mode's
base is v31.1, so adapting it means porting forward one major version.
v31.1 adds a `PRIVATE_BROADCAST` connection type that the v30 patch does
not account for.

## A design question the announcement does not address

The service bit means "I accept this policy set". Libre Relay and DOG
Mode do not run the same policy set: Libre Relay ships
replace-by-fee-rate and unstructured annex standardness, DOG Mode
proposes a 3.9M WU standard transaction ceiling and a 1 sat dust
threshold. If DOG Mode reuses `1 << 29`, each project's nodes will
advertise acceptance of transactions the other will reject, and both
will burn reserved slots on peers that cannot relay for them.

The port used here therefore uses a distinct bit, `NODE_DOG_RELAY =
(1 << 28)`. That is a choice, not a recommendation. It is the kind of
thing that should be decided and written down before release, not
inherited by copying a patch.

## What was measured

| | Result |
|---|---|
| Patched build advertises the bit | yes, `localservices = 0x10000c09` |
| Stock v31.1 advertises it | no |
| Reserved-slot connection between two signalling nodes | establishes, reported as `dog-relay` |
| Reserved-slot connection to a non-signalling node | dropped |

On the third row: the non-signalling peer never appeared in
`getpeerinfo` at all across 10 seconds of polling at 0.5s intervals. The
handshake check fires before the peer is ever listed. The observable
result is that it is not there; the mechanism is confirmed, the exact
moment of the drop is not.

## The cost, measured

The reserved outbound slots are added to `m_max_automatic_outbound`, and
`m_max_inbound` is derived by subtracting automatic outbound from
`max_automatic_connections` (`CConnman::Init`, `net.h`). So reserving
outbound slots silently reduces how many peers the node will serve.

Measured by opening raw TCP connections until `connections_in` stops
rising:

| `-maxconnections` | stock inbound | patched inbound | difference |
|---|---|---|---|
| 20 | 9 | 5 | 4 |
| 125 (default) | 114 | 110 | 4 |

The absolute cost is exactly `MAX_DOG_RELAY_CONNECTIONS`, as the
arithmetic predicts. In relative terms it is 3.5% of inbound capacity at
the default and 44% at `-maxconnections=20`.

The default case is the honest headline: a node running this improves
its own transaction reach by reducing, slightly, what it contributes
back to the network. That is a real trade and it should be stated in the
release notes rather than left for operators to discover. Operators
running deliberately small connection limits pay a much larger share.

## What is not measured, and why

Whether nodes running this actually find each other on a real network.

Peer selection is not a service-filtered `addrman.Select()`.
`ThreadOpenConnections` draws an address and does `continue` if the bit
is missing, and the surrounding loop gives up after 100 tries. At low
adoption a node may simply fail to fill the slots it has already
subtracted from its inbound capacity, which is the worst of both
outcomes.

Testing that end to end needs an addrman populated with reachable peers
at a known density. addrman rejects non-routable addresses
(`AddrManImpl::AddSingle`), so loopback regtest nodes cannot be injected
into it, and synthetic routable addresses have nothing listening behind
them. On a single host there is no honest way to run that experiment. I
would rather leave it open than approximate it and present the
approximation as an answer.

One further structural point, read from the source rather than measured:
the reserved-slot branch in `ThreadOpenConnections` sits after the
full-relay and block-relay branches. A node that cannot fill its 8
full-relay and 2 block-relay slots never reaches the preferential
peering branch at all.

## Test-only changes this required

Two hidden, test-only RPCs had to be extended to make any of this
observable, and they are part of the branch:

- `addpeeraddress` gained an optional `services` argument. It previously
  hardcoded `NODE_NETWORK | NODE_WITNESS`, so no injected address could
  ever carry a new service bit.
- `addconnection` gained the new connection type.
