from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from harmonic_trader.discovery.geometry import (
    GeometryConfig,
    GeometryError,
    OnlineGeometryBuilder,
    build_geometry_vectors,
)
from harmonic_trader.discovery.pivots import ConfirmedPivot, PivotKind


def _pivots(
    *,
    instrument: str = "BTCUSDT-PERP",
    scale: Decimal = Decimal(1),
    time_shift: int = 0,
) -> list[ConfirmedPivot]:
    prices = [Decimal("100"), Decimal("110"), Decimal("104"), Decimal("115"), Decimal("108")]
    kinds = [
        PivotKind.LOW,
        PivotKind.HIGH,
        PivotKind.LOW,
        PivotKind.HIGH,
        PivotKind.LOW,
    ]
    result: list[ConfirmedPivot] = []
    for offset, (price, kind) in enumerate(zip(prices, kinds, strict=True), start=1):
        pivot_bar = offset * 2
        confirmation_bar = pivot_bar + 1
        pivot_time = time_shift + pivot_bar * 10
        confirmation_time = time_shift + confirmation_bar * 10
        result.append(
            ConfirmedPivot(
                instrument_id=instrument,
                sequence=offset,
                kind=kind,
                price=price * scale,
                pivot_bar_index=pivot_bar,
                pivot_time_us=pivot_time,
                confirmation_bar_index=confirmation_bar,
                confirmation_time_us=confirmation_time,
                availability_time_us=confirmation_time + 2,
                lagged_atr=Decimal("2") * scale,
                confirmation_threshold=Decimal("3") * scale,
            )
        )
    return result


def test_builds_stable_flat_vector_at_terminal_decision() -> None:
    pivots = _pivots()
    vector = build_geometry_vectors(pivots, GeometryConfig(pivot_count=5))[0]
    assert vector.pivot_sequences == (1, 2, 3, 4, 5)
    assert vector.decision_time_us == pivots[-1].availability_time_us
    assert vector.availability_time_us == vector.decision_time_us
    assert vector.terminal_kind == PivotKind.LOW
    assert vector.swing_atr == (
        Decimal("-5"),
        Decimal("3"),
        Decimal("-5.5"),
        Decimal("3.5"),
    )
    assert len(vector.feature_names) == len(vector.feature_values)
    assert len(set(vector.feature_names)) == len(vector.feature_names)
    assert all(value.is_finite() for value in vector.feature_values)


def test_features_are_invariant_to_price_scale() -> None:
    config = GeometryConfig(pivot_count=5)
    base = build_geometry_vectors(_pivots(), config)[0]
    scaled = build_geometry_vectors(_pivots(scale=Decimal("1000")), config)[0]
    assert scaled.feature_items == base.feature_items


def test_features_are_invariant_to_time_origin() -> None:
    config = GeometryConfig(pivot_count=5)
    base = build_geometry_vectors(_pivots(), config)[0]
    shifted = build_geometry_vectors(_pivots(time_shift=1_000_000), config)[0]
    assert shifted.feature_items == base.feature_items
    assert shifted.decision_time_us == base.decision_time_us + 1_000_000


def test_direction_normalization_makes_terminal_leg_positive() -> None:
    normalized = build_geometry_vectors(
        _pivots(), GeometryConfig(pivot_count=5, direction_normalized=True)
    )[0]
    raw = build_geometry_vectors(
        _pivots(), GeometryConfig(pivot_count=5, direction_normalized=False)
    )[0]
    assert normalized.swing_atr[-1] > 0
    assert raw.swing_atr[-1] < 0
    assert normalized.swing_atr == tuple(-value for value in raw.swing_atr)


def test_future_pivots_do_not_revise_existing_vectors() -> None:
    pivots = _pivots()
    sixth = replace(
        pivots[-1],
        sequence=6,
        kind=PivotKind.HIGH,
        price=Decimal("120"),
        pivot_bar_index=12,
        pivot_time_us=120,
        confirmation_bar_index=13,
        confirmation_time_us=130,
        availability_time_us=132,
    )
    config = GeometryConfig(pivot_count=4)
    prefix = build_geometry_vectors(pivots, config)
    full = build_geometry_vectors([*pivots, sixth], config)
    assert full[: len(prefix)] == prefix


def test_interleaved_instruments_have_independent_windows() -> None:
    btc = _pivots(instrument="BTCUSDT-PERP")
    eth = _pivots(instrument="ETHUSDT-PERP")
    interleaved = [pivot for pair in zip(btc, eth, strict=True) for pivot in pair]
    vectors = build_geometry_vectors(interleaved, GeometryConfig(pivot_count=5))
    assert {vector.instrument_id for vector in vectors} == {
        "BTCUSDT-PERP",
        "ETHUSDT-PERP",
    }


@pytest.mark.parametrize(
    "config",
    [
        {"pivot_count": 2},
        {"pivot_count": True},
        {"pivot_count": 5, "denominator_floor": Decimal(0)},
        {"pivot_count": 5, "denominator_floor": Decimal("NaN")},
        {"pivot_count": 5, "direction_normalized": 1},
    ],
)
def test_invalid_geometry_configuration_fails_closed(config: dict[str, object]) -> None:
    with pytest.raises(GeometryError):
        GeometryConfig(**config)  # type: ignore[arg-type]


def test_non_alternating_or_noncontiguous_pivots_fail_closed() -> None:
    pivots = _pivots()
    builder = OnlineGeometryBuilder("BTCUSDT-PERP", GeometryConfig(pivot_count=3))
    builder.update(pivots[0])
    with pytest.raises(GeometryError, match="alternate"):
        builder.update(replace(pivots[1], kind=PivotKind.LOW))

    builder = OnlineGeometryBuilder("BTCUSDT-PERP", GeometryConfig(pivot_count=3))
    builder.update(pivots[0])
    with pytest.raises(GeometryError, match="contiguous"):
        builder.update(replace(pivots[1], sequence=3))


def test_globally_out_of_order_pivot_stream_fails_closed() -> None:
    pivots = _pivots()
    with pytest.raises(GeometryError, match="globally ordered"):
        build_geometry_vectors(
            [pivots[1], pivots[0]], GeometryConfig(pivot_count=3)
        )
