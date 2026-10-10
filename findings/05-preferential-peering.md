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

The reserved-slot branch sits well down the priority chain in
`ThreadOpenConnections`. With six reachable peers, all six are consumed
filling the eight full-relay slots, and the reserved branch is never
reached. A node with fewer than about ten reachable peers gets no
preferential peering at all, whatever the adoption rate is.

An earlier version of this finding described the branch as sitting
"after the full-relay and block-relay branches", which implied two tiers
ahead of it. That understated it. Counted in the if/else-if chain:

1. anchor block-relay
2. full-relay
3. block-relay
4. `GetTryNewOutboundPeer()`, a second full-relay path
5. the periodic extra-block-relay anti-eclipse branch
6. **reserved slots**
7. feeler
8. extra network peer

Five tiers ahead, not two. Because each pass through the loop commits to
one connection type, a senior quota that is permanently unmet, for
instance full-relay stuck below 8 because the address pool is thin,
blocks the chain from ever reaching the reserved branch however many
attempts run. That is a general property of the ordering rather than an
artifact of a particular harness size. Correction due to Mehdalon on
bitcoindogmode/bitcoin#3.

It still pays for it. The four reserved slots are added to
`m_max_automatic_outbound` regardless of whether they are ever used, so
such a node loses four inbound slots and gains nothing. That is the
worst position in this design, and it lands on exactly the nodes with
the weakest connectivity.

## Learning the peers in the first place

Everything above starts from an addrman already holding the peers.
`scripts/exp8_gossip_discovery.py` removes that assumption: every node
advertises a synthetic public address via `-externalip`, is reachable at
it through the mapper, and the observer starts knowing nothing but a
single bootstrap hub, as it would from a seed node. Nothing is
pre-populated.

24 peers, 12 of them signalling, one observer, 25 minutes:

| Elapsed | Addresses known | Signalling known | Outbound full-relay | Reserved slots |
|---|---|---|---|---|
| 60s | 2 | 2 | 1 | 0 |
| 180s | 8 | 6 | 7 | 0 |
| 300s | 9 | 7 | 8 | 0 |
| 900s | 9 | 7 | 8 | 0 |
| 1500s | 9 | 7 | 8 | 0 |

Discovery plateaued at 9 of 24 addresses after five minutes and did not
move again for the following twenty. The reserved slots never filled.

The reason is precise, and it is the branch ordering again, one step
earlier than expected. The observer ended with 8 full-relay and 1
block-relay connection, having used all nine addresses it knew. The
reserved-slot branch sits below the block-relay branch, which wants
two. One address short of a slot nobody thinks about, the node never
reaches preferential peering at all.

Two caveats, and they matter. This is a single run. And a 24 node closed
network with one bootstrap hub is a much thinner address supply than the
real network, where a node starts from DNS seeds with hundreds of
addresses; the plateau at 9 is an artifact of that thinness, not a
prediction about mainnet.

What is not an artifact is the ordering. Reserved slots are reached only
after 8 full-relay and 2 block-relay slots are satisfied, so how fast a
node learns peers directly gates whether preferential peering engages at
all. And the inbound cost is charged from the first second, whether or
not it ever engages.

## Added 10 October 2026: the merged implementation and PR #10

Everything above was measured on a port of Libre Relay's mechanism
(`NODE_DOG_RELAY`, bit 28, connection type `dog-relay`). The implementation
that was actually merged (bitcoindogmode/bitcoin#3, merge commit
`75032400914250c7ad857dc29043761680a66485`) is different code: bit 14
(`NODE_DOG_MODE`), connection type `dog`, `MAX_DOG_MODE_CONNECTIONS = 4`.
Its `dog` choice also sits above the feeler and network-specific choices in
`ThreadOpenConnections`. PR #10 (`dogofbitcoin`) moves it below them and
reports, from mainnet, 0-1 feelers per hour without the change against 28-32
with it. This section reruns the same topology as experiment 7 on both builds
(`scripts/exp11_merged_vs_pr10.py`, results in `results/exp11_*.json`).

Build notes, because they affect how far this can be trusted: both builds are
the PR's own commits plus one test-only patch (`addpeeraddress` accepting a
services argument, the same patch as before). On this machine (macOS 26.6,
SDK 27) a fresh build of any commit, including stock `31.1-dogmode`, crashes
at start-up in `TokenPipe::Make()` because the SDK declares `pipe2` and the OS
does not provide it; the builds here use `-DHAVE_DECL_PIPE2=0`. That is a
toolchain issue and says nothing about the DOG Mode code.

**Slot fill, same four densities as before, one run per cell:**

| Peers (signalling) | merged `7503240091` | PR #10 |
|---|---|---|
| 24 (3) | 2 of 4 | 2 of 4 |
| 24 (12) | 4 of 4, 10 s | 4 of 4, 10 s |
| 24 (24) | 4 of 4, 10 s | 4 of 4, 10 s |
| 6 (6) | 0 of 4 | 0 of 4 |

The six-peer case is unchanged by PR #10, as it should be: the `dog` choice is
still below the full-relay choice, so a node short of peers never reaches it.
PR #10 does not address that, and does not claim to.

**Feelers, with addresses in the `new` table (420 s, one run per cell):**

| Peers (signalling) | build | `dog` connections | feelers opened |
|---|---|---|---|
| 24 (3) | merged | 1 | 0 |
| 24 (3) | PR #10 | 0 | 4 |

With a `dog` slot empty, the merged build opened no feeler in 420 s where
about 3.5 would be expected at the default interval; PR #10 opened four. This
agrees with the mainnet reading in #10 and with the ordering in the code.

What this does and does not show:

- The first version of this experiment seeded addrman with `tried=True` and
  reported 0 feelers on every build. Feelers draw only from the `new` table, so
  that column carried no information and is not reported. The table above
  uses `tried=False`.
- One run per cell. In the 3-signalling-peer row the two builds ended with
  different numbers of `dog` connections (1 and 0) because which peers the
  full-relay slots take first is random; that difference is not attributable
  to PR #10.
- Feeler counts in the 12-signalling-peer rows cover only the seconds before
  the slots filled, and are not informative.
- Same limits as the rest of this finding: 24 nodes on one host, not a
  network, and PR #10's own functional test was not run here.

## What is still not measured

Any of this at realistic network scale. Everything here is a small
closed network on one host. The mechanism, the costs and the ordering
reproduce; the timings and the plateau do not transfer to mainnet.

## Test-only changes this required

Two hidden, test-only RPCs had to be extended to make any of this
observable, and they are part of the branch:

- `addpeeraddress` gained an optional `services` argument. It previously
  hardcoded `NODE_NETWORK | NODE_WITNESS`, so no injected address could
  ever carry a new service bit.
- `addconnection` gained the new connection type.
