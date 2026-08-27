#!/usr/bin/env python3
"""Experiment 7 - does preferential peering fill its slots at a given density?

Finding 5 left this open because addrman rejects non-routable addresses,
so loopback regtest nodes could not be placed in it. scripts/socks_mapper.py
closes that: peers are addressed as synthetic public IPs (one per /16, since
ThreadOpenConnections allows one automatic outbound peer per IPv4 /16) and a
local SOCKS5 proxy maps them onto the real loopback ports.

Setup per run: `peers` peer nodes, of which `dog_peers` run the patched
build and advertise NODE_DOG_RELAY. One observer node, patched, with its
addrman populated with all peer addresses carrying the correct flags.

Measured: how many of the observer's four reserved slots fill, and how
long it takes.

Note on ordering, which matters for reading the result: the reserved-slot
branch in ThreadOpenConnections sits after the full-relay and block-relay
branches, so the observer fills 8 + 2 ordinary outbound slots first, from
any peer including the signalling ones. Competition for signalling peers
between ordinary and reserved slots is part of what is being measured, not
an artifact.

Usage: python3 exp7_peer_discovery.py /path/to/dog/bitcoind /path/to/stock/bitcoind
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
NODE_DOG_RELAY = 1 << 28
BASE = NODE_NETWORK | NODE_WITNESS
DOG = BASE | NODE_DOG_RELAY

RESERVED_SLOTS = 4
PEERS = 24
OBSERVE_SECONDS = 240
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
                         True, services)

        t0 = time.time()
        timeline = []
        filled_at = None
        while time.time() - t0 < OBSERVE_SECONDS:
            c = conn_types(observer)
            dog_now = c.get("dog-relay", 0)
            timeline.append({"t": round(time.time() - t0, 1),
                             "dog_relay": dog_now,
                             "full_relay": c.get("outbound-full-relay", 0),
                             "block_relay": c.get("block-relay-only", 0)})
            if dog_now >= RESERVED_SLOTS and filled_at is None:
                filled_at = round(time.time() - t0, 1)
                break
            time.sleep(5)

        final = conn_types(observer)
        return {
            "peers": peers,
            "dog_peers": dog_peers,
            "dog_density": round(dog_peers / peers, 3),
            "reserved_slots": RESERVED_SLOTS,
            "dog_slots_filled": final.get("dog-relay", 0),
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
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    dog_bin, stock_bin = sys.argv[1], sys.argv[2]
    report = {"note": "peers reached through a local SOCKS5 mapper; see socks_mapper.py",
              "runs": []}
    for dog_peers in (3, 6, 12, 24):
        print(f"--- {dog_peers}/{PEERS} signalling peers ---", flush=True)
        r = run(dog_bin, stock_bin, dog_peers)
        report["runs"].append(r)
        print(json.dumps({k: r[k] for k in
                          ("dog_density", "dog_slots_filled", "seconds_to_fill",
                           "final_conn_types")}, indent=2), flush=True)
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "results", "exp7_peer_discovery.json")
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
