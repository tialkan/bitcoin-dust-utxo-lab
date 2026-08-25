#!/usr/bin/env python3
"""Experiment 3 - what does a 1-sat output cost the UTXO set?

DOG Mode proposes a 1-sat dust threshold. The stated benefit accrues to
the party creating those outputs; the cost is carried by every node
operator, forever, because a 1-sat output can never be economically
spent (see the break-even calculation printed at the end).

This experiment quantifies the cost side. It creates 1-sat outputs in
bulk on regtest with -dustrelayfee=0, mines them, and samples the
chainstate at checkpoints.

Metrics per checkpoint:
  txouts     - UTXO count reported by gettxoutsetinfo
  bogosize   - Core's own size-agnostic UTXO set measure
  disk_size  - serialised chainstate size in bytes
  chainstate - actual on-disk directory size in bytes
  rss_kb     - resident memory of bitcoind at fixed -dbcache

Usage: python3 exp3_utxo_growth.py /path/to/bitcoind [n_batches] [outs_per_batch]
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from regtest_env import RegtestNode

COIN = 100_000_000

# Input vsize by type, used for the economic-spendability break-even.
INPUT_VSIZE = {"P2TR keypath": 57.5, "P2WPKH": 68.0, "P2PKH": 148.0}


def dir_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def rss_kb(pid):
    try:
        out = subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)])
        return int(out.strip())
    except Exception:
        return None


def address_pool(node, count):
    for d in node.rpc("listdescriptors")["descriptors"]:
        desc = d["desc"]
        if desc.startswith("wpkh(") and "/0/*" in desc:
            return node.rpc("deriveaddresses", desc, [0, count - 1])
    raise RuntimeError("no ranged wpkh descriptor found")


def sample(node):
    info = node.rpc("gettxoutsetinfo")
    return {
        "height": info["height"],
        "txouts": info["txouts"],
        "bogosize": info["bogosize"],
        "disk_size": info["disk_size"],
        "chainstate_bytes": dir_size(os.path.join(node.datadir, "regtest", "chainstate")),
        "rss_kb": rss_kb(node.proc.pid),
    }


def biggest_utxo(node):
    return sorted(node.rpc("listunspent", 1), key=lambda u: -u["amount"])[0]


def make_batch(node, pool, n_outputs, sats):
    utxo = biggest_utxo(node)
    value = sats / COIN
    change = round(float(utxo["amount"]) - value * n_outputs - 0.01, 8)
    outputs = [{pool[i]: f"{value:.8f}"} for i in range(n_outputs)]
    outputs.append({pool[n_outputs]: f"{change:.8f}"})
    raw = node.rpc("createrawtransaction",
                   [{"txid": utxo["txid"], "vout": utxo["vout"]}], outputs)
    signed = node.rpc("signrawtransactionwithwallet", raw)
    return node.rpc("sendrawtransaction", signed["hex"])


def breakeven():
    """Feerate at which a 1-sat output is worth more than the fee to spend it."""
    rows = {}
    for label, vsize in INPUT_VSIZE.items():
        rows[label] = {
            "input_vsize": vsize,
            "cost_to_spend_at_1_sat_per_vb": vsize,
            "max_feerate_for_1sat_output_to_be_spendable_sat_per_vb": round(1.0 / vsize, 5),
            "spendable_at_min_relay_fee_1_sat_per_vb": False,
        }
    return rows


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    bitcoind = sys.argv[1]
    n_batches = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    outs = int(sys.argv[3]) if len(sys.argv) > 3 else 3000

    args = ["-dustrelayfee=0", "-dbcache=450", "-blockmintxfee=0", "-minrelaytxfee=0"]
    report = {"config": {"n_batches": n_batches, "outs_per_batch": outs,
                         "node_args": args}, "checkpoints": []}
    with RegtestNode(bitcoind, args) as node:
        node.rpc("createwallet", "lab")
        addr = node.rpc("getnewaddress")
        node.rpc("generatetoaddress", 200, addr)
        pool = address_pool(node, outs + 2)

        report["baseline"] = sample(node)
        print("baseline:", json.dumps(report["baseline"]), flush=True)

        for i in range(1, n_batches + 1):
            make_batch(node, pool, outs, 1)
            node.rpc("generatetoaddress", 1, addr)
            if i % 25 == 0 or i == n_batches:
                s = sample(node)
                s["batches_done"] = i
                s["one_sat_outputs_created"] = i * outs
                report["checkpoints"].append(s)
                print(json.dumps(s), flush=True)

    base = report["baseline"]
    last = report["checkpoints"][-1]
    added_utxos = last["txouts"] - base["txouts"]
    added_disk = last["chainstate_bytes"] - base["chainstate_bytes"]
    report["summary"] = {
        "utxos_added": added_utxos,
        "chainstate_bytes_added": added_disk,
        "chainstate_bytes_per_utxo": round(added_disk / added_utxos, 2) if added_utxos else None,
        "disk_size_bytes_per_utxo": round(
            (last["disk_size"] - base["disk_size"]) / added_utxos, 2) if added_utxos else None,
        "bogosize_per_utxo": round(
            (last["bogosize"] - base["bogosize"]) / added_utxos, 2) if added_utxos else None,
        "rss_kb_delta": (last["rss_kb"] or 0) - (base["rss_kb"] or 0),
    }
    report["economic_spendability"] = breakeven()
    print("\nsummary:", json.dumps(report["summary"], indent=2))
    print("break-even:", json.dumps(report["economic_spendability"], indent=2))

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "results", "exp3_utxo_growth.json")
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
