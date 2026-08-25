# Methodology

Stated in full so that every number in `findings/` can be re-derived or
falsified. The harness in `scripts/` is the authoritative description;
this document explains the choices behind it.

Disclosure on ordering: experiments 1 and 2 were run before this
document was written, so it is a description of what was done, not a
pre-registration. Experiment 3 onward follow the procedure as written
here. Where that distinction could matter, the finding says so.

## What is being tested

Bitcoin DOG Mode (announced 17 July 2026; repository forked from
bitcoin/bitcoin in August 2026) proposes three relay/standardness
policy changes on top of Bitcoin Core v31.1:

1. Raise the maximum standard transaction size from 400,000 WU to
   3,900,000 WU.
2. Lower the dust threshold from the per-output-type 294-546 sat range
   to 1 sat.
3. Preferential peering between DOG Mode nodes, adapted from Libre Relay.

None of these are consensus changes. This work takes no position on
whether they should be adopted. It asks three answerable questions:

- Q1: Is change (2) actually a code change, or is it already reachable
  through existing runtime configuration?
- Q2: Is change (1) a single-constant change, or does it have
  dependencies that the announcement does not mention?
- Q3: What is the measurable cost of a 1-sat output to the UTXO set,
  and under what fee conditions can such an output ever be spent?

## Base

- Upstream: bitcoin/bitcoin v31.1 (tag v31.1, commit 9be056a8).
- DOG Mode repo at time of writing is v31.1 plus a single README commit
  (bbc08805, 24 Aug 2026). No policy code exists in it yet, so all
  experiments are run against v31.1 with locally applied patches that
  implement the announced changes as literally as possible.
- Build: CMake, Release, `-DBUILD_GUI=OFF -DENABLE_WALLET=ON -DENABLE_IPC=OFF`.

## Network

regtest. Chosen over signet deliberately: the questions above are about
deterministic policy behaviour and chainstate accounting, both of which
regtest reproduces exactly, and regtest allows a reviewer to reproduce
a run in minutes rather than days. Signet is appropriate for a later
stage, when propagation and miner-inclusion behaviour is the question.

## Oracle

The node itself, via `testmempoolaccept`, is the oracle for every
acceptance question. No wallet-side heuristics are trusted, because
wallet dust behaviour and node relay policy are separate code paths and
conflating them is the most common error in this kind of measurement.

## Metrics for Q3

Sampled from `gettxoutsetinfo` plus the filesystem at fixed checkpoints:

- `txouts`: UTXO count.
- `bogosize`: Core's own implementation-independent UTXO set measure.
- `disk_size`: serialised chainstate size.
- on-disk `chainstate/` directory size.
- bitcoind RSS at fixed `-dbcache=450`.

Derived: chainstate bytes added per additional UTXO.

## Economic spendability

An output is economically spendable only if its value exceeds the fee
cost of the input that spends it. Input virtual sizes used:

- P2TR key path: 57.5 vB
- P2WPKH: 68 vB
- P2PKH: 148 vB

This is arithmetic, not measurement, and is reported separately from
the measured results.

## Known limitations

- regtest does not model fee markets, miner selection, or propagation.
  Nothing here should be read as a claim about what miners would do.
- The UTXO growth run is bounded by wall-clock time and is a rate
  measurement, not a forecast of mainnet growth.
- Preferential peering (change 3) is not tested here. It needs a
  multi-node harness and is deferred.
