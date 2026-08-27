#!/usr/bin/env python3
"""Experiment 9 - what changes at the -maxmempool floor?

Context. bitcoindogmode/bitcoin#3 raises DEFAULT_CLUSTER_SIZE_LIMIT_KVB
to 976 and, to keep the permitted -maxmempool floor near its historical
~5 MB, changes the multiplier in Flatten() from 40 to 5. Review of that
PR is currently arguing the point from first principles: one side says
the 40x margin from 794a8cec is a cluster-count margin and dropping to
5x removes 8x of it, the other says the margin is byte-denominated and
bytes are preserved (40 x 101 kvB = 4.04 MB, 5 x 976 kvB = 4.88 MB).

Both are arguing about what the multiplier protects. This measures what
actually changes.

The quantity neither framing captures is granularity: at the floor, one
maximum-size transaction is about 2.5% of a stock mempool and about 20%
of a patched one. Eviction works in units of clusters, so coarser units
mean coarser eviction.

Measured, at -maxmempool=5 on both builds: how many maximum-size
transactions fit, what the mempool minimum feerate becomes once full,
and whether an ordinary transaction at an ordinary feerate is still
accepted afterwards.

Usage: python3 exp9_mempool_floor.py STOCK_BIN PR3_BIN
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from regtest_env import RegtestNode, RPCError

COIN = 100_000_000
MAXMEMPOOL_MB = 5


def address_pool(node, count):
    for d in node.rpc("listdescriptors")["descriptors"]:
        if d["desc"].startswith("wpkh(") and "/0/*" in d["desc"]:
            return node.rpc("deriveaddresses", d["desc"], [0, count - 1])
    raise RuntimeError("no ranged wpkh descriptor")


def build_tx(node, funding, pool, n_outputs, fee_btc):
    """Spend `funding` into n_outputs, paying `fee_btc`. Returns hex, decoded, change."""
    per_out = 0.00001
    total_out = per_out * n_outputs
    change = round(float(funding["amount"]) - total_out - fee_btc, 8)
    if change <= 0:
        raise RuntimeError("funding exhausted")
    outs = [{pool[i]: f"{per_out:.8f}"} for i in range(n_outputs)]
    # Change goes to a pool entry, not to getnewaddress: both derive from the
    # same wallet descriptor, and createrawtransaction rejects duplicates.
    outs.append({pool[n_outputs]: f"{change:.8f}"})
    raw = node.rpc("createrawtransaction",
                   [{"txid": funding["txid"], "vout": funding["vout"]}], outs)
    signed = node.rpc("signrawtransactionwithwallet", raw)
    dec = node.rpc("decoderawtransaction", signed["hex"])
    return signed["hex"], dec, {"txid": dec["txid"], "vout": n_outputs, "amount": change}


def run(binary, label, n_outputs, low_feerate=1.2, probe_feerate=10.0):
    args = [f"-maxmempool={MAXMEMPOOL_MB}", "-dnsseed=0", "-fixedseeds=0"]
    with RegtestNode(binary, args) as node:
        node.rpc("createwallet", "w")
        addr = node.rpc("getnewaddress")
        node.rpc("generatetoaddress", 250, addr)
        pool = address_pool(node, n_outputs + 2)
        # One coinbase output per transaction. Chaining them would put every
        # transaction in a single cluster, which is the limit under test and
        # would make the experiment measure the wrong thing entirely.
        utxos = [u for u in sorted(node.rpc("listunspent", 1),
                                   key=lambda u: -u["amount"])
                 if float(u["amount"]) >= 1.0]

        accepted, rejects = [], []
        max_vsize = None
        for funding in utxos[:40]:
            try:
                tx_hex, dec, _ = build_tx(node, funding, pool, n_outputs,
                                          round(dec_fee(n_outputs, low_feerate), 8))
            except RuntimeError:
                break
            max_vsize = dec["vsize"]
            try:
                node.rpc("sendrawtransaction", tx_hex)
                accepted.append(dec["vsize"])
            except RPCError as e:
                rejects.append(str(e))
                break
            info = node.rpc("getmempoolinfo")
            if info["usage"] > info["maxmempool"] * 0.9:
                break
        funding = utxos[len(accepted) + 1] if len(utxos) > len(accepted) + 1 else utxos[-1]

        info = node.rpc("getmempoolinfo")
        # Probe: an ordinary sized transaction at a clearly higher feerate.
        probe_ok, probe_reason = None, ""
        try:
            probe_hex, probe_dec, _ = build_tx(node, funding, pool, 200,
                                               round(dec_fee(200, probe_feerate), 8))
            res = node.rpc("testmempoolaccept", [probe_hex])[0]
            probe_ok = res.get("allowed", False)
            probe_reason = res.get("reject-reason", "")
        except Exception as e:
            probe_reason = f"could not build probe: {e}"

        return {
            "build": label,
            "maxmempool_mb": MAXMEMPOOL_MB,
            "outputs_per_tx": n_outputs,
            "max_tx_vsize": max_vsize,
            "single_tx_share_of_mempool_pct": round(100 * max_vsize / (MAXMEMPOOL_MB * 1_000_000), 2) if max_vsize else None,
            "txs_accepted": len(accepted),
            "mempool_bytes": info["bytes"],
            "mempool_usage": info["usage"],
            "mempool_txcount": info["size"],
            "mempoolminfee_btc_kvb": info["mempoolminfee"],
            "probe_ordinary_tx_accepted": probe_ok,
            "probe_reject_reason": probe_reason,
            "first_reject": rejects[0] if rejects else None,
        }


def dec_fee(n_outputs, sat_per_vb):
    """Rough fee for a fanout transaction of n_outputs at sat_per_vb."""
    vsize = 11 + 68 + 31 * (n_outputs + 1)
    return vsize * sat_per_vb / COIN


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    stock, pr3 = sys.argv[1], sys.argv[2]
    report = {"note": "same -maxmempool on both; each build filled with its own maximum size transaction",
              "runs": []}
    for label, binary, n_out in (
        ("stock v31.1, 100 kvB txs", stock, 3200),
        ("PR#3, 975 kvB txs", pr3, 31000),
        ("PR#3, 100 kvB txs (control)", pr3, 3200),
    ):
        print(f"--- {label} ---", flush=True)
        r = run(binary, label, n_out)
        report["runs"].append(r)
        print(json.dumps(r, indent=2), flush=True)
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "results", "exp9_mempool_floor.json")
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
