#!/usr/bin/env python3
"""Experiment 2 - what actually caps transaction size in v31.1?

DOG Mode proposes raising MAX_STANDARD_TX_WEIGHT from 400_000 to
3_900_000 WU. This experiment establishes two things empirically:

  2a. The stock v31.1 standardness ceiling, by growing a transaction
      output-by-output until the node answers "tx-size".
  2b. Whether a second, independent limit sits behind it. Since v31.1
      replaced ancestor/descendant size limits with cluster size limits
      (DEFAULT_CLUSTER_SIZE_LIMIT_KVB = 101), a transaction near
      3_900_000 WU (= 975_000 vB) would exceed the cluster ceiling by
      almost 10x even with no unconfirmed parents. 2b tests the cluster
      limit directly by chaining two large transactions.

Usage: python3 exp2_weight_and_cluster.py /path/to/bitcoind
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from regtest_env import RegtestNode, RPCError

COIN = 100_000_000


def setup(node, blocks=200):
    node.rpc("createwallet", "lab")
    addr = node.rpc("getnewaddress")
    node.rpc("generatetoaddress", blocks, addr)
    return addr


def address_pool(node, count):
    """Derive `count` distinct addresses in one call.

    createrawtransaction rejects duplicate addresses, so a fanout test
    needs a distinct scriptPubKey per output. deriveaddresses over the
    wallet's own public descriptor is far cheaper than `count` calls to
    getnewaddress.
    """
    for d in node.rpc("listdescriptors")["descriptors"]:
        desc = d["desc"]
        if desc.startswith("wpkh(") and "/0/*" in desc:
            return node.rpc("deriveaddresses", desc, [0, count - 1])
    raise RuntimeError("no ranged wpkh descriptor found in wallet")


def biggest_utxo(node):
    utxos = sorted(node.rpc("listunspent", 1), key=lambda u: -u["amount"])
    return utxos[0]


def fanout_tx(node, utxo, n_outputs, sats_per_output, pool):
    """One input -> n_outputs distinct outputs + change. Returns (hex, decoded)."""
    if n_outputs + 1 > len(pool):
        raise RuntimeError("address pool too small")
    value = sats_per_output / COIN
    total_out = value * n_outputs
    change = round(float(utxo["amount"]) - total_out - 0.01, 8)
    if change <= 0:
        raise RuntimeError("input too small for requested fanout")
    outputs = [{pool[i]: f"{value:.8f}"} for i in range(n_outputs)]
    outputs.append({pool[n_outputs]: f"{change:.8f}"})
    raw = node.rpc(
        "createrawtransaction",
        [{"txid": utxo["txid"], "vout": utxo["vout"]}],
        outputs,
    )
    signed = node.rpc("signrawtransactionwithwallet", raw)
    dec = node.rpc("decoderawtransaction", signed["hex"])
    return signed["hex"], dec


def accept_check(node, tx_hex):
    res = node.rpc("testmempoolaccept", [tx_hex])[0]
    return res.get("allowed", False), res.get("reject-reason", "")


def part_a(node, pool):
    """Grow output count until the node stops accepting. Report the wall."""
    utxo = biggest_utxo(node)
    lo, hi = 100, 8000
    last_ok = None
    first_bad = None
    while lo <= hi:
        mid = (lo + hi) // 2
        tx_hex, dec = fanout_tx(node, utxo, mid, 1000, pool)
        ok, reason = accept_check(node, tx_hex)
        rec = {"n_outputs": mid, "weight": dec["weight"], "vsize": dec["vsize"],
               "allowed": ok, "reject_reason": reason}
        if ok:
            last_ok = rec
            lo = mid + 1
        else:
            first_bad = rec
            hi = mid - 1
    return {"largest_accepted": last_ok, "smallest_rejected": first_bad,
            "policy_constant_MAX_STANDARD_TX_WEIGHT": 400000}


def part_b(node, pool):
    """Chain two large txs so their combined cluster exceeds the limit."""
    utxo = biggest_utxo(node)
    # Parent: sized to sit comfortably under the standardness ceiling.
    parent_hex, parent_dec = fanout_tx(node, utxo, 3000, 1000, pool)
    ok, reason = accept_check(node, parent_hex)
    if not ok:
        return {"error": f"parent unexpectedly rejected: {reason}", "parent": parent_dec["vsize"]}
    parent_txid = node.rpc("sendrawtransaction", parent_hex)

    # Child spends the parent's change output (the last one) and fans out again.
    change_vout = len(parent_dec["vout"]) - 1
    change_val = parent_dec["vout"][change_vout]["value"]
    child_utxo = {"txid": parent_txid, "vout": change_vout, "amount": change_val}
    child_hex, child_dec = fanout_tx(node, child_utxo, 3000, 1000, pool)
    ok_c, reason_c = accept_check(node, child_hex)

    return {
        "parent_vsize": parent_dec["vsize"],
        "parent_weight": parent_dec["weight"],
        "child_vsize": child_dec["vsize"],
        "child_weight": child_dec["weight"],
        "combined_cluster_vsize": parent_dec["vsize"] + child_dec["vsize"],
        "cluster_size_limit_vbytes": 101000,
        "child_allowed": ok_c,
        "child_reject_reason": reason_c,
    }


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    bitcoind = sys.argv[1]
    report = {}
    with RegtestNode(bitcoind) as node:
        setup(node)
        pool = address_pool(node, 9000)
        print("--- 2a: standardness ceiling ---", flush=True)
        report["2a_standardness_ceiling"] = part_a(node, pool)
        print(json.dumps(report["2a_standardness_ceiling"], indent=2), flush=True)
        print("--- 2b: cluster size limit ---", flush=True)
        report["2b_cluster_limit"] = part_b(node, pool)
        print(json.dumps(report["2b_cluster_limit"], indent=2), flush=True)
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "results", "exp2_weight_and_cluster.json")
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
