#!/usr/bin/env python3
"""Experiment 4 - does the DOG Mode weight change work once it compiles?

Run against a bitcoind built with the minimal patch that actually
compiles (see findings/02): MAX_STANDARD_TX_WEIGHT, MAX_PACKAGE_WEIGHT
and DEFAULT_CLUSTER_SIZE_LIMIT_KVB all raised together.

Grows a single transaction with no unconfirmed parents up to and past
3,900,000 WU and reports where, and why, the node stops accepting it.

Usage: python3 exp4_patched_large_tx.py /path/to/patched/bitcoind
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from regtest_env import RegtestNode

COIN = 100_000_000
POOL = 34000


def address_pool(node, count):
    for d in node.rpc("listdescriptors")["descriptors"]:
        desc = d["desc"]
        if desc.startswith("wpkh(") and "/0/*" in desc:
            return node.rpc("deriveaddresses", desc, [0, count - 1])
    raise RuntimeError("no ranged wpkh descriptor")


def fanout(node, utxo, n, sats, pool):
    value = sats / COIN
    change = round(float(utxo["amount"]) - value * n - 0.05, 8)
    outs = [{pool[i]: f"{value:.8f}"} for i in range(n)]
    outs.append({pool[n]: f"{change:.8f}"})
    raw = node.rpc("createrawtransaction",
                   [{"txid": utxo["txid"], "vout": utxo["vout"]}], outs)
    signed = node.rpc("signrawtransactionwithwallet", raw)
    dec = node.rpc("decoderawtransaction", signed["hex"])
    return signed["hex"], dec


def probe(node, pool, n):
    utxo = sorted(node.rpc("listunspent", 1), key=lambda u: -u["amount"])[0]
    tx_hex, dec = fanout(node, utxo, n, 1000, pool)
    res = node.rpc("testmempoolaccept", [tx_hex])[0]
    return {"n_outputs": n, "weight": dec["weight"], "vsize": dec["vsize"],
            "allowed": res.get("allowed", False),
            "reject_reason": res.get("reject-reason", "")}


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    args = ["-maxmempool=300"]
    report = {"node_args": args, "probes": []}
    with RegtestNode(sys.argv[1], args) as node:
        node.rpc("createwallet", "lab")
        addr = node.rpc("getnewaddress")
        node.rpc("generatetoaddress", 400, addr)
        pool = address_pool(node, POOL)
        # Sweep from just over the stock ceiling up past the DOG Mode target.
        for n in (3300, 10000, 20000, 31000, 31400, 31500, 32000):
            try:
                r = probe(node, pool, n)
            except Exception as e:
                r = {"n_outputs": n, "error": str(e)}
            report["probes"].append(r)
            print(json.dumps(r), flush=True)
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "results", "exp4_patched_large_tx.json")
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
