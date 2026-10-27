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

## Check historical contracts before projecting bars

HT-005 adds a separately pinned contract-history file. It distinguishes relaunches and
reused tickers, reports where a row falls relative to launch/restriction/settlement, and
uses a separate Nautilus instrument identity for each recovered contract episode.
The original market files and funding observations remain available.

Set `CEX002_HISTORY` to the generated companion and `CEX002_HISTORY_SHA` to its reviewed
SHA-256. Supply a UTC research knowledge time at or after the companion's `known_from`.
The current reviewed companion can be selected as follows; then inspect the closure month
without discarding any source rows:

```bash
CEX002_HISTORY="$CEX002_ROOT/data/.cex002_contract_history/review529-20261027.json"
CEX002_HISTORY_SHA="6ef47558eff2b3d3b30fbd8569dd96e0f7b7863bd8b310025cf641f7e72034a9"
CEX002_KNOWLEDGE_TIME="2026-10-27T18:20:52Z"
PYTHONPATH=src .venv/bin/python -m harmonic_trader.cex002 --root "$CEX002_ROOT" rows \
  --product binance_usdm_bar_1h --symbol ANCBUSD --month 2022-12 --component '' \
  --history "$CEX002_HISTORY" --history-sha "$CEX002_HISTORY_SHA" \
  --knowledge-time "$CEX002_KNOWLEDGE_TIME" --limit 3
```

Use the same history options with `nautilus`, plus
`--clock-policy event_time_assumption --reference-policy reviewed_notices_assumption`.
That path refuses an hourly bar outside a known unrestricted episode or crossing a
boundary. It also refuses unknown histories and mixed-episode bar batches, rather than
silently omitting rows. The `rows` command still shows those observations and their
classification. Funding annotations never establish payment entitlement.

The current companion covers 782 contract episodes across 770 symbols. Five contracts
(BTCUSDT, ETHUSDT, BCHUSDT, XRPUSDT and ARBUSDT) have a documented confirmed-active start
instead of an invented exact launch time. Earlier intervals are `before_confirmed_active`
and remain accessible through `rows`; native Bars are refused there. GAIBUSDT is explicitly
postponed, is pending in the retained snapshot, and has no bar partitions.

For example, after setting the three history variables above, deliver one stored BTC bar:

```bash
PYTHONPATH=src .venv/bin/python -m harmonic_trader.cex002 --root "$CEX002_ROOT" nautilus \
  --product binance_usdm_bar_1h --symbol BTCUSDT --month 2019-12 --component '' --limit 1 \
  --history "$CEX002_HISTORY" --history-sha "$CEX002_HISTORY_SHA" \
  --knowledge-time "$CEX002_KNOWLEDGE_TIME" --clock-policy event_time_assumption \
  --reference-policy reviewed_notices_assumption
```

All historical contract specifications remain incomplete. Binance permits some order
thresholds to change without announcements; present API limits cannot be assigned to past
dates. These callbacks demonstrate data delivery and dated selection, not order execution,
margin calculations or fills.

The Python API is `ContractHistory`, `annotate_row` and `iter_history_rows` in
`harmonic_trader.data.cex002_history`. Native `native_bar`/`deliver_to_nautilus` accept
`history`, `knowledge_time`, `reference_policy` and the matching `publication_sha256`.
The companion preserves incomplete-history flags; exact launches carry launch-only terms,
and confirmed-active records do not invent them. Using
today's recovered notices is retrospective reconstruction; it does not establish what
was known at a historical trading decision. Omitting the history file retains HT-004's
explicitly unqualified event-time transport.

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
