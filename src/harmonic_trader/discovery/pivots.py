"""Online ATR-scaled directional-change pivots with an explicit causal clock.

The detector consumes one completed bar at a time. A bar can confirm an earlier
extremum, but an extremum first observed in the current bar cannot be confirmed in that
same bar because OHLC data does not reveal intrabar ordering. The confirmation threshold
uses Wilder ATR through the previous bar, so the confirming bar never changes its own
threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Iterable


class PivotError(ValueError):
    """A bar, configuration, or stream violates the causal pivot contract."""


class PivotKind(StrEnum):
    HIGH = "high"
    LOW = "low"


class _Mode(StrEnum):
    UNKNOWN = "unknown"
    SEEK_HIGH = "seek_high"
    SEEK_LOW = "seek_low"


def _positive_decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool):
        raise PivotError(f"{field} must be a finite positive decimal")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PivotError(f"{field} must be a finite positive decimal") from exc
    if not result.is_finite() or result <= 0:
        raise PivotError(f"{field} must be a finite positive decimal")
    return result


def _exact_time(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PivotError(f"{field} must be an integer microsecond timestamp")
    return value


@dataclass(frozen=True, slots=True)
class PivotConfig:
    atr_period: int
    threshold_multiplier: Decimal

    def __post_init__(self) -> None:
        if (
            isinstance(self.atr_period, bool)
            or not isinstance(self.atr_period, int)
            or self.atr_period <= 0
        ):
            raise PivotError("atr_period must be a positive integer")
        object.__setattr__(
            self,
            "threshold_multiplier",
            _positive_decimal(
                self.threshold_multiplier, field="threshold_multiplier"
            ),
        )


@dataclass(frozen=True, slots=True)
class BarObservation:
    instrument_id: str
    period_start_us: int
    period_end_us: int
    availability_time_us: int
    high: Decimal
    low: Decimal
    close: Decimal

    def __post_init__(self) -> None:
        instrument = str(self.instrument_id).strip()
        if not instrument:
            raise PivotError("instrument_id must be non-empty")
        object.__setattr__(self, "instrument_id", instrument)
        start = _exact_time(self.period_start_us, field="period_start_us")
        end = _exact_time(self.period_end_us, field="period_end_us")
        available = _exact_time(
            self.availability_time_us, field="availability_time_us"
        )
        if not start < end <= available:
            raise PivotError(
                "require period_start_us < period_end_us <= availability_time_us"
            )
        high = _positive_decimal(self.high, field="high")
        low = _positive_decimal(self.low, field="low")
        close = _positive_decimal(self.close, field="close")
        if not low <= close <= high:
            raise PivotError("require low <= close <= high")
        object.__setattr__(self, "high", high)
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "close", close)


@dataclass(frozen=True, slots=True)
class ConfirmedPivot:
    instrument_id: str
    sequence: int
    kind: PivotKind
    price: Decimal
    pivot_bar_index: int
    pivot_time_us: int
    confirmation_bar_index: int
    confirmation_time_us: int
    availability_time_us: int
    lagged_atr: Decimal
    confirmation_threshold: Decimal

    @property
    def confirmation_delay_bars(self) -> int:
        return self.confirmation_bar_index - self.pivot_bar_index

    @property
    def decision_time_us(self) -> int:
        """Earliest time at which this pivot may enter a feature vector."""

        return self.availability_time_us


class OnlineDirectionalChange:
    """Stateful one-instrument directional-change detector."""

    def __init__(self, instrument_id: str, config: PivotConfig) -> None:
        instrument = str(instrument_id).strip()
        if not instrument:
            raise PivotError("instrument_id must be non-empty")
        self.instrument_id = instrument
        self.config = config
        self._mode = _Mode.UNKNOWN
        self._bar_index = -1
        self._last_period_end_us: int | None = None
        self._previous_close: Decimal | None = None
        self._seed_true_ranges: list[Decimal] = []
        self._atr: Decimal | None = None
        self._candidate_high: tuple[Decimal, int, int] | None = None
        self._candidate_low: tuple[Decimal, int, int] | None = None
        self._sequence = 0

    @property
    def lagged_atr(self) -> Decimal | None:
        """ATR available to the next bar, based only on already-consumed bars."""

        return self._atr

    def update(self, bar: BarObservation) -> ConfirmedPivot | None:
        if bar.instrument_id != self.instrument_id:
            raise PivotError(
                f"detector for {self.instrument_id!r} received {bar.instrument_id!r}"
            )
        if (
            self._last_period_end_us is not None
            and bar.period_start_us < self._last_period_end_us
        ):
            raise PivotError("bars overlap or are out of chronological order")

        self._bar_index += 1
        lagged_atr = self._atr
        pivot = None
        if lagged_atr is not None and lagged_atr > 0:
            pivot = self._process_bar(bar, lagged_atr)

        true_range = self._true_range(bar)
        self._update_atr(true_range)
        self._previous_close = bar.close
        self._last_period_end_us = bar.period_end_us
        return pivot

    def _true_range(self, bar: BarObservation) -> Decimal:
        if self._previous_close is None:
            return bar.high - bar.low
        return max(
            bar.high - bar.low,
            abs(bar.high - self._previous_close),
            abs(bar.low - self._previous_close),
        )

    def _update_atr(self, true_range: Decimal) -> None:
        period = self.config.atr_period
        if self._atr is None:
            self._seed_true_ranges.append(true_range)
            if len(self._seed_true_ranges) == period:
                self._atr = sum(self._seed_true_ranges, Decimal(0)) / Decimal(period)
                self._seed_true_ranges.clear()
            return
        self._atr = (
            self._atr * Decimal(period - 1) + true_range
        ) / Decimal(period)

    def _process_bar(
        self, bar: BarObservation, lagged_atr: Decimal
    ) -> ConfirmedPivot | None:
        index = self._bar_index
        if self._candidate_high is None or self._candidate_low is None:
            self._candidate_high = (bar.high, index, bar.period_end_us)
            self._candidate_low = (bar.low, index, bar.period_end_us)
            return None

        threshold = lagged_atr * self.config.threshold_multiplier
        if self._mode == _Mode.UNKNOWN:
            return self._process_unknown(bar, threshold, lagged_atr)
        if self._mode == _Mode.SEEK_HIGH:
            candidate = self._candidate_high
            if bar.high > candidate[0]:
                self._candidate_high = (bar.high, index, bar.period_end_us)
                return None
            if index > candidate[1] and bar.close <= candidate[0] - threshold:
                return self._confirm(
                    PivotKind.HIGH, candidate, bar, lagged_atr, threshold
                )
            return None

        candidate = self._candidate_low
        if bar.low < candidate[0]:
            self._candidate_low = (bar.low, index, bar.period_end_us)
            return None
        if index > candidate[1] and bar.close >= candidate[0] + threshold:
            return self._confirm(PivotKind.LOW, candidate, bar, lagged_atr, threshold)
        return None

    def _process_unknown(
        self, bar: BarObservation, threshold: Decimal, lagged_atr: Decimal
    ) -> ConfirmedPivot | None:
        index = self._bar_index
        high = self._candidate_high
        low = self._candidate_low
        assert high is not None and low is not None
        if bar.high > high[0]:
            high = (bar.high, index, bar.period_end_us)
            self._candidate_high = high
        if bar.low < low[0]:
            low = (bar.low, index, bar.period_end_us)
            self._candidate_low = low

        can_confirm_high = index > high[1] and bar.close <= high[0] - threshold
        can_confirm_low = index > low[1] and bar.close >= low[0] + threshold
        if can_confirm_high and can_confirm_low:
            if high[1] > low[1]:
                can_confirm_low = False
            elif low[1] > high[1]:
                can_confirm_high = False
            else:
                return None
        if can_confirm_high:
            return self._confirm(PivotKind.HIGH, high, bar, lagged_atr, threshold)
        if can_confirm_low:
            return self._confirm(PivotKind.LOW, low, bar, lagged_atr, threshold)
        return None

    def _confirm(
        self,
        kind: PivotKind,
        candidate: tuple[Decimal, int, int],
        bar: BarObservation,
        lagged_atr: Decimal,
        threshold: Decimal,
    ) -> ConfirmedPivot:
        self._sequence += 1
        pivot = ConfirmedPivot(
            instrument_id=self.instrument_id,
            sequence=self._sequence,
            kind=kind,
            price=candidate[0],
            pivot_bar_index=candidate[1],
            pivot_time_us=candidate[2],
            confirmation_bar_index=self._bar_index,
            confirmation_time_us=bar.period_end_us,
            availability_time_us=bar.availability_time_us,
            lagged_atr=lagged_atr,
            confirmation_threshold=threshold,
        )
        if pivot.confirmation_delay_bars <= 0:
            raise PivotError("a pivot cannot be confirmed in its extremum bar")
        if kind == PivotKind.HIGH:
            self._mode = _Mode.SEEK_LOW
            self._candidate_low = (bar.low, self._bar_index, bar.period_end_us)
        else:
            self._mode = _Mode.SEEK_HIGH
            self._candidate_high = (bar.high, self._bar_index, bar.period_end_us)
        return pivot


def extract_pivots(
    bars: Iterable[BarObservation], config: PivotConfig
) -> tuple[ConfirmedPivot, ...]:
    """Extract pivots from an interleaved, per-instrument chronological stream."""

    detectors: dict[str, OnlineDirectionalChange] = {}
    pivots: list[ConfirmedPivot] = []
    for bar in bars:
        detector = detectors.get(bar.instrument_id)
        if detector is None:
            detector = OnlineDirectionalChange(bar.instrument_id, config)
            detectors[bar.instrument_id] = detector
        pivot = detector.update(bar)
        if pivot is not None:
            pivots.append(pivot)
    return tuple(
        sorted(
            pivots,
            key=lambda item: (
                item.decision_time_us,
                item.instrument_id,
                item.confirmation_time_us,
                item.sequence,
            ),
        )
    )


def observations_from_market_table(table: Any) -> tuple[BarObservation, ...]:
    """Convert the audited market-bar Arrow shape without importing PyArrow here."""

    required = {
        "instrument_id",
        "period_start",
        "period_end",
        "availability_time",
        "high",
        "low",
        "close",
    }
    names = set(getattr(table, "column_names", ()))
    missing = sorted(required - names)
    if missing:
        raise PivotError(f"market bars are missing pivot columns: {missing!r}")
    columns = {name: table.column(name).to_pylist() for name in required}
    rows = [
        BarObservation(
            instrument_id=str(columns["instrument_id"][index]),
            period_start_us=int(columns["period_start"][index]),
            period_end_us=int(columns["period_end"][index]),
            availability_time_us=int(columns["availability_time"][index]),
            high=columns["high"][index],
            low=columns["low"][index],
            close=columns["close"][index],
        )
        for index in range(int(table.num_rows))
    ]
    rows.sort(
        key=lambda item: (
            item.instrument_id,
            item.period_start_us,
            item.period_end_us,
        )
    )
    return tuple(rows)


def extract_market_pivots(
    table: Any, config: PivotConfig
) -> tuple[ConfirmedPivot, ...]:
    """Extract causal pivots from an already-audited market-bar table."""

    return extract_pivots(observations_from_market_table(table), config)
