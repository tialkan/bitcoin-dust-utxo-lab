#!/usr/bin/env python3
"""Experiment 1 - measure the real dust threshold per output type.

Question: DOG Mode proposes lowering the dust limit from the 294-546 sat
range to 1 sat. Does that require a code change, or is it already
reachable with the existing -dustrelayfee runtime option?

Method: binary-search the smallest output value that testmempoolaccept
does not reject with reason "dust", for each standard output type, under
several -dustrelayfee settings. No wallet heuristics involved: the node
itself is the oracle.

Usage: python3 exp1_dust_threshold.py /path/to/bitcoind
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from regtest_env import RegtestNode, RPCError

ADDR_TYPES = {
    "P2PKH (legacy)": "legacy",
    "P2SH-P2WPKH": "p2sh-segwit",
    "P2WPKH (bech32)": "bech32",
    "P2TR (bech32m)": "bech32m",
}

COIN = 100_000_000


def setup(node):
    node.rpc("createwallet", "lab")
    addr = node.rpc("getnewaddress")
    node.rpc("generatetoaddress", 200, addr)
    return addr


def spendable(node):
    utxos = sorted(node.rpc("listunspent", 1), key=lambda u: -u["amount"])
    if not utxos:
        raise RuntimeError("no spendable utxos")
    return utxos[0]


def is_dust(node, utxo, target_addr, change_addr, sats):
    """True if the node rejects a tx carrying an output of `sats` as dust."""
    value = sats / COIN
    change = round(float(utxo["amount"]) - value - 0.0001, 8)
    raw = node.rpc(
        "createrawtransaction",
        [{"txid": utxo["txid"], "vout": utxo["vout"]}],
        [{target_addr: f"{value:.8f}"}, {change_addr: f"{change:.8f}"}],
    )
    signed = node.rpc("signrawtransactionwithwallet", raw)
    res = node.rpc("testmempoolaccept", [signed["hex"]])[0]
    reason = res.get("reject-reason", "")
    return reason == "dust", reason


def find_threshold(node, utxo, target_addr, change_addr, lo=1, hi=2000):
    """Smallest value that is NOT dust. Returns None if even `hi` is dust."""
    dust_hi, _ = is_dust(node, utxo, target_addr, change_addr, hi)
    if dust_hi:
        return None
    dust_lo, _ = is_dust(node, utxo, target_addr, change_addr, lo)
    if not dust_lo:
        return lo
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        d, _ = is_dust(node, utxo, target_addr, change_addr, mid)
        if d:
            lo = mid
        else:
            hi = mid
    return hi


def run(bitcoind, dustrelayfee):
    args = [] if dustrelayfee is None else [f"-dustrelayfee={dustrelayfee}"]
    with RegtestNode(bitcoind, args) as node:
        change_addr = setup(node)
        utxo = spendable(node)
        out = {}
        for label, kind in ADDR_TYPES.items():
            addr = node.rpc("getnewaddress", "", kind)
            out[label] = find_threshold(node, utxo, addr, change_addr)
        return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    bitcoind = sys.argv[1]
    settings = [None, "0.00003000", "0.00000100", "0"]
    report = {}
    for s in settings:
        key = "default (3000 sat/kvB)" if s is None else f"-dustrelayfee={s}"
        print(f"--- {key} ---", flush=True)
        res = run(bitcoind, s)
        report[key] = res
        for label, val in res.items():
            print(f"  {label:<20} min non-dust output = {val} sat")
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "results",
        "exp1_dust_threshold.json",
    )
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
