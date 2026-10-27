# Harmonic Trader

Research and strategy code for discovering whether causal price geometry has incremental
trading value when conditioned on the leverage and forced-flow state of Binance USD-M
perpetual markets.

The primary hypothesis is not price-only technical analysis. A valid experiment requires
the complete, venue-aligned CEX-002 release: perpetual bars, taker flow, open interest,
realized and indicative funding, mark/index basis, observed liquidations, historical
membership, execution-cost calibration, and typed coverage gaps. Geometry-only is retained
solely as a matched ablation inside that complete experiment.

## Read the existing exchange data

HT-004 adds a reader for all eleven published CEX-002 datasets and delivers selected
market rows to real NautilusTrader callbacks. It reads the original files in place.
Set `CEX002_ROOT` to the directory containing the published `data/` tree, then run from
this repository with the existing pinned Nautilus environment:

```bash
PYTHONPATH=src .venv/bin/python -m harmonic_trader.cex002 --root "$CEX002_ROOT" inventory
PYTHONPATH=src .venv/bin/python -m harmonic_trader.cex002 --root "$CEX002_ROOT" rows --product binance_usdm_bar_1h --symbol BTCUSDT --month 2025-09 --component '' --limit 3
PYTHONPATH=src .venv/bin/python -m harmonic_trader.cex002 --root "$CEX002_ROOT" nautilus --product binance_usdm_bar_1h --symbol BTCUSDT --month 2025-09 --clock-policy event_time_assumption --limit 24
```

The Python API is `harmonic_trader.data.cex002.Cex002ReleaseReader`; `iter_rows` and
`iter_batches` stream the selected files without the CLI's display limit. Product names
and components come from `inventory`. Symbol/month filters select declared partitions;
`start_ms` is inclusive and `end_ms` exclusive, in UTC event milliseconds. Gap/reference
rows are accessible as tables; they are not assigned artificial market clocks.

`nautilus` reports counts from actual callbacks, with the first received values.
Source publication times remain unknown. The required `event_time_assumption` flag is an
explicit playback assumption, **not evidence that a historical trading decision could
have known those values then**. Liquidation amounts stay in base-asset units; OI value
stays in provider quote units; unavailable funding rates and fees remain missing.
The reader does not replace the existing stricter research observation classes.

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
