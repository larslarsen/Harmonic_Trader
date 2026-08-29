from __future__ import annotations

from decimal import Decimal

import pytest

from harmonic_trader.discovery.pivots import (
    BarObservation,
    OnlineDirectionalChange,
    PivotConfig,
    PivotError,
    PivotKind,
    extract_market_pivots,
    extract_pivots,
)


def _bar(
    index: int,
    *,
    high: str,
    low: str,
    close: str,
    instrument: str = "BTC",
    availability_delay: int = 0,
) -> BarObservation:
    start = index * 10
    end = start + 10
    return BarObservation(
        instrument_id=instrument,
        period_start_us=start,
        period_end_us=end,
        availability_time_us=end + availability_delay,
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
    )


def _alternating_bars(*, instrument: str = "BTC") -> list[BarObservation]:
    return [
        _bar(0, high="10", low="9", close="9.5", instrument=instrument),
        _bar(1, high="10", low="9", close="9.5", instrument=instrument),
        _bar(2, high="10", low="9", close="9.5", instrument=instrument),
        _bar(
            3,
            high="11.5",
            low="9.5",
            close="11",
            instrument=instrument,
            availability_delay=2,
        ),
        _bar(4, high="11.4", low="9.5", close="9.8", instrument=instrument),
        _bar(5, high="10", low="7", close="7.5", instrument=instrument),
        _bar(6, high="10.5", low="7.2", close="10.4", instrument=instrument),
    ]


def test_pivots_alternate_and_preserve_confirmation_clock() -> None:
    pivots = extract_pivots(
        _alternating_bars(),
        PivotConfig(atr_period=2, threshold_multiplier=Decimal("1")),
    )
    assert [pivot.kind for pivot in pivots[:2]] == [PivotKind.LOW, PivotKind.HIGH]
    first = pivots[0]
    assert first.pivot_bar_index == 2
    assert first.confirmation_bar_index == 3
    assert first.pivot_time_us < first.confirmation_time_us
    assert first.confirmation_time_us < first.availability_time_us
    assert first.decision_time_us == first.availability_time_us
    assert first.confirmation_delay_bars == 1


def test_atr_is_lagged_and_current_range_does_not_change_threshold() -> None:
    detector = OnlineDirectionalChange(
        "BTC", PivotConfig(atr_period=2, threshold_multiplier=Decimal("1"))
    )
    bars = _alternating_bars()
    for bar in bars[:4]:
        detector.update(bar)
    pivot = detector.update(
        _bar(4, high="11.4", low="1", close="9.8", instrument="BTC")
    )
    assert pivot is not None
    assert pivot.kind == PivotKind.HIGH
    assert pivot.lagged_atr == Decimal("1.5")
    assert pivot.confirmation_threshold == Decimal("1.5")


def test_new_extreme_cannot_confirm_inside_the_same_ohlc_bar() -> None:
    detector = OnlineDirectionalChange(
        "BTC", PivotConfig(atr_period=2, threshold_multiplier=Decimal("1"))
    )
    for bar in _alternating_bars()[:4]:
        detector.update(bar)
    ambiguous = _bar(4, high="20", low="8", close="8.5")
    assert detector.update(ambiguous) is None
    confirmed = detector.update(_bar(5, high="19", low="8", close="8.5"))
    assert confirmed is not None
    assert confirmed.kind == PivotKind.HIGH
    assert confirmed.pivot_bar_index == 4
    assert confirmed.confirmation_bar_index == 5


def test_future_bars_do_not_revise_already_confirmed_pivots() -> None:
    bars = _alternating_bars()
    config = PivotConfig(atr_period=2, threshold_multiplier=Decimal("1"))
    prefix = extract_pivots(bars[:5], config)
    full = extract_pivots(bars, config)
    assert prefix
    assert full[: len(prefix)] == prefix


def test_interleaved_instruments_keep_independent_state() -> None:
    btc = _alternating_bars(instrument="BTC")
    eth = _alternating_bars(instrument="ETH")
    interleaved = [item for pair in zip(btc, eth, strict=True) for item in pair]
    pivots = extract_pivots(
        interleaved,
        PivotConfig(atr_period=2, threshold_multiplier=Decimal("1")),
    )
    first = [pivot for pivot in pivots if pivot.sequence == 1]
    assert {pivot.instrument_id for pivot in first} == {"BTC", "ETH"}
    assert all(pivot.kind == PivotKind.LOW for pivot in first)


def test_out_of_order_or_overlapping_bars_fail_closed() -> None:
    detector = OnlineDirectionalChange(
        "BTC", PivotConfig(atr_period=2, threshold_multiplier=Decimal("1"))
    )
    detector.update(_bar(1, high="10", low="9", close="9.5"))
    with pytest.raises(PivotError, match="overlap|chronological"):
        detector.update(_bar(0, high="10", low="9", close="9.5"))


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"atr_period": 0, "threshold_multiplier": Decimal("1")}, "atr_period"),
        ({"atr_period": 2, "threshold_multiplier": Decimal("0")}, "multiplier"),
        ({"atr_period": 2, "threshold_multiplier": Decimal("NaN")}, "multiplier"),
    ],
)
def test_invalid_configuration_fails_closed(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(PivotError, match=message):
        PivotConfig(**kwargs)  # type: ignore[arg-type]


def test_invalid_bar_clock_and_prices_fail_closed() -> None:
    with pytest.raises(PivotError, match="period_start_us"):
        BarObservation("BTC", 0, 10, 9, Decimal("10"), Decimal("9"), Decimal("9.5"))
    with pytest.raises(PivotError, match="low <= close <= high"):
        _bar(0, high="10", low="9", close="11")


def test_arrow_adapter_sorts_each_instrument_and_extracts_pivots() -> None:
    pa = pytest.importorskip("pyarrow")
    bars = list(reversed(_alternating_bars()))
    table = pa.table(
        {
            "instrument_id": [bar.instrument_id for bar in bars],
            "period_start": [bar.period_start_us for bar in bars],
            "period_end": [bar.period_end_us for bar in bars],
            "availability_time": [bar.availability_time_us for bar in bars],
            "high": [bar.high for bar in bars],
            "low": [bar.low for bar in bars],
            "close": [bar.close for bar in bars],
        }
    )
    pivots = extract_market_pivots(
        table, PivotConfig(atr_period=2, threshold_multiplier=Decimal("1"))
    )
    assert pivots
    assert pivots[0].kind == PivotKind.LOW
