#!/usr/bin/env python3
# Copyright (c) 2026 Tarık İsmet ALKAN
# Distributed under the MIT software license.
"""Experiment 10 - what the weight change does to the orphan pool.

This is a Bitcoin Core functional test, not a standalone script: orphans can
only arrive over P2P, so it needs the test framework. Copy it into a build's
test/functional directory and run it there.

Context. TxOrphanageImpl::AddTx bounds a single orphan by
MAX_STANDARD_TX_WEIGHT, and the comment above that check says why:

    // Ignore transactions above max standard size to avoid a
    // send-big-orphans memory exhaustion attack.

Sitting next to it is the per-peer memory reservation:

    static constexpr int64_t DEFAULT_RESERVED_ORPHAN_WEIGHT_PER_PEER{404'000};

404,000 is MAX_PACKAGE_WEIGHT in stock Core, sized so that one maximum-size
orphan just fits inside a single peer's whole reservation. Raising the weight
ceiling to 3,900,000 without touching the reservation breaks that relationship.
Neither bitcoindogmode/bitcoin#3 nor #4 changes it.

Measured here: the largest orphan a peer can actually get accepted, and what
that is as a multiple of the per-peer reservation.

Usage:
  cp scripts/exp10_orphanage_bound.py <build>/test/functional/
  python3 <build>/test/functional/exp10_orphanage_bound.py
"""

import json
import os

from test_framework.messages import msg_tx
from test_framework.p2p import P2PInterface
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal
from test_framework.wallet import MiniWallet

# Must match DEFAULT_RESERVED_ORPHAN_WEIGHT_PER_PEER in node/txorphanage.h.
RESERVED_PER_PEER = 404_000

# vsize targets to probe, in bytes. 100,000 vB = 400,000 WU is the stock
# ceiling; 975,000 vB = 3,900,000 WU is the proposed one.
PROBES = [50_000, 99_000, 100_000, 100_500, 100_900, 101_000, 300_000, 974_000]


class OrphanageBoundTest(BitcoinTestFramework):
    def set_test_params(self):
        self.setup_clean_chain = True
        self.num_nodes = 1

    def orphan_count(self, node):
        return len(node.getorphantxs())

    def try_orphan(self, node, wallet, target_vsize):
        """Send a child whose parent was never submitted. Return (accepted, weight).

        The node is restarted first. Without that the probes measure cumulative
        per-peer usage rather than the single-transaction ceiling: one peer's
        whole allowance is RESERVED_PER_PEER, so a 199,999 WU orphan left over
        from an earlier probe is already half of it and the next one gets
        trimmed on arrival. An earlier version of this script made exactly that
        mistake and reported the wrong ceiling.
        """
        self.restart_node(0)
        peer = node.add_p2p_connection(P2PInterface())
        assert_equal(self.orphan_count(node), 0)
        parent = wallet.create_self_transfer()
        child = wallet.create_self_transfer(
            utxo_to_spend=parent["new_utxo"], target_vsize=target_vsize)
        weight = child["tx"].get_weight()
        peer.send_and_ping(msg_tx(child["tx"]))
        accepted = self.orphan_count(node) > 0
        node.disconnect_p2ps()
        return accepted, weight

    def run_test(self):
        node = self.nodes[0]
        wallet = MiniWallet(node)
        self.generate(wallet, 200)

        results = []
        for target in PROBES:
            accepted, weight = self.try_orphan(node, wallet, target)
            results.append({
                "target_vsize": target,
                "weight": weight,
                "accepted_into_orphanage": accepted,
                "multiple_of_per_peer_reservation": round(weight / RESERVED_PER_PEER, 2),
            })
            self.log.info(
                f"vsize~{target} weight={weight} accepted={accepted} "
                f"({weight / RESERVED_PER_PEER:.2f}x per-peer reservation)")

        accepted = [r for r in results if r["accepted_into_orphanage"]]
        largest = max(accepted, key=lambda r: r["weight"]) if accepted else None

        report = {
            "reserved_per_peer_weight": RESERVED_PER_PEER,
            "probes": results,
            "largest_accepted_orphan_weight": largest["weight"] if largest else None,
            "largest_as_multiple_of_reservation":
                largest["multiple_of_per_peer_reservation"] if largest else None,
            "orphan_pool_size_at_end": self.orphan_count(node),
        }
        out = os.environ.get("EXP10_OUT", "exp10_orphanage_bound.json")
        with open(out, "w") as fh:
            json.dump(report, fh, indent=2)
        self.log.info(f"wrote {out}")


if __name__ == "__main__":
    OrphanageBoundTest(__file__).main()
