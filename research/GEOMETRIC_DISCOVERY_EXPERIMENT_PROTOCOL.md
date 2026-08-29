# Multimodal Geometric Discovery Experiment Protocol

Status: governing protocol; numerical experiment freeze remains pending

Scored execution status: blocked on the complete accepted CEX-002 release

## Research question

Do causally observable price geometries add net predictive and trading value when combined
with contemporaneously available leverage, funding, basis, forced-flow, liquidity, and
volatility state in Binance USD-M perpetual markets?

The thesis is an interaction: geometry describes the path while derivatives
microstructure describes the positioning and flow capable of making that path resolve
asymmetrically. Price geometry in isolation is not the proposed strategy.

## Primary hypotheses

The first scored family tests all four claims on identical eligible events, folds, labels,
costs, and execution rules:

- `H1`: the full geometry-plus-microstructure model has positive net performance and
  survives the declared family-wise correction;
- `H2`: the full model improves on its geometry-only ablation, establishing incremental
  value from derivatives state;
- `H3`: the full model improves on its microstructure-only ablation, establishing
  incremental value from geometry; and
- `H4`: learned geometry improves on classical harmonic labels under the same
  microstructure context.

Failure of any incremental claim is reported directly. A profitable microstructure-only
model is not evidence for harmonic discovery. A profitable geometry-only control is not
permission to ignore the primary data contract.

## Required data

Every scored event comes from one accepted CEX-002 bundle containing the eleven products
listed in [the data requirements](CEX_DERIVATIVES_DATA_REQUIREMENTS.md). All streams use
the same Binance USD-M contract identities and point-in-time membership.

The primary sample is the point-in-time intersection with authoritative coverage for:

- perpetual OHLCV and taker flow;
- open-interest level/change;
- realized and indicative funding;
- mark/index basis;
- observed liquidation flow under its censorship label;
- cost-calibration stratum; and
- every feature's frozen historical lookback.

Gaps stay typed. They do not become zeros and do not remove the contract from membership.
The exact inclusion/exclusion ledger is an experiment artifact.

## Observation and causal clock

One candidate event is the most recent frozen number of alternating, confirmed pivots for
one perpetual contract. Every pivot stores:

- extremum bar and time;
- later confirmation bar and time;
- source availability and decision time;
- lagged volatility scale used for confirmation; and
- immutable extractor/configuration identity.

Geometry may use the known earlier extremum locations only after confirmation. Every
microstructure input must have `source_available_at <= decision_time`. Product-specific
rules distinguish observation time, effective time, and publication time, especially for
funding. Rolling transforms are fitted or updated causally.

Trading begins only after decision computation and declared latency. Entry/fill behavior is
implemented and reconciled in NautilusTrader. No same-close fill or retrospective
extremum-time decision is allowed.

## Representation

The primary representation has two explicit blocks.

### Geometry block

- signed swing sizes in lagged-volatility units;
- swing durations and clipped log-duration ratios;
- swing velocities;
- retracement/extension ratios with declared denominator floors;
- terminal displacement;
- path length relative to net displacement;
- terminal-leg share and direction; and
- confirmation delays.

Price-scale and time-origin invariance are tested. Direction normalization, pivot count,
and threshold choices are frozen and counted before outcome inspection.

### Microstructure block

- OI level, change, acceleration, and price/notional-normalized change;
- realized and indicative funding level, persistence, and causal z-score;
- mark/index and premium basis level/change;
- long/short observed-liquidation intensity, imbalance, and acceleration;
- total/taker-buy flow imbalance and volume regime;
- volatility and contemporaneous volume/liquidity regime; and
- explicit censorship and data-quality state allowed by the frozen primary policy.

Each transform names its physical units, lookback, denominator, winsorization, minimum
history, and missingness rule. Scalers are fit inside training only. Geometry and
microstructure blocks are scaled separately and receive predeclared block weights so the
larger block cannot dominate merely by dimension count.

## Discovery and controls

The first family is unsupervised with respect to future returns. Labels, MFE, MAE, fills,
and P&L do not enter feature construction, scaling, distance, clustering, or cluster-count
selection.

The frozen candidate set contains:

- `FULL`: joint geometry and microstructure representation;
- `MICRO`: identical events and model class using only the microstructure block;
- `GEOMETRY`: identical events and model class using only the geometry block;
- `CARNEY+MICRO`: frozen classical harmonic indicators with the same microstructure
  block;
- `CARNEY`: classical harmonic control alone;
- simple continuation/reversal, unconditional, sign-reversed, random-label, and cash
  controls.

The initial clustering class and finite hyperparameter grid are chosen using only
training-set stability, support, coverage, and unsupervised diagnostics. Target-conditioned
metric learning, density clustering, and neural sequence models are later separately
counted families, not rescue paths chosen after a failed outer result.

After a model is frozen inside a fold, cluster payoff estimates use training outcomes and
direction/eligibility selection uses the inner chronological validation segment. The
outer segment is touched once.

## Chronological evaluation

For every outer fold:

1. Generate point-in-time membership, confirmed pivots, and causal source observations.
2. Build the exact complete-case eligibility ledger.
3. Purge observations whose feature or label intervals cross a boundary.
4. Embargo at least the maximum label horizon and persistent feature lookback that can
   carry information across the boundary.
5. Fit transforms and candidate models on training only.
6. Select model settings using unsupervised training criteria.
7. Estimate cluster payoff state on training outcomes.
8. Freeze signal direction and support rules on inner validation.
9. Emit signals and explicit no-signal decisions for the untouched outer segment.
10. Execute the frozen events in NautilusTrader and seal all artifacts before analysis.

Cluster identities are fold-local. Cross-fold shape comparisons use frozen
centroid/medoid matching rather than assuming numeric labels are stable.

## Execution and outcomes

The numerical freeze declares one primary holding/execution rule that the released cadence
can support, plus limited predeclared robustness horizons. It must specify:

- signal computation latency and first eligible order time;
- order type and fill model;
- position sizing, gross and per-instrument caps;
- overlap and concurrent-signal handling;
- fees, spread, slippage/impact, funding, and liquidation accounting;
- delisting, gaps, missing bars, and unfilled orders; and
- exit and end-of-data behavior.

Primary inference uses the net portfolio return series. Forward returns, MFE, MAE, and
time-to-excursion may diagnose cluster behavior but cannot be called executable stop/target
results when hourly bars do not establish intrabar ordering.

Every period independently reconciles gross P&L, turnover, fees, slippage, funding,
realized/unrealized P&L, positions, cash, and net equity.

## Statistical control

The immutable trial ledger includes every inspected pivot rule, point count, feature
variant, lookback, transform, block weight, clustering setting, support threshold,
direction rule, horizon, cost case, universe rule, and model family.

Inference is portfolio-level. Report block-bootstrap confidence intervals, fold and regime
sign consistency, concentration by asset/date/cluster, and a family-wide SPA/reality-check
style result. Deflated Sharpe is reported only with the effective trial count and return
moments. Event-row significance that ignores dependence is not primary evidence.

## Holdout and advancement

All history already accessible before the model freeze is development or pseudo-out-of-
sample data. CEX-002 pins a prospective boundary before outcomes are inspected. The sealed
holdout is opened once only after:

- the complete bundle and consumer adapter pass;
- feature and model families are frozen;
- all development trials are recorded;
- Nautilus execution and accounting reconcile; and
- advancement criteria are signed without seeing holdout outcomes.

Promotion requires positive net performance, survival at the stressed cost case,
consistent major-fold sign, distributed support, no dominant asset/period/cluster,
improvement over both principal ablations and classical controls, family-wise survival,
and exact locked reproduction. No result authorizes PAPER or LIVE without separate risk
and operational work.

## Work allowed before CEX-002 release

- semantic contracts and validators;
- causal pivots and geometry;
- causal as-of state assembly and missingness gates;
- representation code using deterministic fixtures;
- experiment-lock and trial-ledger code;
- Nautilus custom-data, strategy, and accounting integration using contract fixtures; and
- leakage, invariance, execution, and reproducibility tests.

Forbidden before release: adapting to an interim spot dataset, inspecting real alpha,
choosing settings from returns, fabricating unavailable microstructure, or describing any
price-only run as progress toward the primary hypothesis.

## Separate DEX experiment

DEX-003 supports a future pool-level question with Swap/Sync/reserve state, AMM execution,
pool membership, its own experiment lock, and its own holdout. It is neither an input nor a
fallback for the CEX study.
