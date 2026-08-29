"""Training-only robust scaling for matched FULL, MICRO, and GEOMETRY views."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import numpy as np

from harmonic_trader.features.state import MultimodalVector


class RepresentationError(ValueError):
    """A representation configuration, fit, or transform violates its contract."""


_SCHEMA_VERSION = 1
_ARTIFACT_FIELDS = {
    "schema_version",
    "geometry_feature_names",
    "microstructure_feature_names",
    "geometry_medians",
    "geometry_iqrs",
    "geometry_constant_mask",
    "microstructure_medians",
    "microstructure_iqrs",
    "microstructure_constant_mask",
    "geometry_weight",
    "microstructure_weight",
    "normalized_geometry_weight",
    "normalized_microstructure_weight",
    "fit_row_keys",
    "fit_row_keys_sha256",
}
_KEY_FIELDS = {"instrument_id", "decision_time_us", "terminal_sequence"}


def _canonical_json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _positive_finite_float(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RepresentationError(f"{field} must be a strictly positive finite number")
    converted = float(value)
    if not math.isfinite(converted) or converted <= 0:
        raise RepresentationError(f"{field} must be a strictly positive finite number")
    return converted


def _schema_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != _SCHEMA_VERSION:
        raise RepresentationError("unsupported representation schema version")
    return value


def _fitted_iqr(value: object) -> float:
    converted = _finite_float64(value, field="fitted IQR")
    if converted < 0.0:
        raise RepresentationError("fitted IQR must be non-negative")
    return converted


def _unit_block_weights(
    geometry_weight: float, microstructure_weight: float
) -> tuple[float, float]:
    if geometry_weight >= microstructure_weight:
        ratio = microstructure_weight / geometry_weight
        denom = math.sqrt(1.0 + ratio * ratio)
        normalized_geometry = 1.0 / denom
        normalized_microstructure = ratio / denom
    else:
        ratio = geometry_weight / microstructure_weight
        denom = math.sqrt(1.0 + ratio * ratio)
        normalized_geometry = ratio / denom
        normalized_microstructure = 1.0 / denom
    if (
        not math.isfinite(normalized_geometry)
        or not math.isfinite(normalized_microstructure)
        or normalized_geometry <= 0.0
        or normalized_microstructure <= 0.0
    ):
        raise RepresentationError(
            "normalized block weights must be strictly positive and finite"
        )
    return normalized_geometry, normalized_microstructure


def _finite_float64(value: object, *, field: str) -> float:
    if isinstance(value, bool):
        raise RepresentationError(f"{field} must be a finite float64")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise RepresentationError(f"{field} must be a finite float64")
        try:
            converted = float(value)
        except (OverflowError, InvalidOperation, ValueError) as exc:
            raise RepresentationError(f"{field} must be a finite float64") from exc
    elif isinstance(value, (int, float, np.floating, np.integer)):
        converted = float(value)
    else:
        raise RepresentationError(f"{field} must be a finite float64")
    as_float64 = np.float64(converted)
    if not np.isfinite(as_float64):
        raise RepresentationError(f"{field} must be a finite float64")
    return float(as_float64)


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise RepresentationError(f"{field} must be a string")
    result = value.strip()
    if not result:
        raise RepresentationError(f"{field} must be a non-empty string")
    return result


def _int_field(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RepresentationError(f"{field} must be an integer")
    return value


def _unique_names(names: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    if not names or any(not isinstance(name, str) or not name for name in names):
        raise RepresentationError(f"{field} must be a non-empty sequence of names")
    if len(names) != len(set(names)):
        raise RepresentationError(f"{field} must be unique")
    return names


def _bool_mask(values: tuple[object, ...], *, field: str) -> tuple[bool, ...]:
    if not values or any(not isinstance(value, bool) for value in values):
        raise RepresentationError(f"{field} must be a non-empty boolean mask")
    return tuple(values)


def _key_sort_item(key: EventKey) -> tuple[int, str, int]:
    return (key.decision_time_us, key.instrument_id, key.terminal_sequence)


def _keys_payload(keys: tuple[EventKey, ...]) -> list[dict[str, object]]:
    return [
        {
            "decision_time_us": key.decision_time_us,
            "instrument_id": key.instrument_id,
            "terminal_sequence": key.terminal_sequence,
        }
        for key in keys
    ]


def _freeze_array(array: np.ndarray) -> np.ndarray:
    owned = np.array(array, dtype=np.float64, order="C", copy=True)
    if owned.ndim != 2:
        raise RepresentationError("representation matrices must be two-dimensional")
    frozen = np.frombuffer(owned.tobytes(), dtype=np.float64).reshape(owned.shape)
    if not frozen.flags["C_CONTIGUOUS"] or frozen.flags["WRITEABLE"]:
        raise RepresentationError("representation matrices must be immutable")
    return frozen


def _event_key(row: MultimodalVector) -> EventKey:
    return EventKey(
        instrument_id=row.instrument_id,
        decision_time_us=row.decision_time_us,
        terminal_sequence=row.geometry.terminal_sequence,
    )


def _row_block(
    row: MultimodalVector, *, block: str
) -> tuple[tuple[str, ...], tuple[Decimal, ...]]:
    vector = row.geometry if block == "geometry" else row.microstructure
    return vector.feature_names, vector.feature_values


def _block_matrix(
    rows: tuple[MultimodalVector, ...],
    *,
    block: str,
    expected_names: tuple[str, ...] | None,
) -> tuple[tuple[str, ...], np.ndarray]:
    names: tuple[str, ...] | None = None
    values: list[list[float]] = []
    field = f"{block} features"
    for row in rows:
        row_names, row_values = _row_block(row, block=block)
        if names is None:
            names = _unique_names(row_names, field=f"{block} feature names")
        elif row_names != names:
            raise RepresentationError(f"inconsistent {block} feature names")
        if expected_names is not None and row_names != expected_names:
            raise RepresentationError(f"incompatible {block} feature schema")
        values.append([_finite_float64(value, field=field) for value in row_values])
    if names is None:
        raise RepresentationError("transform rows must be non-empty")
    if expected_names is not None and names != expected_names:
        raise RepresentationError(f"incompatible {block} feature schema")
    matrix = np.array(values, dtype=np.float64, order="C")
    if not np.isfinite(matrix).all():
        raise RepresentationError(f"{field} must be a finite float64")
    return names, matrix


def _materialize(
    rows: Sequence[MultimodalVector], *, empty_message: str
) -> tuple[MultimodalVector, ...]:
    try:
        materialized = tuple(rows)
    except TypeError as exc:
        raise RepresentationError(empty_message) from exc
    if not materialized:
        raise RepresentationError(empty_message)
    for row in materialized:
        if not isinstance(row, MultimodalVector):
            raise RepresentationError("rows must be MultimodalVector events")
    return materialized


def _extract(
    rows: Sequence[MultimodalVector],
    *,
    empty_message: str,
    geometry_names: tuple[str, ...] | None = None,
    microstructure_names: tuple[str, ...] | None = None,
) -> tuple[tuple[EventKey, ...], tuple[str, ...], tuple[str, ...], np.ndarray, np.ndarray]:
    materialized = _materialize(rows, empty_message=empty_message)
    keys = tuple(_event_key(row) for row in materialized)
    if len(set(keys)) != len(keys):
        raise RepresentationError("duplicate event keys")
    geometry_names, geometry = _block_matrix(
        materialized, block="geometry", expected_names=geometry_names
    )
    microstructure_names, microstructure = _block_matrix(
        materialized,
        block="microstructure",
        expected_names=microstructure_names,
    )
    return keys, geometry_names, microstructure_names, geometry, microstructure


def _fit_block(
    matrix: np.ndarray, *, block: str
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[bool, ...]]:
    medians: list[float] = []
    iqrs: list[float] = []
    constants: list[bool] = []
    for index in range(matrix.shape[1]):
        quantiles = np.quantile(
            matrix[:, index], (0.25, 0.5, 0.75), method="linear"
        )
        if not np.isfinite(quantiles).all():
            raise RepresentationError("non-finite fitted statistics")
        q1, median, q3 = (float(value) for value in quantiles)
        iqr = _fitted_iqr(q3 - q1)
        medians.append(_finite_float64(median, field="fitted median"))
        iqrs.append(iqr)
        constants.append(iqr == 0.0)
    if all(constants):
        raise RepresentationError(f"all {block} columns are constant")
    return tuple(medians), tuple(iqrs), tuple(constants)


def _scale_block(
    matrix: np.ndarray,
    *,
    medians: tuple[float, ...],
    iqrs: tuple[float, ...],
    constant_mask: tuple[bool, ...],
    block: str,
) -> np.ndarray:
    nonconstant = sum(1 for flag in constant_mask if not flag)
    if nonconstant == 0:
        raise RepresentationError(f"all {block} columns are constant")
    median = np.asarray(medians, dtype=np.float64)
    iqr = np.asarray(iqrs, dtype=np.float64)
    scale = np.where(iqr == 0.0, 1.0, iqr)
    scaled = (matrix - median) / scale
    if not np.isfinite(scaled).all():
        raise RepresentationError(f"{block} features must be a finite float64")
    return scaled / math.sqrt(nonconstant)


def _sort_permutation(keys: tuple[EventKey, ...]) -> tuple[int, ...]:
    return tuple(sorted(range(len(keys)), key=lambda index: _key_sort_item(keys[index])))


@dataclass(frozen=True, slots=True)
class RepresentationConfig:
    """Frozen strictly positive weights for the two representation blocks."""

    geometry_weight: float
    microstructure_weight: float
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))
        object.__setattr__(
            self,
            "geometry_weight",
            _positive_finite_float(self.geometry_weight, field="geometry_weight"),
        )
        object.__setattr__(
            self,
            "microstructure_weight",
            _positive_finite_float(
                self.microstructure_weight, field="microstructure_weight"
            ),
        )


@dataclass(frozen=True, slots=True)
class EventKey:
    """Canonical identity of one multimodal event row."""

    instrument_id: str
    decision_time_us: int
    terminal_sequence: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "instrument_id", _text(self.instrument_id, field="instrument_id")
        )
        object.__setattr__(
            self,
            "decision_time_us",
            _int_field(self.decision_time_us, field="decision_time_us"),
        )
        object.__setattr__(
            self,
            "terminal_sequence",
            _int_field(self.terminal_sequence, field="terminal_sequence"),
        )


@dataclass(frozen=True, slots=True)
class RepresentationArtifact:
    """Immutable training-only robust-scaling identity."""

    geometry_feature_names: tuple[str, ...]
    microstructure_feature_names: tuple[str, ...]
    geometry_medians: tuple[float, ...]
    geometry_iqrs: tuple[float, ...]
    geometry_constant_mask: tuple[bool, ...]
    microstructure_medians: tuple[float, ...]
    microstructure_iqrs: tuple[float, ...]
    microstructure_constant_mask: tuple[bool, ...]
    geometry_weight: float
    microstructure_weight: float
    fit_row_keys: tuple[EventKey, ...]
    normalized_geometry_weight: float = 0.0
    normalized_microstructure_weight: float = 0.0
    fit_row_keys_sha256: str = ""
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))
        geometry_names = _unique_names(
            tuple(self.geometry_feature_names), field="geometry feature names"
        )
        micro_names = _unique_names(
            tuple(self.microstructure_feature_names),
            field="microstructure feature names",
        )
        object.__setattr__(self, "geometry_feature_names", geometry_names)
        object.__setattr__(self, "microstructure_feature_names", micro_names)
        geometry_medians = tuple(
            _finite_float64(value, field="fitted median")
            for value in self.geometry_medians
        )
        geometry_iqrs = tuple(_fitted_iqr(value) for value in self.geometry_iqrs)
        micro_medians = tuple(
            _finite_float64(value, field="fitted median")
            for value in self.microstructure_medians
        )
        micro_iqrs = tuple(_fitted_iqr(value) for value in self.microstructure_iqrs)
        geometry_mask = _bool_mask(
            tuple(self.geometry_constant_mask), field="geometry constant-column mask"
        )
        micro_mask = _bool_mask(
            tuple(self.microstructure_constant_mask),
            field="microstructure constant-column mask",
        )
        if not (
            len(geometry_names)
            == len(geometry_medians)
            == len(geometry_iqrs)
            == len(geometry_mask)
        ):
            raise RepresentationError("incompatible geometry artifact schema")
        if not (
            len(micro_names) == len(micro_medians) == len(micro_iqrs) == len(micro_mask)
        ):
            raise RepresentationError("incompatible microstructure artifact schema")
        if tuple(iqr == 0.0 for iqr in geometry_iqrs) != geometry_mask:
            raise RepresentationError("geometry constant-column mask does not match IQR")
        if tuple(iqr == 0.0 for iqr in micro_iqrs) != micro_mask:
            raise RepresentationError(
                "microstructure constant-column mask does not match IQR"
            )
        if all(geometry_mask):
            raise RepresentationError("all geometry columns are constant")
        if all(micro_mask):
            raise RepresentationError("all microstructure columns are constant")
        object.__setattr__(self, "geometry_medians", geometry_medians)
        object.__setattr__(self, "geometry_iqrs", geometry_iqrs)
        object.__setattr__(self, "geometry_constant_mask", geometry_mask)
        object.__setattr__(self, "microstructure_medians", micro_medians)
        object.__setattr__(self, "microstructure_iqrs", micro_iqrs)
        object.__setattr__(self, "microstructure_constant_mask", micro_mask)
        geometry_weight = _positive_finite_float(
            self.geometry_weight, field="geometry_weight"
        )
        microstructure_weight = _positive_finite_float(
            self.microstructure_weight, field="microstructure_weight"
        )
        normalized_geometry, normalized_microstructure = _unit_block_weights(
            geometry_weight, microstructure_weight
        )
        object.__setattr__(self, "geometry_weight", geometry_weight)
        object.__setattr__(self, "microstructure_weight", microstructure_weight)
        object.__setattr__(self, "normalized_geometry_weight", normalized_geometry)
        object.__setattr__(
            self, "normalized_microstructure_weight", normalized_microstructure
        )
        keys = tuple(self.fit_row_keys)
        if not keys or any(not isinstance(key, EventKey) for key in keys):
            raise RepresentationError("fit-row keys must be EventKey values")
        if len(set(keys)) != len(keys):
            raise RepresentationError("duplicate event keys")
        keys = tuple(sorted(keys, key=_key_sort_item))
        object.__setattr__(self, "fit_row_keys", keys)
        object.__setattr__(
            self,
            "fit_row_keys_sha256",
            _sha256_hex(_canonical_json_bytes(_keys_payload(keys))),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "geometry_feature_names": list(self.geometry_feature_names),
            "microstructure_feature_names": list(self.microstructure_feature_names),
            "geometry_medians": list(self.geometry_medians),
            "geometry_iqrs": list(self.geometry_iqrs),
            "geometry_constant_mask": list(self.geometry_constant_mask),
            "microstructure_medians": list(self.microstructure_medians),
            "microstructure_iqrs": list(self.microstructure_iqrs),
            "microstructure_constant_mask": list(self.microstructure_constant_mask),
            "geometry_weight": self.geometry_weight,
            "microstructure_weight": self.microstructure_weight,
            "normalized_geometry_weight": self.normalized_geometry_weight,
            "normalized_microstructure_weight": self.normalized_microstructure_weight,
            "fit_row_keys": _keys_payload(self.fit_row_keys),
            "fit_row_keys_sha256": self.fit_row_keys_sha256,
        }

    def to_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_payload())

    @property
    def sha256(self) -> str:
        return _sha256_hex(self.to_bytes())

    @property
    def full_feature_names(self) -> tuple[str, ...]:
        return tuple(f"geometry.{name}" for name in self.geometry_feature_names) + tuple(
            f"microstructure.{name}" for name in self.microstructure_feature_names
        )


@dataclass(frozen=True, slots=True)
class TransformedRepresentation:
    """Matched FULL, MICRO, and GEOMETRY matrices for the same event keys."""

    keys: tuple[EventKey, ...]
    full: np.ndarray
    micro: np.ndarray
    geometry: np.ndarray
    full_feature_names: tuple[str, ...]
    micro_feature_names: tuple[str, ...]
    geometry_feature_names: tuple[str, ...]

    def __post_init__(self) -> None:
        keys = tuple(self.keys)
        if not keys or any(not isinstance(key, EventKey) for key in keys):
            raise RepresentationError("transformed keys must be EventKey values")
        if len(set(keys)) != len(keys):
            raise RepresentationError("duplicate event keys")
        if tuple(sorted(keys, key=_key_sort_item)) != keys:
            raise RepresentationError("transformed keys must be in canonical order")
        object.__setattr__(self, "keys", keys)
        full = _freeze_array(self.full)
        micro = _freeze_array(self.micro)
        geometry = _freeze_array(self.geometry)
        geometry_names = _unique_names(
            tuple(self.geometry_feature_names), field="geometry feature names"
        )
        micro_names = _unique_names(
            tuple(self.micro_feature_names), field="microstructure feature names"
        )
        full_names = _unique_names(
            tuple(self.full_feature_names), field="full feature names"
        )
        if full_names != tuple(f"geometry.{name}" for name in geometry_names) + tuple(
            f"microstructure.{name}" for name in micro_names
        ):
            raise RepresentationError("incompatible full feature schema")
        if not (
            full.shape[0]
            == micro.shape[0]
            == geometry.shape[0]
            == len(keys)
        ):
            raise RepresentationError("matched views must share one row order and count")
        if geometry.shape[1] != len(geometry_names) or micro.shape[1] != len(micro_names):
            raise RepresentationError("incompatible block feature schema")
        if full.shape[1] != len(full_names):
            raise RepresentationError("incompatible full feature schema")
        object.__setattr__(self, "full", full)
        object.__setattr__(self, "micro", micro)
        object.__setattr__(self, "geometry", geometry)
        object.__setattr__(self, "full_feature_names", full_names)
        object.__setattr__(self, "micro_feature_names", micro_names)
        object.__setattr__(self, "geometry_feature_names", geometry_names)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TransformedRepresentation):
            return NotImplemented
        return (
            self.keys == other.keys
            and self.full_feature_names == other.full_feature_names
            and self.micro_feature_names == other.micro_feature_names
            and self.geometry_feature_names == other.geometry_feature_names
            and np.array_equal(self.full, other.full)
            and np.array_equal(self.micro, other.micro)
            and np.array_equal(self.geometry, other.geometry)
        )


def fit_representation(
    rows: Sequence[MultimodalVector], config: RepresentationConfig
) -> RepresentationArtifact:
    """Fit block-wise median/IQR statistics on training rows only."""

    if not isinstance(config, RepresentationConfig):
        raise RepresentationError("config must be a RepresentationConfig")
    keys, geometry_names, micro_names, geometry, micro = _extract(
        rows, empty_message="training rows must be non-empty"
    )
    geometry_medians, geometry_iqrs, geometry_mask = _fit_block(
        geometry, block="geometry"
    )
    micro_medians, micro_iqrs, micro_mask = _fit_block(micro, block="microstructure")
    return RepresentationArtifact(
        geometry_feature_names=geometry_names,
        microstructure_feature_names=micro_names,
        geometry_medians=geometry_medians,
        geometry_iqrs=geometry_iqrs,
        geometry_constant_mask=geometry_mask,
        microstructure_medians=micro_medians,
        microstructure_iqrs=micro_iqrs,
        microstructure_constant_mask=micro_mask,
        geometry_weight=config.geometry_weight,
        microstructure_weight=config.microstructure_weight,
        fit_row_keys=keys,
    )


def transform_representation(
    artifact: RepresentationArtifact, rows: Sequence[MultimodalVector]
) -> TransformedRepresentation:
    """Apply a frozen artifact without refitting."""

    if not isinstance(artifact, RepresentationArtifact):
        raise RepresentationError("artifact must be a RepresentationArtifact")
    if artifact.schema_version != _SCHEMA_VERSION:
        raise RepresentationError("unsupported representation schema version")
    keys, _, _, geometry, micro = _extract(
        rows,
        empty_message="transform rows must be non-empty",
        geometry_names=artifact.geometry_feature_names,
        microstructure_names=artifact.microstructure_feature_names,
    )
    geometry_view = _scale_block(
        geometry,
        medians=artifact.geometry_medians,
        iqrs=artifact.geometry_iqrs,
        constant_mask=artifact.geometry_constant_mask,
        block="geometry",
    )
    micro_view = _scale_block(
        micro,
        medians=artifact.microstructure_medians,
        iqrs=artifact.microstructure_iqrs,
        constant_mask=artifact.microstructure_constant_mask,
        block="microstructure",
    )
    full = np.concatenate(
        (
            artifact.normalized_geometry_weight * geometry_view,
            artifact.normalized_microstructure_weight * micro_view,
        ),
        axis=1,
    )
    order = np.asarray(_sort_permutation(keys), dtype=np.intp)
    sorted_keys = tuple(keys[index] for index in order)
    return TransformedRepresentation(
        keys=sorted_keys,
        full=full[order],
        micro=micro_view[order],
        geometry=geometry_view[order],
        full_feature_names=artifact.full_feature_names,
        micro_feature_names=artifact.microstructure_feature_names,
        geometry_feature_names=artifact.geometry_feature_names,
    )


def parse_representation_artifact(raw: bytes) -> RepresentationArtifact:
    try:
        payload: Any = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RepresentationError(f"invalid representation JSON: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != _ARTIFACT_FIELDS:
        raise RepresentationError("representation artifact has unexpected fields")
    key_payloads = payload["fit_row_keys"]
    if not isinstance(key_payloads, list):
        raise RepresentationError("fit-row keys must be a list")
    keys: list[EventKey] = []
    for item in key_payloads:
        if not isinstance(item, dict) or set(item) != _KEY_FIELDS:
            raise RepresentationError("fit-row key has unexpected fields")
        try:
            keys.append(
                EventKey(
                    instrument_id=item["instrument_id"],
                    decision_time_us=item["decision_time_us"],
                    terminal_sequence=item["terminal_sequence"],
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RepresentationError(f"invalid fit-row key: {exc}") from exc
    try:
        artifact = RepresentationArtifact(
            schema_version=payload["schema_version"],
            geometry_feature_names=tuple(payload["geometry_feature_names"]),
            microstructure_feature_names=tuple(payload["microstructure_feature_names"]),
            geometry_medians=tuple(payload["geometry_medians"]),
            geometry_iqrs=tuple(payload["geometry_iqrs"]),
            geometry_constant_mask=tuple(payload["geometry_constant_mask"]),
            microstructure_medians=tuple(payload["microstructure_medians"]),
            microstructure_iqrs=tuple(payload["microstructure_iqrs"]),
            microstructure_constant_mask=tuple(payload["microstructure_constant_mask"]),
            geometry_weight=payload["geometry_weight"],
            microstructure_weight=payload["microstructure_weight"],
            normalized_geometry_weight=payload["normalized_geometry_weight"],
            normalized_microstructure_weight=payload["normalized_microstructure_weight"],
            fit_row_keys=tuple(keys),
            fit_row_keys_sha256=payload["fit_row_keys_sha256"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RepresentationError(f"invalid representation artifact: {exc}") from exc
    if raw != artifact.to_bytes():
        raise RepresentationError("representation artifact is not canonical JSON")
    return artifact
