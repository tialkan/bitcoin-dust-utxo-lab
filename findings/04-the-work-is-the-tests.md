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
- the orphan pool's DoS bounds (`orphanage_tests`), which are sized
  against the standard transaction ceiling
- wallet coin selection's maximum weight (`coinselector_tests`)

Only two of the five are simple constant updates in test expectations.
The `txpackage_tests` and `orphanage_tests` failures are questions
about intended behaviour that a maintainer has to answer before the
tests can be rewritten honestly.

This is the ratio anyone budgeting effort should plan around: the
patch is 3 lines, and it is the smallest part of the job. The rest is
test rework, deciding the side effects in Finding 2, and then carrying
all of it forward across every upstream release, since these files are
among the more actively changed in Core.

Functional tests (`test/functional`) are not included in this run and
will add to the list. That measurement is still to do.
