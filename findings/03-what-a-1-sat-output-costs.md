# Finding 3: what a 1-sat output costs, and who pays it

Status: measured, reproducible via `scripts/exp3_utxo_growth.py`
Base: Bitcoin Core v31.1, regtest, `-dustrelayfee=0 -dbcache=450`
Raw data: `results/exp3_utxo_growth.json`

## Claim under test

The case for a 1-sat dust threshold has been made in terms of value
unlocked. The cost side has been asserted ("UTXO bloat") without a
number attached. This measures it.

## Method

450,000 1-sat P2WPKH outputs created in 150 mined batches, sampled every
25 batches. Destination addresses come from a descriptor the node's
wallet does not own, so that wallet bookkeeping does not contaminate the
chainstate and memory figures.

## Result

| batches | 1-sat outputs | txouts | chainstate on disk | RSS |
|---|---|---|---|---|
| 0 | 0 | 200 | 12.8 KB | 64 MB |
| 25 | 75,000 | 75,225 | 4.81 MB | 103 MB |
| 50 | 150,000 | 150,250 | 8.01 MB | 127 MB |
| 75 | 225,000 | 225,275 | 11.21 MB | 150 MB |
| 100 | 300,000 | 300,300 | 14.41 MB | 168 MB |
| 125 | 375,000 | 375,325 | 17.61 MB | 185 MB |
| 150 | 450,000 | 450,350 | 20.81 MB | 208 MB |

Marginal cost per additional UTXO, checkpoint to checkpoint:

```
63.97, 42.67, 42.65, 42.65, 42.65, 42.65 bytes
```

The first interval carries LevelDB's initial file allocation. From then
on the rate is flat to two decimal places:

- 42.65 bytes of chainstate on disk per 1-sat UTXO
- 33.98 bytes of serialised `disk_size` per UTXO
- 72.00 bytes of `bogosize` per UTXO, exactly, as expected for a
  uniform output type

## What that means per block

From the measured transaction shape, a P2WPKH output costs 31.04 vB of
block space. A block whose 1,000,000 vB is entirely 1-sat dust holds
about 32,219 outputs.

| | |
|---|---|
| permanent chainstate added | 1.37 MB |
| fee paid by the creator at 1 sat/vB | 0.01 BTC |
| borne by | every node operator, indefinitely |

That asymmetry is the finding. A one-time payment of 0.01 BTC buys 1.37
MB of storage on every full node on the network, forever. Sustained
across every block it would be roughly 198 MB per day. I am quoting
that as an upper bound on the mechanism, not as a forecast: no fee
environment fills every block with dust.

## Why these outputs are permanent

An output is economically spendable only if its value exceeds the fee
cost of the input that spends it.

| Input type | vsize | cost to spend at 1 sat/vB | feerate needed for a 1-sat output to be worth spending |
|---|---|---|---|
| P2TR key path | 57.5 vB | 57.5 sat | 0.017 sat/vB |
| P2WPKH | 68 vB | 68 sat | 0.015 sat/vB |
| P2PKH | 148 vB | 148 sat | 0.007 sat/vB |

Every figure in the last column is far below the default minimum relay
feerate of 1 sat/vB. A 1-sat output cannot be spent economically in any
fee environment the network has had. These are not transient entries
that clear when fees fall. They are permanent.

This is the question the proposal should answer directly. If the intent
is that these outputs are never spent, and they function as markers,
then the honest framing is not "how much value is unlocked" but "how
much do we grow the UTXO set permanently, and who pays for it". Both
halves are now quantified and the second one is answerable.

## Caveats, stated plainly

- The RSS column is not a permanent per-UTXO memory cost. It reflects
  the UTXO cache filling toward `-dbcache=450`; a node under cache
  pressure flushes. The disk figure is the one that is permanent.
- regtest has no fee market and no miner selection. Nothing here says
  what miners would include.
- Measured with P2WPKH outputs. P2TR outputs are larger (43 vB), so
  fewer fit per block, though each still costs the same in chainstate.
- This is a rate measurement over 450,000 UTXOs, not a mainnet
  forecast.
