from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from harmonic_trader.data.asof import (
    AsOfStateStore,
    EligibilityCode,
    StateError,
    WindowRequirement,
)
from harmonic_trader.data.contracts import (
    BasisObservation,
    ContractError,
    CoverageGap,
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


_SHA = "a" * 64
_INSTRUMENT = "BTCUSDT-PERP"


def _meta(
    product: Product,
    event: int,
    *,
    available: int | None = None,
    instrument: str = _INSTRUMENT,
) -> ObservationMeta:
    return ObservationMeta(
        product=product,
        instrument_id=instrument,
        event_time_us=event,
        source_available_at_us=event if available is None else available,
        retrieved_at_us=1_000,
        lineage=ReleaseLineage("dataset", _SHA, f"raw-{product.value}-{event}"),
    )


def _unknown_meta(product: Product, event: int) -> ObservationMeta:
    return replace(_meta(product, event), source_available_at_us=None)


def _oi(
    event: int,
    *,
    available: int | None = None,
    instrument: str = _INSTRUMENT,
) -> OpenInterestObservation:
    return OpenInterestObservation(
        meta=_meta(
            Product.OPEN_INTEREST,
            event,
            available=available,
            instrument=instrument,
        ),
        native_quantity=Decimal("100"),
        base_quantity=Decimal("10"),
        notional_usd=Decimal("1000"),
        conversion_price=Decimal("100"),
    )


def test_market_bar_contract_preserves_release_clock_and_units() -> None:
    bar = MarketBarObservation(
        meta=_meta(Product.MARKET_BAR, 20, available=21),
        period_start_us=10,
        period_end_us=20,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        base_volume=Decimal("2"),
        quote_volume=Decimal("205"),
    )
    assert bar.meta.source_available_at_us == 21
    assert bar.high == Decimal("110")


def test_trade_flow_zero_is_observed_but_ratio_is_undefined() -> None:
    flow = TradeFlowObservation(
        meta=_meta(Product.TRADE_FLOW, 20),
        period_start_us=10,
        period_end_us=20,
        total_quote_volume=Decimal(0),
        taker_buy_quote_volume=Decimal(0),
    )
    assert flow.total_quote_volume == 0
    assert flow.taker_imbalance is None


def test_liquidation_observed_zero_is_not_missing_coverage() -> None:
    liquidation = LiquidationObservation(
        meta=_meta(Product.LIQUIDATION_OBSERVED, 20),
        period_start_us=10,
        period_end_us=20,
        long_liquidation_usd=Decimal(0),
        short_liquidation_usd=Decimal(0),
        venue_publication_censored=True,
    )
    assert liquidation.imbalance == 0


def test_funding_kinds_keep_observation_and_effective_clocks_distinct() -> None:
    indicative = FundingObservation(
        meta=_meta(Product.FUNDING_INDICATIVE, 20),
        kind=FundingKind.INDICATIVE,
        rate=Decimal("0.0001"),
        effective_time_us=40,
        interval_us=20,
        positive_rate_long_pays_short=True,
    )
    realized = FundingObservation(
        meta=_meta(Product.FUNDING_REALIZED, 40),
        kind=FundingKind.REALIZED,
        rate=Decimal("0.0002"),
        effective_time_us=40,
        interval_us=20,
        positive_rate_long_pays_short=True,
    )
    assert indicative.effective_time_us > indicative.meta.event_time_us
    assert realized.effective_time_us == realized.meta.event_time_us


def test_basis_must_reconcile_exactly() -> None:
    valid = BasisObservation(
        meta=_meta(Product.MARK_INDEX_BASIS, 20),
        mark_price=Decimal("101"),
        index_price=Decimal("100"),
        basis_ratio=Decimal("0.01"),
    )
    assert valid.basis_ratio == Decimal("0.01")
    with pytest.raises(ContractError, match="reconcile"):
        replace(valid, basis_ratio=Decimal("0.02"))


def test_product_and_clock_mismatches_fail_closed() -> None:
    with pytest.raises(ContractError, match="expected product"):
        OpenInterestObservation(
            meta=_meta(Product.TRADE_FLOW, 20),
            native_quantity=Decimal(1),
            base_quantity=Decimal(1),
            notional_usd=Decimal(1),
            conversion_price=Decimal(1),
        )
    with pytest.raises(ContractError, match="cannot precede event"):
        replace(_meta(Product.OPEN_INTEREST, 20), source_available_at_us=19)


def test_snapshot_returns_only_values_available_by_decision() -> None:
    observations = [_oi(70), _oi(80), _oi(90, available=95), _oi(98, available=105)]
    requirement = WindowRequirement(Product.OPEN_INTEREST, 40, 3, 20)
    snapshot = AsOfStateStore(observations).snapshot(
        _INSTRUMENT, 100, [requirement]
    )
    assert snapshot.eligible
    assert [
        observation.meta.event_time_us
        for observation in snapshot.observations(Product.OPEN_INTEREST)
    ] == [70, 80, 90]


def test_future_or_late_data_cannot_revise_an_existing_snapshot() -> None:
    requirement = WindowRequirement(Product.OPEN_INTEREST, 40, 2, 20)
    prefix = AsOfStateStore([_oi(80), _oi(90)]).snapshot(
        _INSTRUMENT, 100, [requirement]
    )
    extended = AsOfStateStore(
        [_oi(80), _oi(90), _oi(95, available=105), _oi(110)]
    ).snapshot(_INSTRUMENT, 100, [requirement])
    assert extended == prefix


def test_unknown_availability_blocks_primary_eligibility() -> None:
    unknown = OpenInterestObservation(
        meta=_unknown_meta(Product.OPEN_INTEREST, 85),
        native_quantity=Decimal(1),
        base_quantity=Decimal(1),
        notional_usd=Decimal(1),
        conversion_price=Decimal(1),
    )
    snapshot = AsOfStateStore([_oi(80), unknown, _oi(90)]).snapshot(
        _INSTRUMENT,
        100,
        [WindowRequirement(Product.OPEN_INTEREST, 40, 2, 20)],
    )
    assert not snapshot.eligible
    assert EligibilityCode.UNKNOWN_AVAILABILITY in {
        issue.code for issue in snapshot.issues
    }


def test_typed_coverage_gap_blocks_even_when_rows_exist() -> None:
    gap = CoverageGap(
        Product.OPEN_INTEREST,
        _INSTRUMENT,
        75,
        85,
        "source archive missing",
        "gap-evidence",
    )
    snapshot = AsOfStateStore([_oi(80), _oi(90)], [gap]).snapshot(
        _INSTRUMENT,
        100,
        [WindowRequirement(Product.OPEN_INTEREST, 40, 2, 20)],
    )
    assert not snapshot.eligible
    assert snapshot.issues[0].code == EligibilityCode.COVERAGE_GAP


def test_insufficient_and_stale_history_are_distinct() -> None:
    insufficient = AsOfStateStore([_oi(90)]).snapshot(
        _INSTRUMENT,
        100,
        [WindowRequirement(Product.OPEN_INTEREST, 40, 2, 20)],
    )
    stale = AsOfStateStore([_oi(60), _oi(70)]).snapshot(
        _INSTRUMENT,
        100,
        [WindowRequirement(Product.OPEN_INTEREST, 50, 2, 20)],
    )
    assert insufficient.issues[0].code == EligibilityCode.INSUFFICIENT_HISTORY
    assert stale.issues[0].code == EligibilityCode.STALE_LATEST_OBSERVATION


def test_duplicate_observations_and_overlapping_gaps_fail_closed() -> None:
    with pytest.raises(StateError, match="duplicate economic"):
        AsOfStateStore([_oi(80), _oi(80)])

    first = CoverageGap(
        Product.OPEN_INTEREST, _INSTRUMENT, 10, 30, "a", "evidence-a"
    )
    second = CoverageGap(
        Product.OPEN_INTEREST, _INSTRUMENT, 20, 40, "b", "evidence-b"
    )
    with pytest.raises(StateError, match="overlapping"):
        AsOfStateStore([], [first, second])


def test_instruments_remain_isolated() -> None:
    store = AsOfStateStore([_oi(80), _oi(90), _oi(80, instrument="ETHUSDT-PERP")])
    snapshot = store.snapshot(
        _INSTRUMENT,
        100,
        [WindowRequirement(Product.OPEN_INTEREST, 40, 2, 20)],
    )
    assert snapshot.eligible
    assert {
        observation.meta.instrument_id
        for observation in snapshot.observations(Product.OPEN_INTEREST)
    } == {_INSTRUMENT}
