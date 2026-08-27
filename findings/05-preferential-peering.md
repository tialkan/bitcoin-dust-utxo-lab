# Finding 5: preferential peering works, and it is not free

Status: measured, except for peer discovery through gossip
Base: Bitcoin Core v31.1 with a port of the Libre Relay peering mechanism
Reproducible via `scripts/exp6_preferential_peering.py` and
`scripts/exp7_peer_discovery.py`
Raw data: `results/exp6_preferential_peering.json`,
`results/exp7_peer_discovery.json`, `results/exp7_repeats.json`

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

## Does it find its peers? Measured after all

The first version of this finding left this open, because addrman
rejects non-routable addresses (`AddrManImpl::AddSingle`), so loopback
regtest nodes cannot be placed in it, and synthetic routable addresses
have nothing listening behind them.

`scripts/socks_mapper.py` closes that gap without touching the host's
network configuration. Peers are addressed as synthetic public IPs, one
per /16 since `ThreadOpenConnections` allows only one automatic outbound
peer per IPv4 /16, and a local SOCKS5 proxy maps each onto the real
loopback port. The node believes it is dialling `51.<n>.0.1`; the proxy
connects it to `127.0.0.1:(base + n)`.

24 peer nodes, a varying number of them signalling, one patched observer
with its addrman pre-populated with all 24 addresses carrying correct
flags. Measured: how many of the four reserved slots fill.

| Signalling peers | Density | Slots filled | Time to fill |
|---|---|---|---|
| 3 / 24 | 12.5% | 3 of 4 | not filled |
| 6 / 24 | 25% | 4 of 4 | 15s |
| 12 / 24 | 50% | 4 of 4 | 10s |
| 24 / 24 | 100% | 4 of 4 | 10s |

At 25% and above the mechanism works, and quickly. The concern that
reserved slots would sit empty at low adoption is not what happens,
provided the addrman is populated and the peers are reachable.

At 12.5% the ceiling is supply, not selection: there are only three
signalling peers in the whole network and the observer found them.
Repeating that case four times gave 3, 3, 3 and 2 slots filled. The run
that got 2 is the interesting one: an ordinary full-relay slot had taken
one of the three signalling peers first. Ordinary and reserved slots
compete for the same scarce peers, and the ordinary ones are filled
first.

## The case where it never engages at all

The sharpest result came from the smallest setup. Six peers, every one
of them signalling, so 100% density:

| Peers | Density | Slots filled |
|---|---|---|
| 6 / 6 | 100% | 0 of 4 |

Zero, in three consecutive runs.

The reserved-slot branch in `ThreadOpenConnections` sits after the
full-relay and block-relay branches. With six reachable peers, all six
are consumed filling the eight full-relay slots, and the reserved branch
is never reached. A node with fewer than about ten reachable peers gets
no preferential peering at all, whatever the adoption rate is.

It still pays for it. The four reserved slots are added to
`m_max_automatic_outbound` regardless of whether they are ever used, so
such a node loses four inbound slots and gains nothing. That is the
worst position in this design, and it lands on exactly the nodes with
the weakest connectivity.

## What is still not measured

How nodes learn about each other in the first place. Everything above
starts from an addrman that already contains the peers with correct
service flags. Whether that state is reached through `addr` gossip on a
real network, and how long it takes at a given adoption rate, is a
separate question this harness does not answer.

## Test-only changes this required

Two hidden, test-only RPCs had to be extended to make any of this
observable, and they are part of the branch:

- `addpeeraddress` gained an optional `services` argument. It previously
  hardcoded `NODE_NETWORK | NODE_WITNESS`, so no injected address could
  ever carry a new service bit.
- `addconnection` gained the new connection type.
