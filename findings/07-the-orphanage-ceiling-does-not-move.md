# Finding 7: the orphan pool ceiling does not move, and a claim I got wrong

Status: measured, and it corrects an earlier claim of mine
Base: Bitcoin Core v31.1 and bitcoindogmode/bitcoin#4
Reproducible via `scripts/exp10_orphanage_bound.py`
Raw data: `results/exp10_orphanage_stock.json`,
`results/exp10_orphanage_pr4.json`

## The claim I made

`TxOrphanageImpl::AddTx` bounds a single orphan by `MAX_STANDARD_TX_WEIGHT`,
and the comment above that check says why:

```cpp
// Ignore transactions above max standard size to avoid a
// send-big-orphans memory exhaustion attack.
```

Next to it sits the per-peer memory reservation, unchanged by either
proposed implementation:

```cpp
static constexpr int64_t DEFAULT_RESERVED_ORPHAN_WEIGHT_PER_PEER{404'000};
```

404,000 is `MAX_PACKAGE_WEIGHT` in stock Core, so on stock a single
maximum-size orphan just fits inside one peer's whole reservation, at
0.99x. With the ceiling at 3,900,000 that becomes 9.65x.

From this I argued, in finding 4 and on bitcoindogmode/bitcoin#1 and #4,
that raising the ceiling changes the memory an attacker can pin and needs
a deliberate decision rather than a test update.

## What the measurement says

Largest orphan actually retained, probed by sending a child whose parent
was never submitted and counting `getorphantxs`, restarting the node
between probes:

| Target vsize | Weight | Stock v31.1 | PR #4 |
|---|---|---|---|
| 50,000 | 199,999 | accepted | accepted |
| 99,000 | 395,999 | accepted | accepted |
| 100,000 | 399,999 | accepted | accepted |
| 100,500 | 401,999 | rejected | rejected |
| 101,000 | 403,999 | rejected | rejected |
| 300,000 | 1,199,999 | rejected | rejected |
| 974,000 | 3,895,999 | rejected | rejected |

Identical, probe for probe. The effective ceiling is about 400,000 WU on
both builds.

## So the claim was wrong

The per-peer reservation binds first. `LimitOrphans` trims anything that
takes a peer past its allowance, and 404,000 WU is that allowance, so an
orphan of 3,895,999 WU is dropped on arrival regardless of what `AddTx`
permits. The memory a single peer can pin does not change.

The send-big-orphans protection the comment describes is therefore still
in force after the weight change. It is simply enforced by a different
constant than the one the comment points at.

## What is actually left

Two smaller things, neither of them a DoS question.

The `AddTx` check against `MAX_STANDARD_TX_WEIGHT` stops being reachable
for the case it was written for. Anything large enough to matter is
trimmed by the reservation before that check can be the binding
constraint. That is a code clarity issue: the comment now describes a
guarantee provided by a different line.

And `orphanage_tests/DoS_mapOrphans` fails for a purely mechanical
reason. It hardcodes `tx.vin.resize(2777)`, sized to exceed a 400,000 WU
ceiling; at 3,900,000 that transaction is under the ceiling, so the
`BOOST_CHECK(!orphanage->AddTx(...))` no longer holds. Deriving the input
count from the constant fixes it, the same way the `transaction_tests`
boundary was fixed. It does not need a behaviour decision, and I was
wrong to list it as one.

## Method note

The first version of this experiment did not clear the orphan pool
between probes and reported 395,999 WU as rejected. It was measuring
cumulative per-peer usage: a 199,999 WU orphan left from an earlier probe
is already half the allowance, so the next one is trimmed on arrival.
Restarting the node before each probe fixes it. Worth knowing, because
the wrong version looks plausible.
