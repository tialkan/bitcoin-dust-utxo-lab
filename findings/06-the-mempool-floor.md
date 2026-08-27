# Finding 6: what changes at the -maxmempool floor

Status: measured
Base: Bitcoin Core v31.1 and bitcoindogmode/bitcoin#3
Reproducible via `scripts/exp9_mempool_floor.py`
Raw data: `results/exp9_mempool_floor.json`

## Why this was measured

PR #3 on the DOG Mode repository raises
`DEFAULT_CLUSTER_SIZE_LIMIT_KVB` to 976 and changes the multiplier in
`Flatten()` from 40 to 5, keeping the permitted `-maxmempool` floor near
its historical ~5 MB rather than letting it rise to 39 MB.

Review of that PR argued the point from first principles in both
directions: that the 40x margin from commit `794a8cec` is a
cluster-count margin and dropping to 5x removes most of it, and that the
margin is byte-denominated and bytes are preserved. Neither side
measured it.

## Method

Same `-maxmempool=5` on both builds. Each filled with independent
maximum-size transactions at 1.2 sat/vB, funded one per coinbase output
so that they form separate clusters rather than one chain. Then an
ordinary transaction at 10 sat/vB is offered as a probe.

A control run puts 100 kvB transactions through the patched build, to
separate the effect of the multiplier from the effect of larger
transactions.

## Result

| Build | Max tx vsize | One tx as share of mempool | Txs held | `mempoolminfee` (BTC/kvB) | Probe accepted |
|---|---|---|---|---|---|
| stock v31.1, 100 kvB txs | 99,312 | 1.99% | 30 | 0.00000100 | yes |
| PR#3, 975 kvB txs | 961,112 | 19.22% | 3 | 0.00001299 | yes |
| PR#3, 100 kvB txs (control) | 99,312 | 1.99% | 30 | 0.00000100 | yes |

The fifth large transaction was rejected with:

```
mempool min fee not met, 1153332 < 1248485
```

at the same feerate its predecessors were accepted at, with the mempool
around 90% full. One of the four accepted had already been evicted.

## Interpretation

The control is what makes this readable. The patched build fed ordinary
transactions behaves identically to stock, so this is not the multiplier
change in isolation. It is what happens when maximum-size transactions
meet a mempool near the floor.

What changes is sensitivity. Thirty transactions leave stock's minimum
feerate at the floor. Four raise the patched build's to thirteen times
the floor, because one eviction is now about a fifth of the mempool.
That is the granularity argument, and it is neither of the two framings
that were being argued: the attacker's byte cost really is preserved,
and the cluster count really does drop, but what an operator at the
floor sees is a minimum feerate moving in 20% steps for reasons
unrelated to fee market conditions.

Bounded honestly: an ordinary 10 sat/vB transaction was accepted in
every case, including after filling. This is not a node that stops
working. It is a node whose mempool policy diverges from the network's,
and whose fee estimation is reading its own eviction noise.

At the 300 MB default none of this arises. It applies to operators
running near the floor, who are precisely the operators the floor change
was made to accommodate.
