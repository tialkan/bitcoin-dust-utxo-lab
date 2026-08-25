# Finding 1: the 1-sat dust threshold needs no code change

Status: measured, reproducible via `scripts/exp1_dust_threshold.py`
Base: Bitcoin Core v31.1, regtest
Raw data: `results/exp1_dust_threshold.json`

## Claim under test

Bitcoin DOG Mode lists "lower the dust limit from 294-546 sat to 1 sat"
as one of three changes in its first release, implying a patch to
`GetDustThreshold()` in `src/policy/policy.cpp`.

## Method

For each standard output type, binary-search the smallest output value
that stock `bitcoind` does not reject from `testmempoolaccept` with
reason `dust`, under four settings of the existing `-dustrelayfee`
runtime option.

## Result

Minimum non-dust output value, in satoshis:

| Output type    | default (3000 sat/kvB) | 3000 sat/kvB (explicit) | 100 sat/kvB | 0 |
|----------------|------------------------|-------------------------|-------------|---|
| P2PKH (legacy) | 546 | 546 | 19 | 1 |
| P2SH-P2WPKH    | 540 | 540 | 18 | 1 |
| P2WPKH         | 294 | 294 | 10 | 1 |
| P2TR           | 330 | 330 | 11 | 1 |

## Interpretation

`-dustrelayfee=0` produces a 1-sat threshold on every standard output
type in unmodified Bitcoin Core v31.1. `-dustrelayfee` is registered in
`src/init.cpp` with `ALLOW_ANY | DEBUG_ONLY`, so it is usable on any
network, mainnet included, today.

Change (2) is therefore not a code change. It is a default value change
plus documentation. That is a legitimate thing for a distribution to
do, but it should be described accurately: a node operator who wants
this behaviour does not need DOG Mode, and does not need to leave
Bitcoin Core.

## Secondary correction

The commonly quoted range "294-546 sat" is incomplete. P2TR outputs sit
at 330 sat, not at either end of that range, and P2SH-P2WPKH at 540.
The full set of stock thresholds is the first column above.

## What this does not show

Nothing here says whether a 1-sat threshold is a good idea. That
depends on the cost side, which is Finding 3.
