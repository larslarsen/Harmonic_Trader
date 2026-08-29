"""Causal, scale-invariant geometry built from already-confirmed pivots."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable

from harmonic_trader.discovery.pivots import ConfirmedPivot, PivotKind


class GeometryError(ValueError):
    """A geometry configuration or pivot stream violates the research contract."""


def _positive_decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool):
        raise GeometryError(f"{field} must be a finite positive decimal")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise GeometryError(f"{field} must be a finite positive decimal") from exc
    if not result.is_finite() or result <= 0:
        raise GeometryError(f"{field} must be a finite positive decimal")
    return result


@dataclass(frozen=True, slots=True)
class GeometryConfig:
    """Frozen choices that define one geometry observation family."""

    pivot_count: int
    denominator_floor: Decimal = Decimal("1e-12")
    direction_normalized: bool = True

    def __post_init__(self) -> None:
        if (
            isinstance(self.pivot_count, bool)
            or not isinstance(self.pivot_count, int)
            or self.pivot_count < 3
        ):
            raise GeometryError("pivot_count must be an integer of at least 3")
        object.__setattr__(
            self,
            "denominator_floor",
            _positive_decimal(self.denominator_floor, field="denominator_floor"),
        )
        if not isinstance(self.direction_normalized, bool):
            raise GeometryError("direction_normalized must be a boolean")


@dataclass(frozen=True, slots=True)
class GeometryVector:
    """One immutable model input known at the terminal pivot's decision time."""

    instrument_id: str
    terminal_sequence: int
    terminal_kind: PivotKind
    decision_time_us: int
    availability_time_us: int
    first_pivot_time_us: int
    terminal_pivot_time_us: int
    pivot_sequences: tuple[int, ...]
    direction_normalized: bool
    swing_atr: tuple[Decimal, ...]
    log_duration_ratios: tuple[Decimal, ...]
    swing_velocity: tuple[Decimal, ...]
    retracement_ratios: tuple[Decimal, ...]
    terminal_displacement_atr: Decimal
    path_efficiency: Decimal
    terminal_leg_share: Decimal
    confirmation_delays: tuple[Decimal, ...]

    @property
    def feature_items(self) -> tuple[tuple[str, Decimal], ...]:
        """Return a stable flat feature order for downstream model adapters."""

        items: list[tuple[str, Decimal]] = []
        items.extend(
            (f"swing_atr_{index}", value)
            for index, value in enumerate(self.swing_atr, start=1)
        )
        items.extend(
            (f"log_duration_ratio_{index}", value)
            for index, value in enumerate(self.log_duration_ratios, start=2)
        )
        items.extend(
            (f"swing_velocity_{index}", value)
            for index, value in enumerate(self.swing_velocity, start=1)
        )
        items.extend(
            (f"retracement_ratio_{index}", value)
            for index, value in enumerate(self.retracement_ratios, start=2)
        )
        items.extend(
            (
                ("terminal_displacement_atr", self.terminal_displacement_atr),
                ("path_efficiency", self.path_efficiency),
                ("terminal_leg_share", self.terminal_leg_share),
            )
        )
        items.extend(
            (f"confirmation_delay_{index}", value)
            for index, value in enumerate(self.confirmation_delays, start=1)
        )
        return tuple(items)

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.feature_items)

    @property
    def feature_values(self) -> tuple[Decimal, ...]:
        return tuple(value for _, value in self.feature_items)


class OnlineGeometryBuilder:
    """Build one vector whenever a new pivot completes an instrument window."""

    def __init__(self, instrument_id: str, config: GeometryConfig) -> None:
        instrument = str(instrument_id).strip()
        if not instrument:
            raise GeometryError("instrument_id must be non-empty")
        self.instrument_id = instrument
        self.config = config
        self._pivots: deque[ConfirmedPivot] = deque(maxlen=config.pivot_count)
        self._last: ConfirmedPivot | None = None

    def update(self, pivot: ConfirmedPivot) -> GeometryVector | None:
        self._validate_next(pivot)
        self._pivots.append(pivot)
        self._last = pivot
        if len(self._pivots) < self.config.pivot_count:
            return None
        return _vector_from_window(tuple(self._pivots), self.config)

    def _validate_next(self, pivot: ConfirmedPivot) -> None:
        if pivot.instrument_id != self.instrument_id:
            raise GeometryError(
                f"builder for {self.instrument_id!r} received {pivot.instrument_id!r}"
            )
        if pivot.sequence <= 0:
            raise GeometryError("pivot sequence must be positive")
        if pivot.price <= 0 or not pivot.price.is_finite():
            raise GeometryError("pivot price must be finite and positive")
        if pivot.lagged_atr <= 0 or not pivot.lagged_atr.is_finite():
            raise GeometryError("pivot lagged_atr must be finite and positive")
        if pivot.confirmation_delay_bars <= 0:
            raise GeometryError("pivot confirmation delay must be positive")
        if pivot.pivot_time_us > pivot.confirmation_time_us:
            raise GeometryError("pivot time cannot follow confirmation time")
        if pivot.confirmation_time_us > pivot.availability_time_us:
            raise GeometryError("confirmation time cannot follow availability time")

        previous = self._last
        if previous is None:
            return
        if pivot.sequence != previous.sequence + 1:
            raise GeometryError("pivot sequences must be contiguous")
        if pivot.kind == previous.kind:
            raise GeometryError("pivot kinds must alternate")
        if pivot.pivot_bar_index <= previous.pivot_bar_index:
            raise GeometryError("pivot extrema must advance by bar index")
        if pivot.pivot_time_us <= previous.pivot_time_us:
            raise GeometryError("pivot extrema must advance in time")
        if pivot.decision_time_us <= previous.decision_time_us:
            raise GeometryError("pivot decisions must advance in time")


def _ratio(numerator: Decimal, denominator: Decimal, floor: Decimal) -> Decimal:
    return numerator / max(abs(denominator), floor)


def _vector_from_window(
    pivots: tuple[ConfirmedPivot, ...], config: GeometryConfig
) -> GeometryVector:
    raw_swings = tuple(
        current.price - previous.price
        for previous, current in zip(pivots, pivots[1:])
    )
    if any(swing == 0 for swing in raw_swings):
        raise GeometryError("alternating pivots must have nonzero price swings")

    orientation = (
        Decimal(1)
        if not config.direction_normalized or raw_swings[-1] > 0
        else Decimal(-1)
    )
    swing_atr = tuple(
        orientation * swing / current.lagged_atr
        for swing, current in zip(raw_swings, pivots[1:], strict=True)
    )
    durations = tuple(
        current.pivot_bar_index - previous.pivot_bar_index
        for previous, current in zip(pivots, pivots[1:])
    )
    if any(duration <= 0 for duration in durations):
        raise GeometryError("pivot durations must be positive")
    log_duration_ratios = tuple(
        (Decimal(current) / Decimal(previous)).ln()
        for previous, current in zip(durations, durations[1:])
    )
    swing_velocity = tuple(
        swing / Decimal(duration)
        for swing, duration in zip(swing_atr, durations, strict=True)
    )
    retracement_ratios = tuple(
        _ratio(abs(current), previous, config.denominator_floor)
        for previous, current in zip(raw_swings, raw_swings[1:])
    )

    terminal_displacement = (
        orientation
        * (pivots[-1].price - pivots[0].price)
        / pivots[-1].lagged_atr
    )
    path = sum((abs(swing) for swing in swing_atr), Decimal(0))
    net = sum(swing_atr, Decimal(0))
    path_efficiency = _ratio(path, net, config.denominator_floor)
    terminal_leg_share = _ratio(
        abs(swing_atr[-1]), path, config.denominator_floor
    )
    confirmation_delays = tuple(
        Decimal(pivot.confirmation_delay_bars) for pivot in pivots
    )

    features = (
        *swing_atr,
        *log_duration_ratios,
        *swing_velocity,
        *retracement_ratios,
        terminal_displacement,
        path_efficiency,
        terminal_leg_share,
        *confirmation_delays,
    )
    if any(not value.is_finite() for value in features):
        raise GeometryError("geometry features must be finite")

    terminal = pivots[-1]
    return GeometryVector(
        instrument_id=terminal.instrument_id,
        terminal_sequence=terminal.sequence,
        terminal_kind=terminal.kind,
        decision_time_us=terminal.decision_time_us,
        availability_time_us=terminal.availability_time_us,
        first_pivot_time_us=pivots[0].pivot_time_us,
        terminal_pivot_time_us=terminal.pivot_time_us,
        pivot_sequences=tuple(pivot.sequence for pivot in pivots),
        direction_normalized=config.direction_normalized,
        swing_atr=swing_atr,
        log_duration_ratios=log_duration_ratios,
        swing_velocity=swing_velocity,
        retracement_ratios=retracement_ratios,
        terminal_displacement_atr=terminal_displacement,
        path_efficiency=path_efficiency,
        terminal_leg_share=terminal_leg_share,
        confirmation_delays=confirmation_delays,
    )


def build_geometry_vectors(
    pivots: Iterable[ConfirmedPivot], config: GeometryConfig
) -> tuple[GeometryVector, ...]:
    """Build vectors from an interleaved, globally causal pivot stream."""

    builders: dict[str, OnlineGeometryBuilder] = {}
    vectors: list[GeometryVector] = []
    last_global_decision: int | None = None
    for pivot in pivots:
        if last_global_decision is not None and pivot.decision_time_us < last_global_decision:
            raise GeometryError("pivot stream must be globally ordered by decision time")
        last_global_decision = pivot.decision_time_us
        builder = builders.get(pivot.instrument_id)
        if builder is None:
            builder = OnlineGeometryBuilder(pivot.instrument_id, config)
            builders[pivot.instrument_id] = builder
        vector = builder.update(pivot)
        if vector is not None:
            vectors.append(vector)
    return tuple(vectors)
