# Harmonic Trader

Research and strategy code for discovering whether causal price geometry has incremental
trading value when conditioned on the leverage and forced-flow state of Binance USD-M
perpetual markets.

The primary hypothesis is not price-only technical analysis. A valid experiment requires
the complete, venue-aligned CEX-002 release: perpetual bars, taker flow, open interest,
realized and indicative funding, mark/index basis, observed liquidations, historical
membership, execution-cost calibration, and typed coverage gaps. Geometry-only is retained
solely as a matched ablation inside that complete experiment.

## Current state

The sibling `Crypto_Multifactor_Bot` repository owns acquisition, normalization,
reconciliation, and immutable publication of the CEX-002 data bundle. This repository owns
causal event extraction, representations, model discovery, experiment definitions, and
NautilusTrader strategy/backtest integration.

No scored study is authorized before the complete CEX-002 bundle passes its release gates.
Development that does not require real outcomes continues against consumer-owned semantic
contracts and deterministic fixtures. The first implemented component is the online,
lagged-ATR directional-change pivot detector in
`harmonic_trader.discovery.pivots`.

See:

- [cross-repository architecture](docs/architecture/CROSS_REPOSITORY_INTEGRATION.md);
- [primary CEX study design](research/PRIMARY_CEX_STUDY_DESIGN.md);
- [experiment protocol](research/GEOMETRIC_DISCOVERY_EXPERIMENT_PROTOCOL.md); and
- [complete data contract](research/CEX_DERIVATIVES_DATA_REQUIREMENTS.md).

The legacy automation scripts remain at repository root while useful logic is replaced by
tested package interfaces. They are not an experiment implementation or evidence.
