# Finding 4: the work is the tests, not the constants

Status: measured
Base: Bitcoin Core v31.1

## Method

Two builds of the same tree, identical configuration
(`Release`, `-DBUILD_GUI=OFF -DENABLE_WALLET=ON -DENABLE_IPC=OFF`):

- stock v31.1
- v31.1 with the three-constant patch from Finding 2

`build/bin/test_bitcoin` run on each. A baseline matters: without it,
"19 failures" is an unattributable number.

## Result

Stock v31.1: `*** No errors detected`. The baseline is clean.

Patched: 19 assertion failures across 5 test cases, all of them
attributable to the patch:

| Test case | File |
|---|---|
| `transaction_tests/test_IsStandard` | `src/test/transaction_tests.cpp` |
| `txpackage_tests/package_sanitization_tests` | `src/test/txpackage_tests.cpp` |
| `txpackage_tests/package_validation_tests` | `src/test/txpackage_tests.cpp` |
| `orphanage_tests/DoS_mapOrphans` | `src/test/orphanage_tests.cpp` |
| `coinselector_tests/check_max_selection_weight` | `src/wallet/test/coinselector_tests.cpp` |

Representative failures:

```
transaction_tests.cpp:775: check reason_in == reason has failed [tx-size != ]
txpackage_tests.cpp:160:  check state_too_large.GetRejectReason() == "package-too-large" has failed
                          [package-too-many-transactions != package-too-large]
txpackage_tests.cpp:243:  check GetVirtualTransactionSize(*giant_ptx) > DEFAULT_CLUSTER_SIZE_LIMIT_KVB * 1000 has failed
orphanage_tests.cpp:514:  check orphanage->CountUniqueOrphans() == expected_num_orphans has failed [104 != 105]
coinselector_tests.cpp:1340: check has_coin(result->GetInputSet(), CAmount(50 * COIN)) has failed
```

## Interpretation

The reach is the point. A change described as "one number in
policy.h" propagates into:

- standardness (`transaction_tests`)
- package relay semantics (`txpackage_tests`) - note that the
  `package-too-large` path stops being reachable, because the count
  limit now trips first. That is a behaviour change, not a test that
  needs its expected string updated.
- the orphan pool (`orphanage_tests`), whose test is sized against the
  standard transaction ceiling. I first read this as a DoS bound that the
  change loosens. Measurement says otherwise: see finding 7. The per-peer
  memory reservation binds first and the effective orphan ceiling does not
  move, so this one is a mechanical fix after all
- wallet coin selection's maximum weight (`coinselector_tests`)

Only two of the five are simple constant updates in test expectations.
The `txpackage_tests` failures are questions about intended behaviour
that a maintainer has to answer before the tests can be rewritten
honestly. The `orphanage_tests` one looked like another, but finding 7
measured it and it is not.

This is the ratio anyone budgeting effort should plan around: the
patch is 3 lines, and it is the smallest part of the job. The rest is
test rework, deciding the side effects in Finding 2, and then carrying
all of it forward across every upstream release, since these files are
among the more actively changed in Core.

## Functional tests

Same method: both binaries, same runner invocation, `-j10`, 267 test
files.

Stock v31.1 baseline is not clean on this machine. Two tests fail for
environmental reasons (`interface_http.py`, `tool_utxo_to_sqlite.py`)
and 21 are skipped, mostly macOS-unsupported ZMQ, USDT, IPC and bind
tests. Reporting a raw failure count without that baseline would have
charged those two to the patch.

Patched: 23 failures, of which 21 are attributable to the patch.

The split matters more than the number.

**Eleven are not test failures at all. The node refuses to start.**

```
Error: -maxmempool must be at least 39 MB
```

`feature_fee_estimation`, `mempool_limit`, `mempool_package_rbf`,
`p2p_addr_relay`, `p2p_blocksonly`, `p2p_compactblocks_blocksonly`,
`p2p_feefilter`, `p2p_opportunistic_1p1c`, `p2p_sendtxrcncl`,
`p2p_tx_download`, `rpc_packages`.

Every one of these starts a node with a small `-maxmempool`. Raising
`DEFAULT_CLUSTER_SIZE_LIMIT_KVB` to 975 raises the enforced minimum to
39 MB, and `Flatten()` in `txmempool.cpp` treats it as a fatal
configuration error rather than clamping. Note what this means beyond
the test suite: any operator, deployment script, or CI job that pins a
small mempool stops booting after upgrading. That is a migration
problem, not a test problem, and it is invisible if you only read the
constant diff.

**Ten are genuine policy behaviour changes.**

`mempool_accept`, `mempool_datacarrier`, `mempool_package_limits`,
`mempool_sigoplimit`, `p2p_segwit`, `rpc_psbt`,
`wallet_fundrawtransaction`, `wallet_miniscript`, `wallet_send`,
`wallet_sendall`.

`mempool_datacarrier` failing is direct confirmation of the coupling
predicted in Finding 2: `MAX_OP_RETURN_RELAY` is derived from
`MAX_STANDARD_TX_WEIGHT`, so the default datacarrier limit moved from
100,000 to 975,000 bytes without anyone asking for it. The four wallet
tests failing shows the change reaches past relay policy into coin
selection and funding.

## Revised total

Five unit test cases and 21 functional tests, against a three line
diff. Two of the unit failures and none of the functional ones are
simple expectation updates.
