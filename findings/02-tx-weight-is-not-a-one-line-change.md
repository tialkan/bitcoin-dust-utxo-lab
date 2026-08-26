# Finding 2: raising the max standard tx weight is not a one-constant change

Status: measured, reproducible via `scripts/exp2_weight_and_cluster.py`
and `scripts/exp4_patched_large_tx.py`
Base: Bitcoin Core v31.1
Raw data: `results/exp2_weight_and_cluster.json`,
`results/exp4_patched_large_tx.json`

## Claim under test

Bitcoin DOG Mode proposes raising the maximum standard transaction size
from 400,000 WU to 3,900,000 WU. Read plainly, that is one constant:
`MAX_STANDARD_TX_WEIGHT` in `src/policy/policy.h`.

## Step 1: confirm the stock ceiling

Growing a single transaction output by output against stock v31.1:

| n_outputs | weight  | vsize   | accepted | reason  |
|-----------|---------|---------|----------|---------|
| 3222      | 399,973 | 99,994  | yes      |         |
| 3223      | 400,097 | 100,025 | no       | tx-size |

The ceiling is exactly `MAX_STANDARD_TX_WEIGHT`, as expected.

## Step 2: change the one constant

Setting `MAX_STANDARD_TX_WEIGHT{3900000}` and rebuilding fails to
compile. `src/policy/packages.h:25` carries a compile-time guard:

```
static_assert(MAX_PACKAGE_WEIGHT >= MAX_STANDARD_TX_WEIGHT);
// error: expression evaluates to '404000 >= 3900000'
```

Bitcoin Core refuses to build a node whose standardness ceiling exceeds
its package weight ceiling. This is not an oversight to be patched
around; it encodes an invariant.

## Step 3: follow the chain

Raising `MAX_PACKAGE_WEIGHT` to 3,900,000 hits the next assertion, four
lines down in the same file:

```
static_assert(MAX_PACKAGE_WEIGHT <= DEFAULT_CLUSTER_SIZE_LIMIT_KVB * WITNESS_SCALE_FACTOR * 1000);
```

With `DEFAULT_CLUSTER_SIZE_LIMIT_KVB{101}` the right-hand side is
404,000. Satisfying it requires `DEFAULT_CLUSTER_SIZE_LIMIT_KVB >= 975`.

The minimal patch that compiles is therefore three coupled constants:

| Constant | v31.1 | required |
|---|---|---|
| `MAX_STANDARD_TX_WEIGHT` (`policy.h`) | 400,000 | 3,900,000 |
| `MAX_PACKAGE_WEIGHT` (`packages.h`) | 404,000 | >= 3,900,000 |
| `DEFAULT_CLUSTER_SIZE_LIMIT_KVB` (`policy.h`) | 101 | >= 975 |

## Step 4: verify at runtime

With all three raised, a single transaction with no unconfirmed parents:

| n_outputs | weight    | vsize   | accepted | reason  |
|-----------|-----------|---------|----------|---------|
| 31,400    | 3,894,045 | 973,512 | yes      |         |
| 31,500    | 3,906,445 | 976,612 | no       | tx-size |

The change works, once it is made correctly.

## Why the cluster limit matters, empirically

v31.1 replaced ancestor/descendant size limits with cluster size limits.
`-limitancestorsize` and `-limitdescendantsize` are now no-ops that emit
a startup warning. The cluster limit is enforced and is easy to hit:

| | vsize |
|---|---|
| parent | 93,112 |
| child (spends parent) | 93,112 |
| combined cluster | 186,224 |
| `DEFAULT_CLUSTER_SIZE_LIMIT_KVB * 1000` | 101,000 |

The child is rejected with `too-large-cluster`. Any published guidance
that still points at `-limitancestorsize` for this is out of date for
v31.1.

## Two side effects the announcement does not mention

1. `MAX_OP_RETURN_RELAY` is defined as
   `MAX_STANDARD_TX_WEIGHT / WITNESS_SCALE_FACTOR` (`policy.h:83`) and
   feeds the default of `max_datacarrier_bytes`
   (`kernel/mempool_options.h:53`). Raising the weight constant to
   3,900,000 silently raises the default OP_RETURN datacarrier limit
   from 100,000 to 975,000 bytes. That may well be intended, but it is
   a second policy change riding along on the first, and it should be
   stated rather than inherited.

2. `src/txmempool.cpp` (`Flatten`) requires
   `-maxmempool >= cluster_size_vbytes * 40`. At
   `DEFAULT_CLUSTER_SIZE_LIMIT_KVB = 975` the minimum `-maxmempool`
   becomes 39 MB, up from about 4 MB. It sits below the 300 MB default,
   so a node started with default settings is unaffected.

   An earlier version of this document called that "not a blocker".
   That understated it, and Finding 4 shows why: a node given a smaller
   `-maxmempool` does not warn and fall back, it refuses to start with
   `Error: -maxmempool must be at least 39 MB`. Eleven functional tests
   fail on that alone, before any policy behaviour is exercised. Any
   operator, test harness, or CI job that pins a small mempool breaks
   outright.

## What this means for the project

The work is not the constant. The work is the invariant chain, the side
effects, and the tests, which is Finding 4.
