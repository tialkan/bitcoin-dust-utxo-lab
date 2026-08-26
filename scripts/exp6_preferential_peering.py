#!/usr/bin/env python3
"""Experiment 6 - preferential peering: what can and cannot be measured.

The third announced DOG Mode change is preferential peering, adapted
from Libre Relay (petertodd/bitcoin, libre-relay-v30.0, commit 66518db).
The mechanism there is:

  - advertise a service bit (NODE_LIBRE_RELAY = 1 << 29)
  - reserve 4 dedicated outbound slots for peers advertising it
  - drop such a peer at handshake if it does not advertise the bit

This script tests the parts that a single-host regtest can actually
answer, and is explicit about the part it cannot.

  6a. Does a node advertise the service bit at all?
  6b. Does a reserved-slot connection between two signalling nodes
      establish and stay up, with the expected connection type?
  6c. Is the handshake check real? A reserved-slot connection aimed at
      a node that does not signal should be dropped.
  6d. What does reserving those slots cost? The reserved outbound slots
      are added to m_max_automatic_outbound, and m_max_inbound is
      derived by subtraction, so a node with an unchanged
      -maxconnections should accept fewer inbound peers.

NOT measured here, and the reason:

  Whether nodes running this actually find each other on a real network.
  Peer selection is not a service-filtered addrman Select(); it picks an
  address and does `continue` if the bit is missing, giving up after 100
  tries. Testing that end to end needs an addrman full of reachable
  peers at a known density. addrman rejects non-routable addresses
  (addrman.cpp, AddSingle), so loopback regtest nodes cannot be injected,
  and synthetic routable addresses have nothing listening behind them.
  On a single host there is no honest way to run that experiment, so it
  is left open rather than approximated.

Usage: python3 exp6_preferential_peering.py /path/to/dogpeer/bitcoind /path/to/stock/bitcoind
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from regtest_env import RegtestNode

NODE_DOG_RELAY = 1 << 28
EXPECTED_SLOTS = 4


def local_services(node):
    return int(node.rpc("getnetworkinfo")["localservices"], 16)


def conn_types(node):
    out = {}
    for p in node.rpc("getpeerinfo"):
        out[p["connection_type"]] = out.get(p["connection_type"], 0) + 1
    return out


def addr_of(node):
    return f"127.0.0.1:{node.p2p_port}"


def test_6a(dog, stock):
    return {
        "dog_build_advertises_bit": bool(local_services(dog) & NODE_DOG_RELAY),
        "stock_build_advertises_bit": bool(local_services(stock) & NODE_DOG_RELAY),
        "dog_localservices_hex": hex(local_services(dog)),
    }


def test_6b(dog_a, dog_b):
    dog_a.rpc("addconnection", addr_of(dog_b), "dog-relay", False)
    time.sleep(3)
    types = conn_types(dog_a)
    return {"connection_types_on_initiator": types,
            "dog_relay_connection_established": types.get("dog-relay", 0) == 1}


def peer_addrs(node):
    return {p["addr"] for p in node.rpc("getpeerinfo")}


def test_6c(dog, stock):
    """A reserved-slot connection to a non-signalling node must be dropped.

    Checked per peer address, not by counting connection types: the
    initiator already holds a legitimate dog-relay connection from 6b,
    so an aggregate count cannot tell the two apart.
    """
    target = addr_of(stock)
    before = peer_addrs(dog)
    try:
        dog.rpc("addconnection", target, "dog-relay", False)
    except Exception as e:
        return {"error": str(e)}
    seen_connected = False
    dropped = False
    for _ in range(20):
        time.sleep(0.5)
        addrs = peer_addrs(dog)
        if target in addrs:
            seen_connected = True
        elif seen_connected:
            dropped = True
            break
    return {"target": target,
            "peers_before": sorted(before),
            "peers_after": sorted(peer_addrs(dog)),
            "connection_was_observed": seen_connected,
            "non_signalling_peer_dropped": dropped or target not in peer_addrs(dog),
            "surviving_conn_types": conn_types(dog)}


def measure_inbound_ceiling(binary, maxconnections, probes=40):
    """Occupy inbound slots with raw TCP sockets and read the ceiling off.

    The inbound ceiling is not exposed over RPC. It does not need to be:
    a bare accepted TCP connection already occupies a slot, so opening
    sockets until connections_in stops rising measures it directly.
    """
    import socket
    args = [f"-maxconnections={maxconnections}", "-listen=1", "-discover=0",
            "-dnsseed=0", "-fixedseeds=0"]
    socks = []
    with RegtestNode(binary, args) as n:
        peak = 0
        for _ in range(probes):
            try:
                s = socket.create_connection(("127.0.0.1", n.p2p_port), timeout=5)
                socks.append(s)
            except OSError:
                break
            time.sleep(0.05)
            try:
                peak = max(peak, n.rpc("getnetworkinfo")["connections_in"])
            except Exception:
                pass
        time.sleep(1)
        try:
            final = n.rpc("getnetworkinfo")["connections_in"]
        except Exception:
            final = peak
        for s in socks:
            try:
                s.close()
            except OSError:
                pass
        return {"maxconnections": maxconnections,
                "sockets_opened": len(socks),
                "peak_connections_in": peak,
                "final_connections_in": final}


def test_6d(dog_bin, stock_bin, maxconnections=20):
    """Reserved outbound slots are subtracted from inbound capacity."""
    out = {}
    for label, binary in (("stock", stock_bin), ("dog", dog_bin)):
        out[label] = measure_inbound_ceiling(binary, maxconnections)
    out["expected_difference"] = EXPECTED_SLOTS
    out["observed_difference"] = (out["stock"]["peak_connections_in"]
                                  - out["dog"]["peak_connections_in"])
    out["note"] = ("m_max_inbound is max_automatic_connections minus automatic "
                   "outbound, and the reserved slots are part of that "
                   "subtraction. See CConnman::Init in net.h.")
    return out


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    dog_bin, stock_bin = sys.argv[1], sys.argv[2]
    report = {}
    dog_a = RegtestNode(dog_bin, ["-listen=1", "-discover=0", "-dnsseed=0"]).start()
    dog_b = RegtestNode(dog_bin, ["-listen=1", "-discover=0", "-dnsseed=0"]).start()
    stock = RegtestNode(stock_bin, ["-listen=1", "-discover=0", "-dnsseed=0"]).start()
    try:
        report["6a_service_bit"] = test_6a(dog_a, stock)
        print("6a:", json.dumps(report["6a_service_bit"]), flush=True)
        report["6b_reserved_slot_connection"] = test_6b(dog_a, dog_b)
        print("6b:", json.dumps(report["6b_reserved_slot_connection"]), flush=True)
        report["6c_handshake_enforcement"] = test_6c(dog_a, stock)
        print("6c:", json.dumps(report["6c_handshake_enforcement"]), flush=True)
    finally:
        for n in (dog_a, dog_b, stock):
            n.cleanup()
    report["6d_inbound_cost"] = test_6d(dog_bin, stock_bin)
    print("6d:", json.dumps(report["6d_inbound_cost"], indent=2), flush=True)
    report["not_measured"] = ("peer discovery at a given adoption rate; see "
                              "module docstring for why a single host cannot "
                              "answer it honestly")
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "results", "exp6_preferential_peering.json")
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
