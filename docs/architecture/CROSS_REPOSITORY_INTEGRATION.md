# Cross-Repository Architecture

Status: governing Harmonic Trader design

Scored execution status: blocked until the complete CEX-002 bundle is accepted

## Decision

`Crypto_Multifactor_Bot` owns source qualification, acquisition, raw provenance,
canonicalization, coverage/gap accounting, immutable publication, and the final
NautilusTrader catalog-load proof for CEX-002.

`Harmonic_Trader` consumes that accepted release read-only and owns:

- causal pivot and event extraction;
- scale-invariant geometry;
- causally joined derivatives-state features;
- unsupervised discovery and matched ablations;
- experiment locks, fold artifacts, and trial accounting; and
- NautilusTrader strategies, backtests, execution assumptions, and result evidence.

The integration boundary is the immutable CEX-002 bundle descriptor plus the bundle's
NautilusTrader catalog. It is not the upstream source checkout, mutable SQLite control
database, a copied data tree, or a custom upstream backtest wheel.

## Required release

One accepted bundle must bind all of these products on Binance USD-M perpetual identities:

1. historical perpetual membership;
2. one-hour perpetual bars;
3. one-hour taker trade flow;
4. five-minute open interest;
5. realized funding events;
6. one-hour indicative funding;
7. one-hour mark/index basis;
8. observed daily long/short liquidation aggregates;
9. execution-cost calibration;
10. typed per-product coverage and gaps; and
11. the harmonic bundle descriptor.

The products remain separate. A consumer may construct an in-memory feature view but may
not publish or treat a mutable, zero-filled wide table as source authority.

There is no price-only release stage. Bars and microstructure become research inputs
together when the complete bundle passes. The old DATA-011 spot panel and quarantined
BitMEX funding artifacts are not inputs to this project.

## Boundary invariants

Every scored run pins:

- bundle id and descriptor hash;
- every dataset, manifest, schema, mapping, and gap-product identity;
- the exact eligible product intersection and historical-membership version;
- Harmonic Trader commit and environment lock;
- NautilusTrader version and catalog serialization version;
- frozen experiment specification and complete trial-ledger identity; and
- prospective holdout boundary and access state.

Readers fail closed if any required identity, product, coverage declaration, unit,
censorship flag, or schema differs. They never resolve `latest`, scan the upstream store,
query the live control database, or write upstream state.

## Internal layers

```text
accepted CEX-002 descriptor + read-only Nautilus catalog
                         |
                         v
             bundle verification/adapters
                         |
                         v
        typed observations + causal availability clock
                         |
             +-----------+-----------+
             |                       |
             v                       v
      confirmed pivots       derivatives state
             |                       |
             v                       v
        geometry block        microstructure block
             +-----------+-----------+
                         |
                         v
          frozen multiview representation/model
                         |
                         v
          sparse decision events + explicit no-signal
                         |
                         v
              NautilusTrader execution
                         |
                         v
       locked artifacts, trial ledger, inference
```

Layer rules:

- storage adapters translate an accepted release into consumer semantic types but do not
  compute research features;
- causal state code may read only observations available by the decision time;
- discovery code never imports labels, forward returns, MFE, MAE, or P&L;
- outcome selection occurs only inside chronological training/validation boundaries;
- Nautilus code consumes frozen signals and owns order/fill/accounting behavior; and
- statistical reporting consumes immutable run artifacts, not mutable model objects.

## Causal clock

Each source record preserves its economic event/effective time, source availability time,
retrieval time, and raw/release identity. Each confirmed pivot preserves both the earlier
extremum time and later confirmation/availability time.

For a pattern event:

```text
source observations available
              <= decision
                   < order submission after declared latency
                         <= first eligible executable fill
                               < exit
```

The decision time is never the extremum time. A realized funding value is not observable
before publication. Indicative funding remains distinguishable from realized funding.
Missing liquidation coverage is not zero flow. Unknown availability blocks the primary
sample unless a source-specific release rule establishes a conservative timestamp.

## Complete-case primary sample

Historical membership is never reduced because a product is missing. For the primary
experiment, an instrument/decision enters only when every required feature family has
authoritative coverage under the frozen lookback. A typed gap excludes that interval from
the primary intersection and remains visible in coverage evidence.

This is not survivorship filtering: membership and exclusions are both retained, and
eligibility is evaluated point in time. Any partial-feature model is a separately
predeclared sensitivity analysis, never an implicit fallback.

## Development before release

Work that can be completed while CEX-002 is downloading includes:

- semantic domain types and strict validators;
- causal pivot and geometry extraction;
- as-of joins and typed missingness;
- feature transformations using deterministic fixtures;
- experiment-lock and trial-ledger serialization;
- Nautilus custom-data and strategy interfaces using contract fixtures; and
- leakage, invariance, accounting, and execution tests.

The final storage adapter is implemented only against the accepted descriptor/schema.
Real event counts may be inspected after release for data-quality parameter feasibility,
without opening outcomes. No alpha, payoff, cluster direction, or holdout result is
inspected before the complete design is frozen.

## NautilusTrader boundary

NautilusTrader is the sole simulation and eventual paper/live engine for this project.
Harmonic Trader does not fork the sibling repository's simulator and does not build a
second portfolio engine.

Before a scored run, integration tests must prove:

- all required native and custom data types round-trip through a clean catalog;
- strategy decisions occur only after all contributing observations are available;
- order submission and fill timestamps obey the declared latency/execution model;
- fees, slippage, funding cashflows, positions, and net P&L reconcile independently;
- missing custom data blocks or suppresses a signal according to the frozen policy; and
- repeated runs from the same lock are artifact-identical apart from declared runtime
  metadata.

Hourly historical data cannot prove intrabar stop/target ordering. The first primary
experiment therefore uses a predeclared execution/holding rule supported by the released
cadence and treats MFE/MAE as diagnostics unless finer authoritative path data exists.

## DEX branch

DEX geometry is a separate future experiment using DEX-003 Swap/Sync/reserve products, a
pool-level point-in-time universe, AMM costs, and its own holdout and trial ledger. DEX data
does not substitute for CEX OI, funding, or liquidation state, and CEX conclusions do not
transfer automatically to DEX execution.

## Rejected alternatives

- standalone price-only G1 followed by microstructure later: tests the wrong thesis and is
  not enabled sooner because CEX-002 releases bars and microstructure together;
- DATA-011 daily spot development backtest: repeats contaminated price-only work on a
  historically selected panel with no executable short/funding claim;
- upstream custom research wheel: duplicates NautilusTrader's role and couples this
  project to unrelated simulator internals;
- sibling source imports or live catalog reads: results depend on mutable state;
- zero-filling unavailable products: converts missing coverage into false economic facts;
- cross-venue funding or liquidation proxies in the primary model: breaks instrument and
  execution coherence; and
- target-conditioned discovery as the first family: lets outcomes shape the searched
  representation before a simpler falsifiable model is evaluated.
