#!/usr/bin/env python3
"""Experiment 11 - merged PR #3 and PR #10: slot fill and feelers.

Finding 5 measured a port of Libre Relay's preferential peering
(NODE_DOG_RELAY = 1 << 28, connection type "dog-relay"). The merged
implementation (bitcoindogmode/bitcoin@7503240091) uses a different bit
(NODE_DOG_MODE = 1 << 14) and a different connection type name ("dog"),
so experiment 7 cannot be pointed at it unchanged. This script is the
same setup with both parametrised.

PR #10 moves the $DOG Mode choice in ThreadOpenConnections below the feeler
and network-specific choices. Same topology, same densities, run against
both builds, and the observer's feeler and dog connections are counted
from the debug log as well as from getpeerinfo (feelers are too short
lived for polling).

Usage: python3 exp11_merged_vs_pr10.py MERGED_BIN PR10_BIN STOCK_BIN
"""


import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from regtest_env import RegtestNode
from socks_mapper import start as start_proxy

NODE_NETWORK = 1 << 0
NODE_WITNESS = 1 << 3
NODE_DOG_RELAY = 1 << 14
BASE = NODE_NETWORK | NODE_WITNESS
DOG = BASE | NODE_DOG_RELAY

RESERVED_SLOTS = 4
PEERS = 24
OBSERVE_SECONDS = int(os.environ.get("EXP11_SECONDS", "240"))
# Feelers only draw from the "new" table, so a feeler measurement needs TRIED=False.
TRIED = os.environ.get("EXP11_TRIED", "1") == "1"
PEER_PORT_BASE = 41000


def conn_types(node):
    out = {}
    for p in node.rpc("getpeerinfo"):
        out[p["connection_type"]] = out.get(p["connection_type"], 0) + 1
    return out


def run(dog_bin, stock_bin, dog_peers, peers=PEERS):
    """One density point. Returns a result dict."""
    srv, socks_port = start_proxy(PEER_PORT_BASE)
    nodes = []
    try:
        for i in range(1, peers + 1):
            binary = dog_bin if i <= dog_peers else stock_bin
            n = RegtestNode(binary, [
                "-listen=1",
                f"-bind=127.0.0.1:{PEER_PORT_BASE + i}",
                "-dnsseed=0", "-fixedseeds=0", "-discover=0",
            ])
            n.p2p_port = PEER_PORT_BASE + i
            n.start()
            nodes.append(n)

        observer = RegtestNode(dog_bin, [
            "-dnsseed=0", "-fixedseeds=0", "-discover=0", "-listen=0",
            f"-proxy=127.0.0.1:{socks_port}",
            "-debug=net",
        ])
        observer.start()
        nodes.append(observer)

        for i in range(1, peers + 1):
            services = DOG if i <= dog_peers else BASE
            observer.rpc("addpeeraddress", f"51.{i}.0.1", PEER_PORT_BASE + i,
                         TRIED, services)

        t0 = time.time()
        timeline = []
        filled_at = None
        while time.time() - t0 < OBSERVE_SECONDS:
            c = conn_types(observer)
            dog_now = c.get("dog", 0)
            timeline.append({"t": round(time.time() - t0, 1),
                             "dog_relay": dog_now,
                             "full_relay": c.get("outbound-full-relay", 0),
                             "block_relay": c.get("block-relay-only", 0)})
            if dog_now >= RESERVED_SLOTS and filled_at is None:
                filled_at = round(time.time() - t0, 1)
                break
            time.sleep(5)

        final = conn_types(observer)
        feelers = 0
        try:
            with open(os.path.join(observer.datadir, "regtest", "debug.log")) as fh:
                feelers = sum(1 for line in fh if "feeler connection" in line)
        except OSError:
            pass
        return {
            "feeler_attempts_logged": feelers,
            "peers": peers,
            "dog_peers": dog_peers,
            "dog_density": round(dog_peers / peers, 3),
            "reserved_slots": RESERVED_SLOTS,
            "dog_slots_filled": final.get("dog", 0),
            "seconds_to_fill": filled_at,
            "final_conn_types": final,
            "timeline": timeline[-12:],
        }
    finally:
        for n in nodes:
            try:
                n.cleanup()
            except Exception:
                pass
        srv.shutdown()


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    merged_bin, pr10_bin, stock_bin = sys.argv[1:4]
    report = {"note": "merged = bitcoindogmode/bitcoin@7503240091, pr10 = PR #10 head; "
                      "peers reached through a local SOCKS5 mapper",
              "runs": []}
    points = [(24, 3), (24, 12), (24, 24), (6, 6)] if TRIED else [(24, 3), (24, 12)]
    for label, binary in (("merged", merged_bin), ("pr10", pr10_bin)):
        for peers, dog_peers in points:
            print(f"--- {label}: {dog_peers}/{peers} signalling peers ---", flush=True)
            r = run(binary, stock_bin, dog_peers, peers=peers)
            r["build"] = label
            report["runs"].append(r)
            print(json.dumps({k: r[k] for k in
                              ("dog_density", "dog_slots_filled", "seconds_to_fill",
                               "feeler_attempts_logged", "final_conn_types")}), flush=True)
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "results", "exp11_merged_vs_pr10.json" if TRIED else "exp11_feelers_new_table.json")
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
