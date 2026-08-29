# Upstream Microstructure Audit

Date: 2026-08-28

## Finding

The earlier Crypto Multifactor Bot experiments did not test the Harmonic Trader thesis.
They primarily evaluated price-derived factors on Binance spot daily bars. They did not
jointly consume venue-aligned perpetual prices, OI, realized/indicative funding, basis,
taker flow, and observed liquidation state.

That negative evidence is a warning against another price-only experiment, not a reason to
stage one.

## Invalid historical inputs

The published BitMEX funding artifacts are unusable:

- every retained funding rate is numeric zero;
- funding-interval strings are empty;
- raw lineage is insufficient to reconstruct source responses;
- availability and symbol/contract semantics are not adequate for a Binance USD-M study;
  and
- the earlier decisive factor runs did not consume those artifacts anyway.

DATA-011 is also unsuitable for Harmonic Trader research. It is a historically selected
22-name Binance spot daily panel, not the complete perpetual membership, does not carry the
required derivatives state, has no executable short/funding claim, and has already been
exposed to extensive prior research.

Both may document historical defects or support isolated parser fixtures. Neither is an
experiment input, preliminary alpha stage, or fallback.

## Corrective upstream work

Active CEX-002 is acquiring and will publish the complete free Binance USD-M harmonic
bundle:

- historical perpetual membership;
- one-hour perpetual bars and taker flow;
- five-minute open interest;
- realized and indicative funding;
- mark/index basis;
- observed daily liquidation aggregates;
- execution-cost calibration;
- typed coverage/gaps; and
- one immutable bundle descriptor with a clean NautilusTrader catalog-load proof.

CEX-002 has no partial PASS. Bars and microstructure become available to this project
together only after every gate succeeds.

## Architectural consequence

Harmonic Trader has one primary CEX study, not a G1/G2 ladder. The primary representation
combines causal geometry with derivatives state. Geometry-only, microstructure-only, and
classical-pattern variants are same-sample matched ablations needed to identify incremental
value.

Development before release is limited to data-independent semantic contracts, causal
extraction, representations, as-of joins, experiment locks, Nautilus integration fixtures,
and tests. No interim spot backtest or outcome-guided model selection is valid progress.

## DEX distinction

DEX-003 is a separate future research domain. Swap/Sync flow, reserves, pool liquidity, and
AMM costs can support a pool-level geometry study with its own point-in-time universe,
execution model, holdout, and trial ledger. DEX data is not CEX OI, perpetual funding, or
exchange liquidation flow and is never substituted into the CEX study.
