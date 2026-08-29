from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import numpy as np
import pytest

from harmonic_trader.discovery.geometry import GeometryVector
from harmonic_trader.discovery.pivots import PivotKind
from harmonic_trader.features.microstructure import MicrostructureVector
from harmonic_trader.features.state import MultimodalVector
from harmonic_trader.modeling.representation import (
    EventKey,
    RepresentationConfig,
    RepresentationError,
    fit_representation,
    parse_representation_artifact,
    transform_representation,
)


_INSTRUMENT = "BTCUSDT-PERP"
_MICRO_NAMES = ("flow", "oi")


def _geometry(
    *,
    instrument: str = _INSTRUMENT,
    decision: int = 100,
    sequence: int = 5,
    path_efficiency: Decimal = Decimal("6"),
    terminal_displacement_atr: Decimal = Decimal("0"),
    confirmation_delays: tuple[Decimal, ...] = (Decimal(1),) * 5,
) -> GeometryVector:
    return GeometryVector(
        instrument_id=instrument,
        terminal_sequence=sequence,
        terminal_kind=PivotKind.LOW,
        decision_time_us=decision,
        availability_time_us=decision,
        first_pivot_time_us=10,
        terminal_pivot_time_us=90,
        pivot_sequences=(1, 2, 3, 4, sequence),
        direction_normalized=True,
        swing_atr=(Decimal(1), Decimal(-1), Decimal(2), Decimal(-2)),
        log_duration_ratios=(Decimal(0), Decimal(0), Decimal(0)),
        swing_velocity=(Decimal(1), Decimal(-1), Decimal(2), Decimal(-2)),
        retracement_ratios=(Decimal(1), Decimal(2), Decimal(1)),
        terminal_displacement_atr=terminal_displacement_atr,
        path_efficiency=path_efficiency,
        terminal_leg_share=Decimal(1) / Decimal(3),
        confirmation_delays=confirmation_delays,
    )


def _micro(
    *,
    instrument: str = _INSTRUMENT,
    decision: int = 100,
    flow: Decimal = Decimal("1"),
    oi: Decimal = Decimal("2"),
    names: tuple[str, ...] = _MICRO_NAMES,
    values: tuple[Decimal, ...] | None = None,
) -> MicrostructureVector:
    if values is None:
        items = (("flow", flow), ("oi", oi))
    else:
        items = tuple(zip(names, values, strict=True))
    return MicrostructureVector(
        instrument_id=instrument,
        decision_time_us=decision,
        availability_time_us=decision,
        source_lineages=(),
        feature_items=items,
    )


def _row(
    *,
    instrument: str = _INSTRUMENT,
    decision: int = 100,
    sequence: int = 5,
    path_efficiency: Decimal = Decimal("6"),
    terminal_displacement_atr: Decimal = Decimal("0"),
    flow: Decimal = Decimal("1"),
    oi: Decimal = Decimal("2"),
    geometry: GeometryVector | None = None,
    microstructure: MicrostructureVector | None = None,
) -> MultimodalVector:
    geometry = geometry or _geometry(
        instrument=instrument,
        decision=decision,
        sequence=sequence,
        path_efficiency=path_efficiency,
        terminal_displacement_atr=terminal_displacement_atr,
    )
    microstructure = microstructure or _micro(
        instrument=instrument, decision=decision, flow=flow, oi=oi
    )
    return MultimodalVector(
        instrument_id=instrument,
        decision_time_us=decision,
        availability_time_us=decision,
        geometry=geometry,
        microstructure=microstructure,
    )


def _train() -> tuple[MultimodalVector, ...]:
    return (
        _row(decision=400, sequence=4, path_efficiency=Decimal("100"), flow=Decimal("8")),
        _row(decision=100, sequence=1, path_efficiency=Decimal("1"), flow=Decimal("1")),
        _row(decision=300, sequence=3, path_efficiency=Decimal("3"), flow=Decimal("3")),
        _row(decision=200, sequence=2, path_efficiency=Decimal("2"), flow=Decimal("2")),
    )


def _config() -> RepresentationConfig:
    return RepresentationConfig(geometry_weight=3.0, microstructure_weight=4.0)


def test_fit_records_linear_quantile_medians_and_iqrs() -> None:
    rows = _train()
    artifact = fit_representation(rows, _config())
    path_index = artifact.geometry_feature_names.index("path_efficiency")
    flow_index = artifact.microstructure_feature_names.index("flow")
    path_values = np.array([100.0, 1.0, 3.0, 2.0], dtype=np.float64)
    flow_values = np.array([8.0, 1.0, 3.0, 2.0], dtype=np.float64)
    expected_path = np.quantile(path_values, (0.25, 0.5, 0.75), method="linear")
    expected_flow = np.quantile(flow_values, (0.25, 0.5, 0.75), method="linear")
    assert artifact.geometry_medians[path_index] == 2.5
    assert artifact.geometry_iqrs[path_index] == 25.5
    assert artifact.geometry_medians[path_index] == float(expected_path[1])
    assert artifact.geometry_iqrs[path_index] == float(expected_path[2] - expected_path[0])
    assert artifact.microstructure_medians[flow_index] == float(expected_flow[1])
    assert artifact.microstructure_iqrs[flow_index] == float(
        expected_flow[2] - expected_flow[0]
    )
    delay_index = artifact.geometry_feature_names.index("confirmation_delay_1")
    assert artifact.geometry_iqrs[delay_index] == 0.0
    assert artifact.geometry_constant_mask[delay_index] is True
    assert artifact.geometry_constant_mask[path_index] is False


def test_blocks_fit_independently_and_full_applies_unit_norm_weights() -> None:
    rows = _train()
    artifact = fit_representation(rows, _config())
    shifted_micro = tuple(
        replace(
            row,
            microstructure=replace(
                row.microstructure,
                feature_items=(
                    ("flow", row.microstructure.feature_values[0] + Decimal("50")),
                    ("oi", Decimal("2")),
                ),
            ),
        )
        for row in rows
    )
    shifted_artifact = fit_representation(shifted_micro, _config())
    assert shifted_artifact.geometry_medians == artifact.geometry_medians
    assert shifted_artifact.geometry_iqrs == artifact.geometry_iqrs
    assert shifted_artifact.microstructure_medians != artifact.microstructure_medians

    transformed = transform_representation(artifact, rows)
    assert artifact.normalized_geometry_weight == 0.6
    assert artifact.normalized_microstructure_weight == 0.8
    np.testing.assert_allclose(
        transformed.full[:, : transformed.geometry.shape[1]],
        0.6 * transformed.geometry,
    )
    np.testing.assert_allclose(
        transformed.full[:, transformed.geometry.shape[1] :],
        0.8 * transformed.micro,
    )
    reweighted = fit_representation(
        rows, RepresentationConfig(geometry_weight=1.0, microstructure_weight=1.0)
    )
    reweighted_view = transform_representation(reweighted, rows)
    np.testing.assert_array_equal(reweighted_view.geometry, transformed.geometry)
    np.testing.assert_array_equal(reweighted_view.micro, transformed.micro)
    assert not np.array_equal(reweighted_view.full, transformed.full)


def _key(row: MultimodalVector) -> EventKey:
    return EventKey(
        row.instrument_id, row.decision_time_us, row.geometry.terminal_sequence
    )


def test_transform_emits_matched_sorted_keys_and_row_order() -> None:
    rows = _train() + (
        _row(
            instrument="ETHUSDT-PERP",
            decision=200,
            sequence=9,
            path_efficiency=Decimal("7"),
            flow=Decimal("4"),
        ),
    )
    transformed = transform_representation(fit_representation(rows, _config()), rows)
    expected = tuple(
        sorted(
            (_key(row) for row in rows),
            key=lambda key: (
                key.decision_time_us,
                key.instrument_id,
                key.terminal_sequence,
            ),
        )
    )
    assert transformed.keys == expected
    assert transformed.full.shape[0] == transformed.micro.shape[0] == len(expected)
    assert transformed.geometry.shape[0] == len(expected)
    path_index = transformed.geometry_feature_names.index("path_efficiency")
    originals = np.array(
        [
            float(row.geometry.path_efficiency)
            for row in sorted(
                rows,
                key=lambda row: (
                    row.decision_time_us,
                    row.instrument_id,
                    row.geometry.terminal_sequence,
                ),
            )
        ],
        dtype=np.float64,
    )
    np.testing.assert_array_equal(
        np.argsort(originals), np.argsort(transformed.geometry[:, path_index])
    )


def test_validation_rows_cannot_change_fitted_artifact_or_training_rows() -> None:
    train = _train()
    artifact = fit_representation(train, _config())
    before = artifact.to_bytes()
    medians = artifact.geometry_medians
    iqrs = artifact.geometry_iqrs
    training = transform_representation(artifact, train)
    extreme = _row(
        instrument="FUTURE",
        decision=10_000_000,
        sequence=99,
        path_efficiency=Decimal("1000000"),
        terminal_displacement_atr=Decimal("1000000"),
        flow=Decimal("1000000"),
        oi=Decimal("1000000"),
    )
    transform_representation(artifact, (*train, extreme))
    later_training = transform_representation(artifact, train)
    assert artifact.to_bytes() == before
    assert artifact.geometry_medians is medians
    assert artifact.geometry_iqrs is iqrs
    np.testing.assert_array_equal(later_training.full, training.full)
    contaminated = fit_representation((*train, extreme), _config())
    assert contaminated.geometry_medians != artifact.geometry_medians
    assert contaminated.sha256 != artifact.sha256


def test_affine_rescaling_of_training_features_is_invariant() -> None:
    rows = _train()
    baseline = transform_representation(fit_representation(rows, _config()), rows)
    scaled = tuple(
        replace(
            row,
            geometry=replace(
                row.geometry,
                path_efficiency=row.geometry.path_efficiency * Decimal("10") + Decimal("3"),
            ),
            microstructure=replace(
                row.microstructure,
                feature_items=(
                    (
                        "flow",
                        row.microstructure.feature_values[0] * Decimal("2") - Decimal("7"),
                    ),
                    ("oi", Decimal("2")),
                ),
            ),
        )
        for row in rows
    )
    scaled_view = transform_representation(fit_representation(scaled, _config()), scaled)
    np.testing.assert_allclose(scaled_view.full, baseline.full, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(scaled_view.geometry, baseline.geometry, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(scaled_view.micro, baseline.micro, rtol=1e-12, atol=1e-12)


def test_artifact_bytes_hash_and_parse_are_deterministic() -> None:
    rows = _train()
    first = fit_representation(rows, _config())
    second = fit_representation(tuple(reversed(rows)), _config())
    parsed = parse_representation_artifact(first.to_bytes())
    assert first.to_bytes() == second.to_bytes()
    assert first.sha256 == second.sha256
    assert parsed == first
    assert parsed.fit_row_keys == tuple(
        sorted(
            (_key(row) for row in rows),
            key=lambda key: (
                key.decision_time_us,
                key.instrument_id,
                key.terminal_sequence,
            ),
        )
    )
    pretty = json.dumps(first.to_payload(), indent=2).encode()
    with pytest.raises(RepresentationError, match="canonical"):
        parse_representation_artifact(pretty)
    with pytest.raises(RepresentationError, match="unexpected fields"):
        parse_representation_artifact(b'{"schema_version":1}\n')


@pytest.mark.parametrize(
    "config",
    [
        {"geometry_weight": 0.0, "microstructure_weight": 1.0},
        {"geometry_weight": -1.0, "microstructure_weight": 1.0},
        {"geometry_weight": float("nan"), "microstructure_weight": 1.0},
        {"geometry_weight": float("inf"), "microstructure_weight": 1.0},
        {"geometry_weight": True, "microstructure_weight": 1.0},
        {"geometry_weight": 1.0, "microstructure_weight": 1.0, "schema_version": 2},
    ],
)
def test_invalid_weights_fail_closed(config: dict[str, object]) -> None:
    with pytest.raises(RepresentationError):
        RepresentationConfig(**config)  # type: ignore[arg-type]


def test_duplicate_keys_schema_drift_and_empty_input_fail_closed() -> None:
    rows = _train()
    artifact = fit_representation(rows, _config())
    duplicate = (*rows, replace(rows[1], availability_time_us=rows[1].availability_time_us))
    with pytest.raises(RepresentationError, match="duplicate event keys"):
        fit_representation(duplicate, _config())
    drifted = replace(
        rows[0],
        microstructure=_micro(
            decision=rows[0].decision_time_us,
            names=("oi", "flow"),
            values=(Decimal("2"), Decimal("1")),
        ),
    )
    with pytest.raises(RepresentationError, match="inconsistent microstructure feature names"):
        fit_representation((drifted, *rows[1:]), _config())
    with pytest.raises(RepresentationError, match="incompatible microstructure feature schema"):
        transform_representation(artifact, (drifted, *rows[1:]))
    short_geometry = replace(
        rows[0],
        geometry=replace(rows[0].geometry, swing_atr=(Decimal(1), Decimal(-1), Decimal(2))),
    )
    with pytest.raises(RepresentationError, match="inconsistent geometry feature names"):
        fit_representation((short_geometry, *rows[1:]), _config())
    with pytest.raises(RepresentationError, match="training rows must be non-empty"):
        fit_representation((), _config())
    with pytest.raises(RepresentationError, match="transform rows must be non-empty"):
        transform_representation(artifact, ())


def test_non_finite_values_overflow_and_constant_blocks_fail_closed() -> None:
    rows = _train()
    nan_row = replace(rows[0], geometry=replace(rows[0].geometry, path_efficiency=Decimal("NaN")))
    inf_row = replace(
        rows[0], geometry=replace(rows[0].geometry, path_efficiency=Decimal("Infinity"))
    )
    overflow = replace(
        rows[0],
        microstructure=_micro(
            decision=rows[0].decision_time_us, flow=Decimal("1e400"), oi=Decimal("2")
        ),
    )
    with pytest.raises(RepresentationError, match="finite float64"):
        fit_representation((nan_row, *rows[1:]), _config())
    with pytest.raises(RepresentationError, match="finite float64"):
        fit_representation((inf_row, *rows[1:]), _config())
    with pytest.raises(RepresentationError, match="finite float64"):
        fit_representation((overflow, *rows[1:]), _config())

    constant_geometry = tuple(
        replace(row, geometry=replace(row.geometry, path_efficiency=Decimal("6"))) for row in rows
    )
    with pytest.raises(RepresentationError, match="all geometry columns are constant"):
        fit_representation(constant_geometry, _config())
    constant_micro = tuple(
        replace(
            row,
            microstructure=_micro(
                decision=row.decision_time_us, flow=Decimal("1"), oi=Decimal("2")
            ),
        )
        for row in rows
    )
    with pytest.raises(RepresentationError, match="all microstructure columns are constant"):
        fit_representation(constant_micro, _config())


def test_zero_iqr_columns_are_recorded_without_division_by_zero() -> None:
    artifact = fit_representation(_train(), _config())
    delay_names = [
        name
        for name in artifact.geometry_feature_names
        if name.startswith("confirmation_delay_")
    ]
    assert delay_names
    for name in delay_names:
        index = artifact.geometry_feature_names.index(name)
        assert artifact.geometry_constant_mask[index] is True
        assert artifact.geometry_iqrs[index] == 0.0
    transformed = transform_representation(artifact, _train())
    assert np.isfinite(transformed.geometry).all()
    assert np.isfinite(transformed.full).all()
    delay_index = artifact.geometry_feature_names.index("confirmation_delay_1")
    np.testing.assert_array_equal(transformed.geometry[:, delay_index], 0.0)


def test_matrices_are_float64_c_contiguous_and_read_only() -> None:
    transformed = transform_representation(fit_representation(_train(), _config()), _train())
    artifact = fit_representation(_train(), _config())
    snapshot = transformed.full.copy()
    for matrix in (transformed.full, transformed.micro, transformed.geometry):
        assert matrix.dtype == np.float64
        assert matrix.flags["C_CONTIGUOUS"]
        assert not matrix.flags["WRITEABLE"]
        with pytest.raises(ValueError):
            matrix.setflags(write=True)
        assert not matrix.flags["WRITEABLE"]
        with pytest.raises(ValueError, match="read-only"):
            matrix[0, 0] = 1.0
    np.testing.assert_array_equal(transformed.full, snapshot)
    assert isinstance(artifact.geometry_medians, tuple)
    assert isinstance(artifact.geometry_iqrs, tuple)
    assert isinstance(artifact.geometry_constant_mask, tuple)
    with pytest.raises(FrozenInstanceError):
        artifact.geometry_weight = 9.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        transformed.keys = ()  # type: ignore[misc]


def test_extreme_finite_weights_keep_unit_norm_block_weights() -> None:
    huge = 1.7e308
    equal = fit_representation(
        _train(), RepresentationConfig(geometry_weight=huge, microstructure_weight=huge)
    )
    mixed = fit_representation(
        _train(), RepresentationConfig(geometry_weight=huge, microstructure_weight=1.0)
    )
    for artifact in (equal, mixed):
        assert artifact.normalized_geometry_weight > 0.0
        assert artifact.normalized_microstructure_weight > 0.0
        assert math.isfinite(artifact.normalized_geometry_weight)
        assert math.isfinite(artifact.normalized_microstructure_weight)
        assert math.hypot(
            artifact.normalized_geometry_weight,
            artifact.normalized_microstructure_weight,
        ) == pytest.approx(1.0)
    transformed = transform_representation(mixed, _train())
    geo_width = transformed.geometry.shape[1]
    assert np.isfinite(transformed.full).all()
    assert np.any(transformed.full[:, :geo_width] != 0.0)
    assert np.any(transformed.full[:, geo_width:] != 0.0)


def test_negative_iqrs_fail_closed_on_construct_and_parse() -> None:
    artifact = fit_representation(_train(), _config())
    path_index = artifact.geometry_feature_names.index("path_efficiency")
    negative = list(artifact.geometry_iqrs)
    negative[path_index] = -1.0
    with pytest.raises(RepresentationError, match="IQR"):
        replace(artifact, geometry_iqrs=tuple(negative))
    payload = artifact.to_payload()
    payload["geometry_iqrs"][path_index] = -1.0
    raw = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")
    with pytest.raises(RepresentationError, match="IQR"):
        parse_representation_artifact(raw)


def test_ablation_matrices_contain_only_their_block_columns() -> None:
    rows = _train()
    transformed = transform_representation(fit_representation(rows, _config()), rows)
    geometry_names = rows[0].geometry.feature_names
    micro_names = rows[0].microstructure.feature_names
    assert transformed.geometry_feature_names == geometry_names
    assert transformed.micro_feature_names == micro_names
    assert transformed.full_feature_names == rows[0].feature_names
    assert set(transformed.geometry_feature_names).isdisjoint(transformed.micro_feature_names)
    assert all(
        not name.startswith("microstructure.")
        for name in transformed.geometry_feature_names
    )
    assert all(
        not name.startswith("geometry.") for name in transformed.micro_feature_names
    )
    assert transformed.geometry.shape[1] == len(geometry_names)
    assert transformed.micro.shape[1] == len(micro_names)
    assert transformed.full.shape[1] == len(geometry_names) + len(micro_names)
