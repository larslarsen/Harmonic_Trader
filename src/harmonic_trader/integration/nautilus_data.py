"""Registered NautilusTrader custom-data envelope for CausalObservation."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar, Final

import pyarrow as pa
from nautilus_trader.model import CustomData, DataType, register_custom_data_class
from nautilus_trader.persistence import ParquetDataCatalog

from harmonic_trader.data.contracts import (
    BasisObservation,
    CausalObservation,
    CostCalibrationObservation,
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

TYPE_NAME: Final = "HarmonicObservationData"
SCHEMA_VERSION: Final = "1"
_U64_MAX: Final = (1 << 64) - 1
_US_TO_NS: Final = 1_000
_MAX_MICROSECONDS: Final = _U64_MAX // _US_TO_NS
_REGISTERED = False
_REGISTER_LOCK = threading.Lock()
_ARROW_METADATA_FIELDS: Final = frozenset(
    {"instrument_id", "product", "schema_version", "type_name"}
)
_ARROW_ROW_FIELDS: Final = frozenset(
    {"payload", "payload_sha256", "ts_event", "ts_init"}
)

_DECIMAL_FIELDS: Final[dict[str, frozenset[str]]] = {
    "MarketBarObservation": frozenset(
        {"open", "high", "low", "close", "base_volume", "quote_volume"}
    ),
    "TradeFlowObservation": frozenset({"total_quote_volume", "taker_buy_quote_volume"}),
    "OpenInterestObservation": frozenset(
        {"native_quantity", "base_quantity", "notional_usd", "conversion_price"}
    ),
    "FundingObservation": frozenset({"rate"}),
    "BasisObservation": frozenset({"mark_price", "index_price", "basis_ratio"}),
    "LiquidationObservation": frozenset({"long_liquidation_usd", "short_liquidation_usd"}),
    "CostCalibrationObservation": frozenset(
        {
            "bid_price",
            "ask_price",
            "bid_depth_usd",
            "ask_depth_usd",
            "maker_fee_rate",
            "taker_fee_rate",
        }
    ),
}
_INT_FIELDS: Final[dict[str, frozenset[str]]] = {
    "MarketBarObservation": frozenset({"period_start_us", "period_end_us"}),
    "TradeFlowObservation": frozenset({"period_start_us", "period_end_us"}),
    "OpenInterestObservation": frozenset(),
    "FundingObservation": frozenset({"effective_time_us", "interval_us"}),
    "BasisObservation": frozenset(),
    "LiquidationObservation": frozenset({"period_start_us", "period_end_us"}),
    "CostCalibrationObservation": frozenset(),
}
_BOOL_FIELDS: Final[dict[str, frozenset[str]]] = {
    "MarketBarObservation": frozenset(),
    "TradeFlowObservation": frozenset(),
    "OpenInterestObservation": frozenset(),
    "FundingObservation": frozenset({"positive_rate_long_pays_short"}),
    "BasisObservation": frozenset(),
    "LiquidationObservation": frozenset({"venue_publication_censored"}),
    "CostCalibrationObservation": frozenset(),
}
_TYPE_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "MarketBarObservation": (
        "meta",
        "period_start_us",
        "period_end_us",
        "open",
        "high",
        "low",
        "close",
        "base_volume",
        "quote_volume",
    ),
    "TradeFlowObservation": (
        "meta",
        "period_start_us",
        "period_end_us",
        "total_quote_volume",
        "taker_buy_quote_volume",
    ),
    "OpenInterestObservation": (
        "meta",
        "native_quantity",
        "base_quantity",
        "notional_usd",
        "conversion_price",
    ),
    "FundingObservation": (
        "meta",
        "kind",
        "rate",
        "effective_time_us",
        "interval_us",
        "positive_rate_long_pays_short",
    ),
    "BasisObservation": ("meta", "mark_price", "index_price", "basis_ratio"),
    "LiquidationObservation": (
        "meta",
        "period_start_us",
        "period_end_us",
        "long_liquidation_usd",
        "short_liquidation_usd",
        "venue_publication_censored",
    ),
    "CostCalibrationObservation": (
        "meta",
        "bid_price",
        "ask_price",
        "bid_depth_usd",
        "ask_depth_usd",
        "maker_fee_rate",
        "taker_fee_rate",
    ),
}
_CONSTRUCTORS: Final[dict[str, type[CausalObservation]]] = {
    "MarketBarObservation": MarketBarObservation,
    "TradeFlowObservation": TradeFlowObservation,
    "OpenInterestObservation": OpenInterestObservation,
    "FundingObservation": FundingObservation,
    "BasisObservation": BasisObservation,
    "LiquidationObservation": LiquidationObservation,
    "CostCalibrationObservation": CostCalibrationObservation,
}
_TAG_BY_TYPE: Final[dict[type[CausalObservation], str]] = {
    cls: name for name, cls in _CONSTRUCTORS.items()
}
_META_FIELDS: Final = frozenset(
    {
        "product",
        "instrument_id",
        "event_time_us",
        "source_available_at_us",
        "retrieved_at_us",
        "lineage",
    }
)
_LINEAGE_FIELDS: Final = frozenset({"dataset_id", "manifest_sha256", "raw_identity"})
_ENVELOPE_FIELDS: Final = frozenset({"payload", "payload_sha256", "ts_event", "ts_init"})
_METADATA_FIELDS: Final = frozenset({"schema_version", "product", "instrument_id"})
_ARROW_SCHEMA: Final = pa.schema(
    [
        pa.field("payload", pa.string(), nullable=False),
        pa.field("payload_sha256", pa.string(), nullable=False),
        pa.field("ts_event", pa.uint64(), nullable=False),
        pa.field("ts_init", pa.uint64(), nullable=False),
    ]
)


class NautilusDataError(ValueError):
    """A custom-data envelope, codec, or catalog mapping violates its contract."""


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


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise NautilusDataError(f"{field} must be a non-empty string")
    return value


def _int_field(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NautilusDataError(f"{field} must be an integer")
    return value


def _bool_field(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise NautilusDataError(f"{field} must be a boolean")
    return value


def _decimal_text(value: object, *, field: str) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise NautilusDataError(f"{field} must be a finite decimal")
    return str(value)


def _decimal_from_text(value: object, *, field: str) -> Decimal:
    if not isinstance(value, str):
        raise NautilusDataError(f"{field} must be an exact decimal string")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise NautilusDataError(f"{field} must be an exact decimal string") from exc
    if not result.is_finite():
        raise NautilusDataError(f"{field} must be an exact decimal string")
    if str(result) != value:
        raise NautilusDataError(f"{field} is not canonical decimal text")
    return result


def _uint64(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > _U64_MAX:
        raise NautilusDataError(f"{field} must be a non-boolean unsigned-64-bit integer")
    return value


def _sha256_field(value: object, *, field: str) -> str:
    result = _text(value, field=field).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise NautilusDataError(f"{field} must be a lowercase SHA-256")
    return result


def _exact_fields(payload: Mapping[str, object], expected: frozenset[str], *, field: str) -> None:
    if set(payload) != expected:
        raise NautilusDataError(f"{field} has unexpected keys")


def catalog_identifier(*, product: str, instrument_id: str) -> str:
    """Return a delimiter-safe persistence identity for one catalog partition."""

    return _sha256_hex(
        _canonical_json_bytes(
            {
                "instrument_id": _text(instrument_id, field="instrument_id"),
                "product": _text(product, field="product"),
                "schema_version": SCHEMA_VERSION,
            }
        )
    )


def observation_clocks(observation: CausalObservation) -> tuple[int, int]:
    """Map event and source-availability microseconds onto Nautilus nanosecond clocks."""

    available = observation.meta.source_available_at_us
    if available is None:
        raise NautilusDataError("source_available_at_us must be known")
    event = observation.meta.event_time_us
    if isinstance(event, bool) or isinstance(available, bool):
        raise NautilusDataError("causal clocks cannot be booleans")
    if event < 0 or available < 0:
        raise NautilusDataError("causal clocks cannot be negative")
    if event > _MAX_MICROSECONDS or available > _MAX_MICROSECONDS:
        raise NautilusDataError("causal clocks overflow the unsigned-64-bit nanosecond range")
    return event * _US_TO_NS, available * _US_TO_NS


def _lineage_payload(lineage: ReleaseLineage) -> dict[str, str]:
    return {
        "dataset_id": lineage.dataset_id,
        "manifest_sha256": lineage.manifest_sha256,
        "raw_identity": lineage.raw_identity,
    }


def _meta_payload(meta: ObservationMeta) -> dict[str, object]:
    return {
        "event_time_us": meta.event_time_us,
        "instrument_id": meta.instrument_id,
        "lineage": _lineage_payload(meta.lineage),
        "product": meta.product.value,
        "retrieved_at_us": meta.retrieved_at_us,
        "source_available_at_us": meta.source_available_at_us,
    }


def _observation_tag(observation: CausalObservation) -> str:
    tag = _TAG_BY_TYPE.get(type(observation))
    if tag is None:
        raise NautilusDataError("unsupported observation type")
    return tag


def observation_payload(observation: CausalObservation) -> dict[str, object]:
    tag = _observation_tag(observation)
    payload: dict[str, object] = {
        "observation_type": tag,
        "schema_version": 1,
        "meta": _meta_payload(observation.meta),
    }
    for field in _TYPE_FIELDS[tag]:
        if field == "meta":
            continue
        value = getattr(observation, field)
        if field in _DECIMAL_FIELDS[tag]:
            payload[field] = _decimal_text(value, field=field)
        elif field == "kind":
            if not isinstance(value, FundingKind):
                raise NautilusDataError("kind must be a FundingKind")
            payload[field] = value.value
        elif field in _BOOL_FIELDS[tag]:
            payload[field] = _bool_field(value, field=field)
        else:
            payload[field] = _int_field(value, field=field)
    return payload


def encode_observation(observation: CausalObservation) -> bytes:
    return _canonical_json_bytes(observation_payload(observation))


def observation_sha256(observation: CausalObservation) -> str:
    return _sha256_hex(encode_observation(observation))


def _decode_lineage(payload: object) -> ReleaseLineage:
    if not isinstance(payload, dict):
        raise NautilusDataError("lineage must be an object")
    _exact_fields(payload, _LINEAGE_FIELDS, field="lineage")
    return ReleaseLineage(
        dataset_id=_text(payload["dataset_id"], field="dataset_id"),
        manifest_sha256=_sha256_field(payload["manifest_sha256"], field="manifest_sha256"),
        raw_identity=_text(payload["raw_identity"], field="raw_identity"),
    )


def _decode_meta(payload: object) -> ObservationMeta:
    if not isinstance(payload, dict):
        raise NautilusDataError("meta must be an object")
    _exact_fields(payload, _META_FIELDS, field="meta")
    try:
        product = Product(payload["product"])
    except ValueError as exc:
        raise NautilusDataError("unknown product value") from exc
    available = payload["source_available_at_us"]
    if available is not None:
        available = _int_field(available, field="source_available_at_us")
    return ObservationMeta(
        product=product,
        instrument_id=_text(payload["instrument_id"], field="instrument_id"),
        event_time_us=_int_field(payload["event_time_us"], field="event_time_us"),
        source_available_at_us=available,
        retrieved_at_us=_int_field(payload["retrieved_at_us"], field="retrieved_at_us"),
        lineage=_decode_lineage(payload["lineage"]),
    )


def decode_observation(raw: bytes | str) -> CausalObservation:
    if isinstance(raw, str):
        raw_bytes = raw.encode("ascii")
    elif isinstance(raw, (bytes, bytearray)):
        raw_bytes = bytes(raw)
    else:
        raise NautilusDataError("observation payload must be canonical UTF-8 JSON")
    try:
        payload: Any = json.loads(raw_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise NautilusDataError(f"invalid observation JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise NautilusDataError("observation payload must be an object")
    tag = payload.get("observation_type")
    if tag not in _TYPE_FIELDS:
        raise NautilusDataError("unknown observation type")
    expected = frozenset(("observation_type", "schema_version", *_TYPE_FIELDS[tag]))
    _exact_fields(payload, expected, field="observation payload")
    if payload.get("schema_version") != 1:
        raise NautilusDataError("unsupported observation schema version")
    values: dict[str, object] = {"meta": _decode_meta(payload["meta"])}
    for field in _TYPE_FIELDS[tag]:
        if field == "meta":
            continue
        if field in _DECIMAL_FIELDS[tag]:
            values[field] = _decimal_from_text(payload[field], field=field)
        elif field == "kind":
            try:
                values[field] = FundingKind(payload[field])
            except ValueError as exc:
                raise NautilusDataError("unknown funding kind") from exc
        elif field in _BOOL_FIELDS[tag]:
            values[field] = _bool_field(payload[field], field=field)
        else:
            values[field] = _int_field(payload[field], field=field)
    try:
        observation = _CONSTRUCTORS[tag](**values)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise NautilusDataError(f"invalid observation: {exc}") from exc
    encoded = encode_observation(observation)
    if encoded != raw_bytes:
        raise NautilusDataError("observation payload is not canonical JSON")
    return observation


def observation_data_type(observation: CausalObservation) -> DataType:
    product = observation.meta.product.value
    instrument_id = observation.meta.instrument_id
    return DataType(
        TYPE_NAME,
        metadata={
            "instrument_id": instrument_id,
            "product": product,
            "schema_version": SCHEMA_VERSION,
        },
        identifier=catalog_identifier(product=product, instrument_id=instrument_id),
    )


@dataclass(frozen=True, slots=True)
class HarmonicObservationData:
    """Frozen registered payload for one causal observation wrapper."""

    ts_event: int
    ts_init: int
    payload: str
    payload_sha256: str
    _schema: ClassVar[pa.Schema] = _ARROW_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "ts_event", _uint64(self.ts_event, field="ts_event"))
        object.__setattr__(self, "ts_init", _uint64(self.ts_init, field="ts_init"))
        payload = self.payload if isinstance(self.payload, str) else None
        if payload is None:
            raise NautilusDataError("payload must be canonical UTF-8 JSON text")
        observation = decode_observation(payload)
        digest = _sha256_hex(payload.encode("ascii"))
        expected = _sha256_field(self.payload_sha256, field="payload_sha256")
        if digest != expected:
            raise NautilusDataError("payload SHA-256 does not match canonical payload")
        ts_event, ts_init = observation_clocks(observation)
        if ts_event != self.ts_event or ts_init != self.ts_init:
            raise NautilusDataError("wrapper timestamps do not match the observation clocks")
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "payload_sha256", expected)

    @property
    def observation(self) -> CausalObservation:
        return decode_observation(self.payload)

    @classmethod
    def type_name_static(cls) -> str:
        return TYPE_NAME

    def to_json(self) -> str:
        return json.dumps(
            {
                "payload": self.payload,
                "payload_sha256": self.payload_sha256,
                "ts_event": self.ts_event,
                "ts_init": self.ts_init,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )

    @classmethod
    def from_json(cls, data: object) -> HarmonicObservationData:
        raw_text: str | None = None
        if isinstance(data, (bytes, bytearray)):
            try:
                raw_text = bytes(data).decode("ascii")
            except UnicodeError as exc:
                raise NautilusDataError("envelope JSON must be ASCII") from exc
        elif isinstance(data, str):
            raw_text = data
        if raw_text is not None:
            try:
                data = json.loads(raw_text)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise NautilusDataError(f"invalid envelope JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise NautilusDataError("envelope payload must be an object")
        _exact_fields(data, _ENVELOPE_FIELDS, field="envelope")
        instance = cls(
            ts_event=data["ts_event"],
            ts_init=data["ts_init"],
            payload=data["payload"],
            payload_sha256=data["payload_sha256"],
        )
        if raw_text is not None and raw_text != instance.to_json():
            raise NautilusDataError("envelope JSON is not canonical")
        return instance

    def encode_record_batch_py(self, items: Sequence[HarmonicObservationData]) -> pa.RecordBatch:
        rows = []
        for item in items:
            if not isinstance(item, HarmonicObservationData):
                raise NautilusDataError("Arrow items must be HarmonicObservationData")
            rows.append(
                {
                    "payload": item.payload,
                    "payload_sha256": item.payload_sha256,
                    "ts_event": item.ts_event,
                    "ts_init": item.ts_init,
                }
            )
        if not rows:
            raise NautilusDataError("Arrow encoding requires at least one item")
        return pa.RecordBatch.from_pylist(rows, schema=_ARROW_SCHEMA)

    @classmethod
    def decode_record_batch_py(
        cls, metadata: object, batch: object
    ) -> list[HarmonicObservationData]:
        if not isinstance(metadata, Mapping):
            raise NautilusDataError("Arrow metadata must be a string mapping")
        if set(metadata) != _ARROW_METADATA_FIELDS:
            raise NautilusDataError("Arrow metadata has unexpected keys")
        for key, value in metadata.items():
            if type(key) is not str or type(value) is not str:
                raise NautilusDataError("Arrow metadata must be a string mapping")
        if metadata["type_name"] != TYPE_NAME:
            raise NautilusDataError("Arrow metadata type name does not match")
        if metadata["schema_version"] != SCHEMA_VERSION:
            raise NautilusDataError("Arrow metadata schema version does not match")
        if not isinstance(batch, pa.RecordBatch):
            raise NautilusDataError("Arrow batch is not a record batch")
        names = set(batch.schema.names)
        if not _ARROW_ROW_FIELDS <= names:
            raise NautilusDataError("Arrow batch is missing required fields")
        extra = names - _ARROW_ROW_FIELDS
        if extra - {"data_type"}:
            raise NautilusDataError("Arrow batch has unexpected fields")
        for field in _ARROW_SCHEMA:
            actual = batch.schema.field(field.name)
            if field.name in {"payload", "payload_sha256"}:
                if not (
                    pa.types.is_string(actual.type)
                    or pa.types.is_large_string(actual.type)
                    or pa.types.is_string_view(actual.type)
                ):
                    raise NautilusDataError("Arrow batch schema does not match")
            elif not pa.types.is_uint64(actual.type):
                raise NautilusDataError("Arrow batch schema does not match")
        decoded: list[HarmonicObservationData] = []
        for row in batch.to_pylist():
            if not isinstance(row, dict):
                raise NautilusDataError("Arrow row must be an object")
            extra_row = set(row) - _ARROW_ROW_FIELDS
            if extra_row - {"data_type"}:
                raise NautilusDataError("Arrow row has unexpected fields")
            if not _ARROW_ROW_FIELDS <= set(row):
                raise NautilusDataError("Arrow row is missing required fields")
            item = cls(
                ts_event=row["ts_event"],
                ts_init=row["ts_init"],
                payload=row["payload"],
                payload_sha256=row["payload_sha256"],
            )
            observation = item.observation
            if observation.meta.product.value != metadata["product"]:
                raise NautilusDataError("Arrow metadata product does not match payload")
            if observation.meta.instrument_id != metadata["instrument_id"]:
                raise NautilusDataError("Arrow metadata instrument does not match payload")
            if "data_type" in row:
                stored = row["data_type"]
                if type(stored) is not str:
                    raise NautilusDataError("stored data type must be a string")
                data_type = json.loads(stored)
                if not isinstance(data_type, dict):
                    raise NautilusDataError("stored data type is invalid")
                expected = observation_data_type(observation)
                if data_type.get("type_name") != TYPE_NAME:
                    raise NautilusDataError("stored type name does not match")
                if data_type.get("identifier") != expected.identifier:
                    raise NautilusDataError("stored identifier does not match")
                if data_type.get("metadata") != dict(expected.metadata):
                    raise NautilusDataError("stored metadata does not match")
            decoded.append(item)
        return decoded


def register_harmonic_observation_data() -> None:
    """Idempotently register the Harmonic observation envelope with Nautilus."""

    global _REGISTERED
    with _REGISTER_LOCK:
        if _REGISTERED:
            return
        register_custom_data_class(HarmonicObservationData)
        _REGISTERED = True


def wrap_observation(observation: CausalObservation) -> CustomData:
    register_harmonic_observation_data()
    if type(observation) not in _TAG_BY_TYPE:
        raise NautilusDataError("unsupported observation type")
    payload = encode_observation(observation).decode("ascii")
    ts_event, ts_init = observation_clocks(observation)
    inner = HarmonicObservationData(
        ts_event=ts_event,
        ts_init=ts_init,
        payload=payload,
        payload_sha256=_sha256_hex(payload.encode("ascii")),
    )
    wrapper = CustomData(observation_data_type(observation), inner)
    return unwrap_observation(wrapper)


def unwrap_observation(wrapper: CustomData) -> CustomData:
    register_harmonic_observation_data()
    if not isinstance(wrapper, CustomData):
        raise NautilusDataError("wrapper must be CustomData")
    data_type = wrapper.data_type
    if data_type.type_name != TYPE_NAME:
        raise NautilusDataError("wrapper type name does not match")
    metadata = dict(data_type.metadata)
    if set(metadata) != _METADATA_FIELDS:
        raise NautilusDataError("wrapper metadata has unexpected keys")
    if metadata["schema_version"] != SCHEMA_VERSION:
        raise NautilusDataError("wrapper schema version does not match")
    inner = wrapper.data
    if not isinstance(inner, HarmonicObservationData):
        inner = HarmonicObservationData.from_json(
            {
                "payload": getattr(inner, "payload", None),
                "payload_sha256": getattr(inner, "payload_sha256", None),
                "ts_event": wrapper.ts_event,
                "ts_init": wrapper.ts_init,
            }
        )
    if wrapper.ts_event != inner.ts_event or wrapper.ts_init != inner.ts_init:
        raise NautilusDataError("wrapper timestamps do not match the inner payload")
    observation = inner.observation
    expected = observation_data_type(observation)
    if metadata != dict(expected.metadata):
        raise NautilusDataError("wrapper metadata does not match the observation")
    if data_type.identifier != expected.identifier:
        raise NautilusDataError("wrapper identifier does not match the observation")
    if (
        observation.meta.product.value != metadata["product"]
        or observation.meta.instrument_id != metadata["instrument_id"]
    ):
        raise NautilusDataError("wrapper product or instrument does not match")
    return CustomData(expected, inner)


def prepare_observation_batch(
    observations: Sequence[CausalObservation],
) -> tuple[CustomData, ...]:
    materialized = tuple(observations)
    if not materialized:
        raise NautilusDataError("observation batch must be non-empty")
    identities: set[tuple[str, str, int, int]] = set()
    wrappers: list[CustomData] = []
    for observation in materialized:
        available = observation.meta.source_available_at_us
        if available is None:
            raise NautilusDataError("source_available_at_us must be known")
        identity = (
            observation.meta.product.value,
            observation.meta.instrument_id,
            observation.meta.event_time_us,
            available,
        )
        if identity in identities:
            raise NautilusDataError("duplicate causal identities")
        identities.add(identity)
        wrappers.append(wrap_observation(observation))
    return tuple(
        sorted(
            wrappers,
            key=lambda wrapper: (
                wrapper.ts_init,
                wrapper.ts_event,
                wrapper.data_type.metadata["product"],
                wrapper.data_type.metadata["instrument_id"],
                wrapper.data.payload_sha256,
            ),
        )
    )


def write_catalog_partitions(
    catalog: ParquetDataCatalog, wrappers: Sequence[CustomData]
) -> tuple[str, ...]:
    """Write one ascending-`ts_init` partition per identifier.

    rc3 `write_custom_data` stores a mixed-identifier batch under the first
    wrapper's identifier, so partitions are written separately.
    """

    grouped: dict[str, list[CustomData]] = {}
    for wrapper in wrappers:
        validated = unwrap_observation(wrapper)
        grouped.setdefault(validated.data_type.identifier, []).append(validated)
    paths: list[str] = []
    for identifier in sorted(grouped):
        partition = tuple(
            sorted(
                grouped[identifier],
                key=lambda wrapper: (
                    wrapper.ts_init,
                    wrapper.ts_event,
                    wrapper.data.payload_sha256,
                ),
            )
        )
        paths.append(catalog.write_custom_data(partition))
    return tuple(paths)
