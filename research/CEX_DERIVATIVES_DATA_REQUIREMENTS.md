# Complete CEX Data Requirements

Status: consumer contract aligned with active CEX-002

## Principle

The Harmonic Trader CEX experiment begins with one complete Binance USD-M perpetual
release. Price, leverage, funding, basis, forced flow, membership, and costs must share
coherent contract identities and causal clocks. No smaller price-only or cross-venue proxy
release is a research stage.

Normalized products remain separate and immutable. The experiment lock binds them through
one harmonic bundle descriptor.

## Required products

1. `binance_usdm_perpetual_membership`
2. `binance_usdm_bar_1h`
3. `binance_usdm_trade_flow_1h`
4. `binance_usdm_open_interest_5m`
5. `binance_usdm_funding_realized`
6. `binance_usdm_funding_indicative_1h`
7. `binance_usdm_mark_index_basis_1h`
8. `binance_usdm_liquidation_observed_daily`
9. `binance_usdm_cost_calibration`
10. a typed per-product coverage/gap product
11. `binance_usdm_harmonic_bundle`

The names and semantics follow CEX-002 and its governing ADRs. This repository does not
weaken that ticket's all-or-nothing acceptance.

## Semantic minimum

### Membership

Retain every historically observed USD-M perpetual, including delisted contracts, native
symbol, canonical instrument and contract-version identity, listing/delisting/effective
interval, linear/inverse type, quote and settlement assets, contract multiplier, unit
conversions, and mapping evidence.

### Perpetual bars and taker flow

One-hour OHLCV carries period start/end, source availability, last/mark convention, total
base/quote volume, taker-buy base/quote volume, trade count where authoritative, raw
lineage, and quality state. Taker imbalance is derived causally from proved native
semantics rather than inferred from candle direction.

### Open interest

Five-minute snapshots retain native contract quantity, contract multiplier, base
quantity, USD notional, conversion price and convention, observation/availability/retrieval
times, contract version, raw lineage, and revision state. OI stock and OI change are
distinct consumer features.

### Funding

Realized events and one-hour indicative observations are separate products. Each retains
rate, interval/effective funding time, publication/availability time, long/short cashflow
sign, cap/floor where available, contract identity, raw lineage, and revision state.
Realized funding cashflow applies only to a position held across the event.

### Mark, index, and basis

One-hour observations retain mark, index, premium-index inputs, their identities, period
and availability clocks, and a reproducible basis definition. Cross-venue spot proxies are
not the primary basis.

### Observed liquidations

Daily Coinalyze aggregates retain separate long and short values, source units, USD
conversion evidence, provider/native mapping, period and availability clocks, raw
response identity, and Binance's post-2021 censorship disclosure. Missing provider
coverage is `UNAVAILABLE`, not zero. The product is always called observed rather than
complete liquidation flow.

### Cost calibration

Retain the bounded official book-ticker/depth calibration sample, fee schedule/version,
spread and depth fields, contract/liquidity strata, timestamps, raw lineage, and the
declared interpolation/stress model. It calibrates conservative historical execution; it
does not masquerade as a full historical order book.

## Shared temporal contract

Every economic row or coverage record binds:

- canonical instrument and venue-native symbol;
- contract version/effective interval;
- economic event or period time;
- source availability time when authoritative;
- retrieval time;
- raw object/request and release identities;
- schema, code, and configuration identities; and
- typed quality, revision, censorship, and missingness state.

At decision time `t`, a feature may use a source value only when the product-specific
availability rule proves it observable by `t`. Unknown publication time is not copied
from event time. Joins fail on ambiguous symbols, overlapping versions, duplicate events,
unit disagreement, or undeclared gaps.

## Coverage and release gates

- full historically observed membership remains visible;
- every product has per-contract expected/observed coverage or typed gaps;
- official and secondary-source overlap is reconciled where required;
- units and sign conventions have independent fixtures;
- all-zero, all-null, constant, truncated, duplicate, or mislabeled fields fail;
- raw objects, normalized rows, manifests, gaps, and catalog entries reconcile exactly;
- the bundle declares the full daily intersection and native-cadence products;
- every required native/custom type round-trips through a clean NautilusTrader catalog;
- the descriptor pins every product, manifest, schema, mapping, and coverage identity; and
- a prospective holdout boundary is sealed before Harmonic Trader opens outcomes.

No partial product, smaller panel, invented zero, synthetic substitute, paid-data
assumption, or different venue satisfies the gate.

## Consumer feature families

Harmonic Trader derives, causally and within folds:

- OI level, change, acceleration, and price/notional-normalized state;
- realized and indicative funding level, z-score, and persistence;
- mark/index/premium basis level and change;
- observed long/short liquidation intensity, imbalance, and acceleration;
- taker flow imbalance, volume, volatility, and contemporaneous liquidity regime; and
- price geometry from confirmed perpetual-bar pivots.

Cost-calibration rows parameterize execution and cost stress. They are not predictive
features unless a later release supplies an authoritative point-in-time continuous
liquidity product and a separately frozen model family.

The full model and all ablations use the same accepted bundle and eligible event set.

## Explicitly unnecessary data

Full historical trades, aggregate trades, BBO, and L2 order books are not required for the
first experiment. CEX-002's bounded book calibration supports conservative cost modeling.
Finer path or book data becomes a new requirement only if a later experiment makes claims
about intrabar PRZ fills, stop/target ordering, or market impact that the accepted cadence
cannot identify.
