# Primary CEX Multimodal Study Design

Status: architecture fixed; numerical freeze pending bundle-blind diagnostics

## Objective

Test whether learned causal price geometry contributes incremental tradable information
when combined with venue-aligned perpetual positioning and forced-flow state. This is one
multimodal Binance USD-M study, not a price study followed by a later data upgrade.

## Entry gate

No real observation enters this study until CEX-002 publishes and accepts its complete
harmonic bundle. The consumer must verify every required product, schema, identity,
coverage/gap declaration, unit convention, censorship flag, and Nautilus catalog
round-trip from the immutable bundle descriptor.

The gate fails if any required product is partial, stale, ambiguous, zero-filled for
missingness, cross-venue, or outside the declared point-in-time contract intersection.

## Candidate event

The event clock starts when a new terminal pivot is causally confirmed on the frozen
Binance USD-M perpetual bar series. The candidate contains the latest alternating pivot
sequence, all contributing source identities, confirmation delay, and the point-in-time
derivatives state available at the decision.

One extractor family, point count, threshold set, and duplicate/overlap policy will be
frozen after bundle-blind event-count and stability diagnostics. No outcome field may be
opened during that feasibility step. Every inspected choice enters the trial census even
if removed for structural reasons.

## Feature blocks

The geometry block captures normalized swing structure, duration, velocity, path
efficiency, terminal displacement, and confirmation delay.

The microstructure block captures:

- 5-minute OI stock/change/acceleration in coherent notional units;
- realized and indicative funding state without conflating their clocks;
- hourly mark/index/premium basis;
- hourly volume and taker imbalance;
- observed daily long/short liquidation state using only published available buckets;
- volatility and contemporaneous volume/liquidity regime; and
- contract age and declared market-state controls that are known point in time.

Cost calibration is reserved for Nautilus execution and stress accounting. The sparse
retrospective calibration sample is not a predictive feature.

All rolling windows end at data available by the decision. The primary sample requires
minimum history and authoritative coverage for every primary block.

## Primary model

Use a transparent multiview baseline before a learned encoder:

1. robust-scale geometry and microstructure blocks independently on training data;
2. normalize each block to a frozen aggregate weight;
3. concatenate the blocks;
4. fit one finite clustering family selected by training-only stability, coverage, and
   unsupervised fit; and
5. freeze cluster assignments before any payoff association is estimated.

The exact initial algorithm, finite hyperparameter set, block weights, and support
thresholds are signed in the numerical freeze. A neural or payoff-conditioned
representation is a later separately budgeted model family.

## Matched ablations

All comparisons use the exact same eligible event rows, outer folds, labels, costs,
portfolio rules, and model capacity where applicable:

| Family | Inputs | Question |
| --- | --- | --- |
| FULL | learned geometry + microstructure | Is the complete thesis tradable? |
| MICRO | microstructure only | Does geometry add information? |
| GEOMETRY | geometry only | Does microstructure add information? |
| CARNEY+MICRO | classical labels + microstructure | Does learned geometry beat named patterns? |
| CARNEY | classical labels only | Do named harmonics work by themselves? |
| NULL | cash/random/simple rules | Is any apparent result above chance and trivial exposure? |

GEOMETRY is an ablation, not a separate development milestone, release, or fallback
strategy.

## Direction and evaluation

Cluster direction is not assumed from the terminal leg. Training outcomes estimate
conditional payoff, inner validation freezes direction and eligibility, and the untouched
outer fold measures the result. Reversal and continuation rules may appear as explicitly
counted controls.

The primary outcome and limited robustness horizons are frozen only after the Nautilus
execution fixture proves the available cadence, latency, fill, funding, and cost semantics.
Portfolio-level net performance and incremental ablation comparisons are the decision
criteria.

## Pre-release implementation plan

Development proceeds in this order without real outcomes:

1. causal pivot extraction and invariance tests;
2. geometry-vector construction and stability tests;
3. typed product observations and causal as-of assembly;
4. multimodal state vectors and complete-case eligibility evidence;
5. immutable experiment lock and trial ledger;
6. Nautilus custom-data round-trip and strategy clock fixtures; and
7. independent execution/accounting reconciliation fixtures.

The accepted CEX-002 descriptor then supplies the storage adapter and bundle-specific
contract tests. Only after those pass is the numerical design frozen and real development
data opened.
