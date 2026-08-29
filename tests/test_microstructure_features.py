from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from harmonic_trader.data.asof import AsOfStateStore, WindowRequirement
from harmonic_trader.data.contracts import (
    BasisObservation,
    FundingKind,
    FundingObservation,
    LiquidationObservation,
    MarketBarObservation,
    ObservationMeta,
    OpenInterestObservation,
    Product,
    ReleaseLineage,
    TradeFlowObservation,
)
from harmonic_trader.discovery.geometry import GeometryVector
from harmonic_trader.discovery.pivots import PivotKind
from harmonic_trader.features.microstructure import (
    FeatureError,
    build_microstructure_vector,
)
from harmonic_trader.features.state import join_multimodal_vector


_SHA = "a" * 64
_INSTRUMENT = "BTCUSDT-PERP"
_EVENTS = (70, 80, 90)


def _meta(
    product: Product,
    event: int,
    *,
    available: int | None = None,
    manifest: str = _SHA,
) -> ObservationMeta:
    return ObservationMeta(
        product=product,
        instrument_id=_INSTRUMENT,
        event_time_us=event,
        source_available_at_us=event if available is None else available,
        retrieved_at_us=1_000,
        lineage=ReleaseLineage(
            f"dataset-{product.value}",
            manifest,
            f"raw-{product.value}-{event}",
        ),
    )


def _observations(
    *, scale: Decimal = Decimal(1), late_event: bool = False
) -> list[
    MarketBarObservation
    | TradeFlowObservation
    | OpenInterestObservation
    | FundingObservation
    | BasisObservation
    | LiquidationObservation
]:
    closes = (Decimal("100"), Decimal("102"), Decimal("101"))
    bar_volumes = (Decimal("1000"), Decimal("1100"), Decimal("1300"))
    flow_totals = (Decimal("100"), Decimal("150"), Decimal("200"))
    taker_buy = (Decimal("40"), Decimal("90"), Decimal("130"))
    oi_values = (Decimal("1000"), Decimal("1100"), Decimal("1250"))
    realized_rates = (Decimal("-0.0001"), Decimal("0.0001"), Decimal("0.0002"))
    indicative_rates = (Decimal("0"), Decimal("0.0002"), Decimal("0.0003"))
    basis_values = (Decimal("0"), Decimal("0.01"), Decimal("0.02"))
    liquidation_long = (Decimal("0"), Decimal("100"), Decimal("300"))
    liquidation_short = (Decimal("0"), Decimal("200"), Decimal("100"))

    result: list[
        MarketBarObservation
        | TradeFlowObservation
        | OpenInterestObservation
        | FundingObservation
        | BasisObservation
        | LiquidationObservation
    ] = []
    for index, event in enumerate(_EVENTS):
        close = closes[index] * scale
        result.extend(
            (
                MarketBarObservation(
                    meta=_meta(Product.MARKET_BAR, event),
                    period_start_us=event - 10,
                    period_end_us=event,
                    open=close,
                    high=close + Decimal(2) * scale,
                    low=close - Decimal(2) * scale,
                    close=close,
                    base_volume=Decimal(10),
                    quote_volume=bar_volumes[index] * scale,
                ),
                TradeFlowObservation(
                    meta=_meta(Product.TRADE_FLOW, event),
                    period_start_us=event - 10,
                    period_end_us=event,
                    total_quote_volume=flow_totals[index] * scale,
                    taker_buy_quote_volume=taker_buy[index] * scale,
                ),
                OpenInterestObservation(
                    meta=_meta(Product.OPEN_INTEREST, event),
                    native_quantity=Decimal(100),
                    base_quantity=Decimal(10),
                    notional_usd=oi_values[index] * scale,
                    conversion_price=close,
                ),
                FundingObservation(
                    meta=_meta(Product.FUNDING_REALIZED, event),
                    kind=FundingKind.REALIZED,
                    rate=realized_rates[index],
                    effective_time_us=event,
                    interval_us=10,
                    positive_rate_long_pays_short=True,
                ),
                FundingObservation(
                    meta=_meta(Product.FUNDING_INDICATIVE, event),
                    kind=FundingKind.INDICATIVE,
                    rate=indicative_rates[index],
                    effective_time_us=event + 10,
                    interval_us=10,
                    positive_rate_long_pays_short=True,
                ),
                BasisObservation(
                    meta=_meta(Product.MARK_INDEX_BASIS, event),
                    mark_price=Decimal(100) * scale * (Decimal(1) + basis_values[index]),
                    index_price=Decimal(100) * scale,
                    basis_ratio=basis_values[index],
                ),
                LiquidationObservation(
                    meta=_meta(Product.LIQUIDATION_OBSERVED, event),
                    period_start_us=event - 10,
                    period_end_us=event,
                    long_liquidation_usd=liquidation_long[index] * scale,
                    short_liquidation_usd=liquidation_short[index] * scale,
                    venue_publication_censored=True,
                ),
            )
        )
    if late_event:
        event = 95
        result.append(
            OpenInterestObservation(
                meta=_meta(Product.OPEN_INTEREST, event, available=105),
                native_quantity=Decimal(100),
                base_quantity=Decimal(10),
                notional_usd=Decimal(1300) * scale,
                conversion_price=Decimal(101) * scale,
            )
        )
    return result


def _requirements() -> tuple[WindowRequirement, ...]:
    return tuple(
        WindowRequirement(product, lookback_us=40, min_observations=3, max_staleness_us=20)
        for product in (
            Product.MARKET_BAR,
            Product.TRADE_FLOW,
            Product.OPEN_INTEREST,
            Product.FUNDING_REALIZED,
            Product.FUNDING_INDICATIVE,
            Product.MARK_INDEX_BASIS,
            Product.LIQUIDATION_OBSERVED,
        )
    )


def _snapshot(*, scale: Decimal = Decimal(1), late_event: bool = False):
    return AsOfStateStore(
        _observations(scale=scale, late_event=late_event)
    ).snapshot(_INSTRUMENT, 100, _requirements())


def _geometry(*, instrument: str = _INSTRUMENT, decision: int = 100) -> GeometryVector:
    return GeometryVector(
        instrument_id=instrument,
        terminal_sequence=5,
        terminal_kind=PivotKind.LOW,
        decision_time_us=decision,
        availability_time_us=decision,
        first_pivot_time_us=10,
        terminal_pivot_time_us=90,
        pivot_sequences=(1, 2, 3, 4, 5),
        direction_normalized=True,
        swing_atr=(Decimal(1), Decimal(-1), Decimal(2), Decimal(-2)),
        log_duration_ratios=(Decimal(0), Decimal(0), Decimal(0)),
        swing_velocity=(Decimal(1), Decimal(-1), Decimal(2), Decimal(-2)),
        retracement_ratios=(Decimal(1), Decimal(2), Decimal(1)),
        terminal_displacement_atr=Decimal(0),
        path_efficiency=Decimal(6),
        terminal_leg_share=Decimal(1) / Decimal(3),
        confirmation_delays=(Decimal(1),) * 5,
    )


def test_builds_complete_label_free_microstructure_block() -> None:
    vector = build_microstructure_vector(_snapshot())
    assert vector.instrument_id == _INSTRUMENT
    assert vector.decision_time_us == 100
    assert vector.availability_time_us == 90
    assert len(vector.feature_items) == 25
    assert len(vector.source_lineages) == 7
    assert len(set(vector.feature_names)) == len(vector.feature_names)
    assert all(value.is_finite() for value in vector.feature_values)
    assert "funding_realized_latest" in vector.feature_names
    assert "funding_indicative_latest" in vector.feature_names


def test_economic_scale_changes_do_not_change_dimensionless_block() -> None:
    base = build_microstructure_vector(_snapshot())
    scaled = build_microstructure_vector(_snapshot(scale=Decimal("1000")))
    assert scaled.feature_names == base.feature_names
    assert tuple(map(float, scaled.feature_values)) == pytest.approx(
        tuple(map(float, base.feature_values))
    )


def test_late_observation_cannot_revise_decision_state() -> None:
    base = build_microstructure_vector(_snapshot())
    extended = build_microstructure_vector(_snapshot(late_event=True))
    assert extended == base


def test_ineligible_snapshot_and_zero_flow_fail_closed() -> None:
    incomplete = AsOfStateStore(_observations()[:-1]).snapshot(
        _INSTRUMENT, 100, _requirements()
    )
    with pytest.raises(FeatureError, match="not primary-eligible"):
        build_microstructure_vector(incomplete)

    observations = _observations()
    for index, observation in enumerate(observations):
        if (
            isinstance(observation, TradeFlowObservation)
            and observation.meta.event_time_us == 90
        ):
            observations[index] = replace(
                observation,
                total_quote_volume=Decimal(0),
                taker_buy_quote_volume=Decimal(0),
            )
    zero_flow = AsOfStateStore(observations).snapshot(
        _INSTRUMENT, 100, _requirements()
    )
    with pytest.raises(FeatureError, match="zero-volume"):
        build_microstructure_vector(zero_flow)


def test_window_cannot_cross_manifest_identities() -> None:
    observations = _observations()
    for index, observation in enumerate(observations):
        if (
            isinstance(observation, OpenInterestObservation)
            and observation.meta.event_time_us == 90
        ):
            observations[index] = replace(
                observation,
                meta=replace(
                    observation.meta,
                    lineage=replace(
                        observation.meta.lineage, manifest_sha256="b" * 64
                    ),
                ),
            )
    snapshot = AsOfStateStore(observations).snapshot(
        _INSTRUMENT, 100, _requirements()
    )
    with pytest.raises(FeatureError, match="crosses dataset or manifest"):
        build_microstructure_vector(snapshot)


def test_multimodal_join_requires_exact_instrument_and_decision() -> None:
    microstructure = build_microstructure_vector(_snapshot())
    combined = join_multimodal_vector(_geometry(), microstructure)
    assert combined.instrument_id == _INSTRUMENT
    assert combined.decision_time_us == 100
    assert combined.feature_names[0].startswith("geometry.")
    assert combined.feature_names[-1].startswith("microstructure.")

    with pytest.raises(FeatureError, match="instruments"):
        join_multimodal_vector(_geometry(instrument="ETHUSDT-PERP"), microstructure)
    with pytest.raises(FeatureError, match="decision times"):
        join_multimodal_vector(_geometry(decision=99), microstructure)
