# bitcoin-dust-utxo-lab

Reproducible measurements of the relay policy changes proposed by
Bitcoin DOG Mode, run against Bitcoin Core v31.1.

This repository does not argue for or against the proposal. It answers
questions that were being asserted on both sides without measurement,
and publishes the harness so the numbers can be checked.

## Findings

1. [The 1-sat dust threshold needs no code change](findings/01-dust-threshold-needs-no-code-change.md)
   - `-dustrelayfee=0` yields a 1-sat threshold on every standard output
     type in unmodified v31.1, on any network.
2. [Raising the max standard tx weight is not a one-constant change](findings/02-tx-weight-is-not-a-one-line-change.md)
   - It does not compile. Core has a `static_assert` chain that forces
     three coupled constants to move together.
3. [What a 1-sat output costs, and who pays it](findings/03-what-a-1-sat-output-costs.md)
   - 42.65 bytes of chainstate per output, permanently. A block of dust
     costs its creator 0.01 BTC and every node operator 1.37 MB forever.
4. [The work is the tests, not the constants](findings/04-the-work-is-the-tests.md)
   - Stock v31.1 unit tests are clean; the three-constant patch breaks
     five test cases, three of which are behaviour questions.

Raw JSON for every run is in [`results/`](results/).

## Reproducing

Requires a Bitcoin Core v31.1 `bitcoind` binary. Standard library only,
no Python dependencies.

```sh
git clone https://github.com/bitcoin/bitcoin.git core && cd core
git checkout v31.1
cmake -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_GUI=OFF -DENABLE_IPC=OFF
cmake --build build -j"$(nproc)"
cd ..

python3 scripts/exp1_dust_threshold.py core/build/bin/bitcoind
python3 scripts/exp2_weight_and_cluster.py core/build/bin/bitcoind
python3 scripts/exp3_utxo_growth.py core/build/bin/bitcoind
```

Each script starts and tears down its own isolated regtest node and
writes JSON to `results/`.

## Method

[`METHODOLOGY.md`](METHODOLOGY.md) states the full procedure, the
metrics, and the known limitations, including which experiments were
run before the method was written down.

## Author

Tarık İsmet ALKAN
GitHub: [@tialkan](https://github.com/tialkan) ·
X: [@tialkan](https://x.com/tialkan)

MIT licensed.
