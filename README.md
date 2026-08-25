# bitcoin-dust-utxo-lab

Reproducible measurements of the relay policy changes proposed by
Bitcoin DOG Mode, run against Bitcoin Core v31.1.

This repository does not argue for or against the proposal. It answers
questions that were being asserted on both sides without measurement,
and publishes the harness so the numbers can be checked.

## Findings

See [`findings/`](findings/) for the write-ups and [`results/`](results/)
for the raw JSON output of each run.

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
