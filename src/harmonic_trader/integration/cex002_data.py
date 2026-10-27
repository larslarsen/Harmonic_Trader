"""Nautilus transport for original CEX-002 fields with explicit assumed clocks.

This transport does not establish historical source availability. It deliberately
does not coerce source units into Harmonic Trader's causal observation contracts.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from typing import Any, ClassVar, Mapping, Sequence

import pyarrow as pa
from nautilus_trader.model import (
    Bar, BarAggregation, BarSpecification, BarType, CustomData, DataType,
    InstrumentId, Price, PriceType, Quantity, Symbol, Venue,
    register_custom_data_class,
)
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggerConfig
from nautilus_trader.model import TraderId
from nautilus_trader.trading import Strategy

from harmonic_trader.data.cex002 import Cex002ReaderError, Cex002ReleaseReader, ReleasedRow
from harmonic_trader.data.cex002_history import ContractHistory, REFERENCE_POLICY, annotate_row

CLOCK_POLICY = "event_time_assumption"
TYPE_NAME = "Cex002NativeFields"
SCHEMA_VERSION = "1"
_U64 = (1 << 64) - 1
_SCHEMA = pa.schema([
    pa.field("payload", pa.string(), nullable=False),
    pa.field("payload_sha256", pa.string(), nullable=False),
    pa.field("ts_event", pa.uint64(), nullable=False),
    pa.field("ts_init", pa.uint64(), nullable=False),
])
_REGISTER_LOCK = threading.Lock()
_REGISTERED = False


def _require_policy(policy: str) -> None:
    if policy != CLOCK_POLICY:
        raise Cex002ReaderError("market playback requires clock_policy='event_time_assumption'")


def _tag(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, bytes):
        return {"$bytes": value.hex()}
    if isinstance(value, list):
        return [_tag(item) for item in value]
    if isinstance(value, dict):
        return {key: _tag(item) for key, item in value.items()}
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise Cex002ReaderError(f"unsupported original field type: {type(value).__name__}")


def _untag(value: Any) -> Any:
    if isinstance(value, list):
        return [_untag(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"$decimal"}:
            return Decimal(value["$decimal"])
        if set(value) == {"$bytes"}:
            return bytes.fromhex(value["$bytes"])
        return {key: _untag(item) for key, item in value.items()}
    return value


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _digest(payload: str) -> str:
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _payload(row: ReleasedRow, *, history_sha256: str | None = None,
             classification: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "clock_policy": CLOCK_POLICY,
        "component": row.file.component,
        "dataset_id": row.file.dataset_id,
        "fields": _tag(dict(row.fields)),
        "file_sha256": row.file.sha256,
        "manifest_sha256": row.file.manifest_sha256,
        "native_symbol": row.file.native_symbol,
        "ordinal": row.ordinal,
        "product": row.file.product,
        "relative_path": row.file.relative_path,
        "source_available_at": None,
    }
    if history_sha256 is not None:
        payload["history_sha256"] = history_sha256
        payload["reference_classification"] = classification
    return payload


@dataclass(frozen=True, slots=True)
class Cex002NativeFields:
    ts_event: int
    ts_init: int
    payload: str
    payload_sha256: str
    _schema: ClassVar[pa.Schema] = _SCHEMA

    def __post_init__(self) -> None:
        if (type(self.ts_event) is not int or type(self.ts_init) is not int
                or not 0 <= self.ts_event <= _U64 or self.ts_init != self.ts_event):
            raise Cex002ReaderError("transport clocks are invalid")
        if type(self.payload) is not str or _digest(self.payload) != self.payload_sha256:
            raise Cex002ReaderError("transport payload digest changed")
        decoded = json.loads(self.payload)
        if _json(decoded) != self.payload or decoded.get("clock_policy") != CLOCK_POLICY:
            raise Cex002ReaderError("transport payload is not canonical")
        if decoded.get("source_available_at", False) is not None:
            raise Cex002ReaderError("source availability must remain unknown")
        event_ms = Cex002ReleaseReader.event_time_ms(
            decoded["product"], decoded["component"], _untag(decoded["fields"]),
        )
        if event_ms * 1_000_000 != self.ts_event:
            raise Cex002ReaderError("transport clock differs from original event fields")

    @property
    def native_fields(self) -> dict[str, Any]:
        return _untag(json.loads(self.payload)["fields"])

    @property
    def lineage(self) -> dict[str, Any]:
        obj = json.loads(self.payload)
        result = {key: obj[key] for key in (
            "product", "component", "dataset_id", "manifest_sha256", "file_sha256",
            "relative_path", "ordinal", "native_symbol", "source_available_at", "clock_policy",
        )}
        if "history_sha256" in obj:
            result["history_sha256"] = obj["history_sha256"]
            result["reference_classification"] = obj["reference_classification"]
        return result

    @classmethod
    def type_name_static(cls) -> str:
        return TYPE_NAME

    def to_json(self) -> str:
        return _json({"payload": self.payload, "payload_sha256": self.payload_sha256,
                      "ts_event": self.ts_event, "ts_init": self.ts_init})

    @classmethod
    def from_json(cls, data: object) -> Cex002NativeFields:
        if isinstance(data, (str, bytes)):
            data = json.loads(data)
        if not isinstance(data, dict) or set(data) != {"payload", "payload_sha256", "ts_event", "ts_init"}:
            raise Cex002ReaderError("invalid CEX-002 transport envelope")
        return cls(**data)

    def encode_record_batch_py(self, items: Sequence[Cex002NativeFields]) -> pa.RecordBatch:
        if not items or any(not isinstance(item, Cex002NativeFields) for item in items):
            raise Cex002ReaderError("invalid CEX-002 Arrow transport items")
        return pa.RecordBatch.from_pylist([
            {"payload": item.payload, "payload_sha256": item.payload_sha256,
             "ts_event": item.ts_event, "ts_init": item.ts_init} for item in items
        ], schema=_SCHEMA)

    @classmethod
    def decode_record_batch_py(cls, metadata: object, batch: object) -> list[Cex002NativeFields]:
        if (not isinstance(metadata, Mapping) or set(metadata) != {"schema_version", "type_name", "product", "native_symbol"}
                or metadata["schema_version"] != SCHEMA_VERSION or metadata["type_name"] != TYPE_NAME
                or not isinstance(batch, pa.RecordBatch)
                or not set(_SCHEMA.names) <= set(batch.schema.names)
                or set(batch.schema.names) - set(_SCHEMA.names) - {"data_type"}):
            raise Cex002ReaderError("invalid CEX-002 Arrow transport schema or metadata")
        for expected in _SCHEMA:
            actual = batch.schema.field(expected.name)
            if expected.name in {"payload", "payload_sha256"}:
                valid = (pa.types.is_string(actual.type) or pa.types.is_large_string(actual.type)
                         or pa.types.is_string_view(actual.type))
            else:
                valid = pa.types.is_uint64(actual.type)
            if not valid:
                raise Cex002ReaderError("invalid CEX-002 Arrow transport field type")
        items = [cls(row["ts_event"], row["ts_init"], row["payload"], row["payload_sha256"])
                 for row in batch.to_pylist()]
        for item in items:
            lineage = item.lineage
            if lineage["product"] != metadata["product"] or (lineage["native_symbol"] or "") != metadata["native_symbol"]:
                raise Cex002ReaderError("CEX-002 Arrow metadata differs from original row")
        return items


def register_cex002_native_fields() -> None:
    global _REGISTERED
    with _REGISTER_LOCK:
        if not _REGISTERED:
            register_custom_data_class(Cex002NativeFields)
            _REGISTERED = True


def cex002_data_type(product: str, native_symbol: str | None) -> DataType:
    metadata = {"schema_version": SCHEMA_VERSION, "type_name": TYPE_NAME,
                "product": product, "native_symbol": native_symbol or ""}
    identifier = hashlib.sha256(_json(metadata).encode("ascii")).hexdigest()
    return DataType(TYPE_NAME, metadata=metadata, identifier=identifier)


def custom_event(row: ReleasedRow, *, clock_policy: str,
                 history: ContractHistory | None = None,
                 knowledge_time: datetime | str | None = None,
                 reference_policy: str | None = None,
                 publication_sha256: str | None = None) -> CustomData:
    _require_policy(clock_policy)
    register_cex002_native_fields()
    classification = None
    if history is not None:
        if (reference_policy != REFERENCE_POLICY or knowledge_time is None
                or publication_sha256 != history.publication_sha256):
            raise Cex002ReaderError("history custom event requires reviewed notices policy, knowledge time and matching publication")
        annotation = annotate_row(row, history, knowledge_time)
        classification = (annotation.classification.as_dict() if annotation.classification else
                          {"status": "no_market_interval", "reason": annotation.interval_reason})
    elif knowledge_time is not None or reference_policy is not None or publication_sha256 is not None:
        raise Cex002ReaderError("custom reference options require a pinned contract history")
    event_ms = Cex002ReleaseReader.event_time_ms(row.file.product, row.file.component, row.fields)
    event_ns = event_ms * 1_000_000
    if event_ns > _U64:
        raise Cex002ReaderError("market event time exceeds Nautilus uint64 clock")
    payload = _json(_payload(row, history_sha256=history.sha256 if history else None,
                             classification=classification))
    inner = Cex002NativeFields(event_ns, event_ns, payload, _digest(payload))
    return CustomData(cex002_data_type(row.file.product, row.file.native_symbol), inner)


def _decimal_places(value: Decimal) -> int:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise Cex002ReaderError("native bar decimal is invalid")
    parts = value.as_tuple()
    if not any(parts.digits):
        return 0
    fractional = max(0, -parts.exponent)
    if fractional == 0:
        return 0
    zeros = 0
    for digit in reversed(parts.digits):
        if digit != 0 or zeros == fractional:
            break
        zeros += 1
    return fractional - zeros


def native_bar(row: ReleasedRow, *, clock_policy: str,
               price_precision: int | None = None, size_precision: int | None = None,
               history: ContractHistory | None = None,
               knowledge_time: datetime | str | None = None,
               reference_policy: str | None = None,
               publication_sha256: str | None = None) -> Bar:
    _require_policy(clock_policy)
    if row.file.product != "binance_usdm_bar_1h" or row.file.component != "":
        raise Cex002ReaderError("only primary 1h bar rows have a native Bar projection")
    fields = row.fields
    symbol = fields.get("venue_symbol")
    if type(symbol) is not str or not symbol or "." in symbol or symbol != row.file.native_symbol:
        raise Cex002ReaderError("bar symbol differs from its declared partition")
    values = [fields.get(key) for key in ("open", "high", "low", "close")]
    volume = fields.get("volume")
    if price_precision is None:
        price_precision = max(_decimal_places(value) for value in values)
    if size_precision is None:
        size_precision = _decimal_places(volume)
    event_ms = Cex002ReleaseReader.event_time_ms(row.file.product, row.file.component, fields)
    event_ns = event_ms * 1_000_000
    if event_ns > _U64:
        raise Cex002ReaderError("bar event time exceeds Nautilus uint64 clock")
    native_identity = symbol
    if history is not None:
        if (reference_policy != REFERENCE_POLICY or knowledge_time is None
                or publication_sha256 != history.publication_sha256):
            raise Cex002ReaderError("history-aware Bar requires reviewed notices policy, knowledge time and matching publication")
        classification = annotate_row(row, history, knowledge_time).classification
        if classification is None or classification.status != "within_known_episode":
            reason = classification.status if classification else "no_market_interval"
            raise Cex002ReaderError(f"history-aware Bar refused: {reason}")
        native_identity = classification.instrument_id
    elif knowledge_time is not None or reference_policy is not None or publication_sha256 is not None:
        raise Cex002ReaderError("Bar reference options require a pinned contract history")
    bar_type = BarType(InstrumentId(Symbol(native_identity), Venue("BINANCE")),
                       BarSpecification(1, BarAggregation.HOUR, PriceType.LAST))
    try:
        prices = [Price.from_decimal_dp(value, price_precision) for value in values]
        quantity = Quantity.from_decimal_dp(volume, size_precision)
        native = Bar(bar_type, *prices, quantity, event_ns, event_ns)
    except (ValueError, OverflowError) as exc:
        raise Cex002ReaderError(f"native bar conversion failed: {exc}") from exc
    if any(price.as_decimal() != value for price, value in zip(prices, values, strict=True)) or quantity.as_decimal() != volume:
        raise Cex002ReaderError("native bar conversion lost original precision")
    return native


def native_bar_precision(rows: Sequence[ReleasedRow]) -> tuple[int, int]:
    """Common exact precision for a bounded native Bar delivery batch."""
    if not rows:
        raise Cex002ReaderError("native bar delivery has no rows")
    return (max(_decimal_places(row.fields[key]) for row in rows
                for key in ("open", "high", "low", "close")),
            max(_decimal_places(row.fields["volume"]) for row in rows))


class _ReceiptProbe(Strategy):
    def __init__(self) -> None:
        super().__init__()
        self._data_type: DataType | None = None
        self._bar_type: BarType | None = None
        self.custom_receipts: list[dict[str, Any]] = []
        self.bar_receipts: list[dict[str, Any]] = []

    def bind(self, data_type: DataType, bar_type: BarType | None) -> None:
        self._data_type = data_type
        self._bar_type = bar_type

    def on_start(self) -> None:
        if self._data_type is None:
            raise Cex002ReaderError("Nautilus receipt probe was not bound")
        self.subscribe_data(self._data_type)
        if self._bar_type is not None:
            self.subscribe_bars(self._bar_type)

    def on_data(self, data: CustomData) -> None:
        inner = data.data
        self.custom_receipts.append({
            "ts_event": data.ts_event, "callback_ns": self.clock.timestamp_ns(),
            "payload_sha256": inner.payload_sha256,
            "lineage": inner.lineage, "fields": inner.native_fields,
        })

    def on_bar(self, bar: Bar) -> None:
        self.bar_receipts.append({
            "ts_event": bar.ts_event, "callback_ns": self.clock.timestamp_ns(),
            "bar_type": str(bar.bar_type), "open": bar.open.as_decimal(),
            "high": bar.high.as_decimal(), "low": bar.low.as_decimal(),
            "close": bar.close.as_decimal(), "volume": bar.volume.as_decimal(),
        })


def deliver_to_nautilus(rows: Sequence[ReleasedRow], *, clock_policy: str,
                        history: ContractHistory | None = None,
                        knowledge_time: datetime | str | None = None,
                        reference_policy: str | None = None,
                        publication_sha256: str | None = None) -> dict[str, Any]:
    """Deliver a bounded, homogeneous market selection to real rc3 callbacks."""
    _require_policy(clock_policy)
    if not rows or len(rows) > 65_536:
        raise Cex002ReaderError("Nautilus delivery requires 1..65536 rows")
    identity = (rows[0].file.product, rows[0].file.native_symbol, rows[0].file.component)
    if any((row.file.product, row.file.native_symbol, row.file.component) != identity for row in rows):
        raise Cex002ReaderError("Nautilus delivery requires one product, symbol and component")
    if history is not None:
        if (reference_policy != REFERENCE_POLICY or knowledge_time is None
                or publication_sha256 != history.publication_sha256):
            raise Cex002ReaderError("history delivery requires reviewed notices policy, knowledge time and matching publication")
    elif knowledge_time is not None or reference_policy is not None or publication_sha256 is not None:
        raise Cex002ReaderError("reference options require a pinned contract history")
    wrappers = [custom_event(row, clock_policy=clock_policy, history=history,
                             knowledge_time=knowledge_time, reference_policy=reference_policy,
                             publication_sha256=publication_sha256) for row in rows]
    is_bar = identity[0] == "binance_usdm_bar_1h" and identity[2] == ""
    bars: list[Bar] = []
    if is_bar:
        price_precision, size_precision = native_bar_precision(rows)
        bars = [native_bar(row, clock_policy=clock_policy,
                           price_precision=price_precision, size_precision=size_precision,
                           history=history, knowledge_time=knowledge_time,
                           reference_policy=reference_policy,
                           publication_sha256=publication_sha256)
                for row in rows]
        if len({str(bar.bar_type) for bar in bars}) != 1:
            raise Cex002ReaderError("history-aware native Bar delivery requires a single episode")
    probe = _ReceiptProbe()
    probe.bind(wrappers[0].data_type, bars[0].bar_type if bars else None)
    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=TraderId("HT-CEX002-001"), bypass_logging=True, run_analysis=False,
        logging=LoggerConfig(bypass_logging=True),
    ))
    try:
        engine.add_strategy(probe)
        engine.add_data([*wrappers, *bars], sort=True)
        engine.run()
    finally:
        engine.dispose()
    if len(probe.custom_receipts) != len(wrappers) or len(probe.bar_receipts) != len(bars):
        raise Cex002ReaderError("Nautilus callback receipt count differs from loaded data")
    return {"custom_count": len(probe.custom_receipts), "bar_count": len(probe.bar_receipts),
            "custom_receipts": probe.custom_receipts, "bar_receipts": probe.bar_receipts,
            "clock_policy": CLOCK_POLICY, "source_available_at": None,
            "qualification": (REFERENCE_POLICY if history is not None and is_bar
                              else "unqualified_event_time_only" if history is None
                              else "reference_annotated_original_fields_only"),
            "history_sha256": history.sha256 if history is not None else None}
