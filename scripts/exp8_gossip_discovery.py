#!/usr/bin/env python3
"""Experiment 8 - do signalling nodes find each other through gossip?

Experiment 7 measured slot filling starting from an addrman already
populated with the right peers and the right service flags. This asks
the question underneath it: does a node reach that state on its own?

Setup: every node advertises a synthetic public address via -externalip
and is reachable at it through the SOCKS mapper, so self-advertisement
and addr relay carry real, dialable addresses with real service flags.
Nodes bootstrap from a single hub, as they would from a seed node. No
addrman is pre-populated: everything the observer learns, it learns from
gossip.

Measured: how long until the observer's four reserved slots fill, or
whether they fill at all.

Usage: python3 exp8_gossip_discovery.py DOG_BIN STOCK_BIN [peers] [dog_peers] [seconds]
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from regtest_env import RegtestNode
from socks_mapper import start as start_proxy

NODE_DOG_RELAY = 1 << 28
RESERVED_SLOTS = 4
PORT_BASE = 42000
HUB = 1


def peer_args(index, socks_port):
    return [
        "-listen=1",
        f"-bind=127.0.0.1:{PORT_BASE + index}",
        f"-externalip=51.{index}.0.1",
        f"-proxy=127.0.0.1:{socks_port}",
        "-dnsseed=0", "-fixedseeds=0", "-discover=0",
    ]


def conn_types(node):
    out = {}
    for p in node.rpc("getpeerinfo"):
        out[p["connection_type"]] = out.get(p["connection_type"], 0) + 1
    return out


def addrman_signalling(node):
    """How many addresses the node knows that advertise the bit."""
    raw = node.rpc("getrawaddrman")
    total = signalling = 0
    for table in raw.values():
        for entry in table.values():
            total += 1
            if int(entry["services"]) & NODE_DOG_RELAY:
                signalling += 1
    return total, signalling


def run(dog_bin, stock_bin, peers, dog_peers, seconds):
    srv, socks_port = start_proxy(PORT_BASE)
    nodes = []
    try:
        for i in range(1, peers + 1):
            binary = dog_bin if i <= dog_peers else stock_bin
            args = peer_args(i, socks_port)
            if i != HUB:
                args.append(f"-addnode=51.{HUB}.0.1")
            n = RegtestNode(binary, args)
            n.p2p_port = PORT_BASE + i
            n.start()
            # Self-announcement is gated on !IsInitialBlockDownload() in
            # MaybeSendAddr. An empty regtest chain counts as IBD, so without
            # a block nothing ever advertises itself and no gossip happens at
            # all. This cost an hour to find, so it is written down here.
            n.rpc("createwallet", "w")
            n.rpc("generatetoaddress", 1, n.rpc("getnewaddress"))
            nodes.append(n)

        # The observer learns nothing except how to reach the hub.
        observer = RegtestNode(dog_bin, [
            "-listen=0", "-discover=0", "-dnsseed=0", "-fixedseeds=0",
            f"-proxy=127.0.0.1:{socks_port}",
            f"-seednode=51.{HUB}.0.1",
            "-debug=net",
        ])
        observer.start()
        observer.rpc("createwallet", "w")
        observer.rpc("generatetoaddress", 1, observer.rpc("getnewaddress"))
        nodes.append(observer)

        t0 = time.time()
        timeline = []
        filled_at = None
        while time.time() - t0 < seconds:
            time.sleep(15)
            c = conn_types(observer)
            known, signalling = addrman_signalling(observer)
            dog_now = c.get("dog-relay", 0)
            timeline.append({
                "t": round(time.time() - t0),
                "addrman_total": known,
                "addrman_signalling": signalling,
                "dog_relay": dog_now,
                "full_relay": c.get("outbound-full-relay", 0),
            })
            print("  ", json.dumps(timeline[-1]), flush=True)
            if dog_now >= RESERVED_SLOTS and filled_at is None:
                filled_at = round(time.time() - t0)
                break

        known, signalling = addrman_signalling(observer)
        return {
            "peers": peers, "dog_peers": dog_peers,
            "dog_density": round(dog_peers / peers, 3),
            "observed_seconds": round(time.time() - t0),
            "addrman_total_learned": known,
            "addrman_signalling_learned": signalling,
            "dog_slots_filled": conn_types(observer).get("dog-relay", 0),
            "seconds_to_fill": filled_at,
            "final_conn_types": conn_types(observer),
            "timeline": timeline,
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
    peers = int(sys.argv[3]) if len(sys.argv) > 3 else 24
    dog_peers = int(sys.argv[4]) if len(sys.argv) > 4 else 12
    seconds = int(sys.argv[5]) if len(sys.argv) > 5 else 600
    r = run(dog_bin, stock_bin, peers, dog_peers, seconds)
    print(json.dumps({k: r[k] for k in
                      ("dog_density", "addrman_total_learned",
                       "addrman_signalling_learned", "dog_slots_filled",
                       "seconds_to_fill", "final_conn_types")}, indent=2))
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "results", f"exp8_gossip_{dog_peers}of{peers}.json")
    with open(path, "w") as fh:
        json.dump(r, fh, indent=2)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
