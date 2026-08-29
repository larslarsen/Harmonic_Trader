from __future__ import annotations

import json
from dataclasses import fields, replace
from decimal import Decimal

import pytest
from nautilus_trader.model import CustomData, DataType
from nautilus_trader.persistence import ParquetDataCatalog

from harmonic_trader.data.contracts import (
    BasisObservation,
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
from harmonic_trader.integration.nautilus_data import (
    SCHEMA_VERSION,
    TYPE_NAME,
    HarmonicObservationData,
    NautilusDataError,
    catalog_identifier,
    decode_observation,
    encode_observation,
    observation_clocks,
    observation_sha256,
    prepare_observation_batch,
    register_harmonic_observation_data,
    unwrap_observation,
    wrap_observation,
    write_catalog_partitions,
)


_SHA = "a" * 64
_INSTRUMENT = "BTCUSDT-PERP"


def _meta(
    product: Product,
    event: int,
    *,
    available: int | None = None,
    instrument: str = _INSTRUMENT,
    retrieved: int = 1_000,
) -> ObservationMeta:
    return ObservationMeta(
        product=product,
        instrument_id=instrument,
        event_time_us=event,
        source_available_at_us=event if available is None else available,
        retrieved_at_us=retrieved,
        lineage=ReleaseLineage("dataset", _SHA, f"raw-{product.value}-{event}"),
    )


def _bar(**kwargs: object) -> MarketBarObservation:
    values = {
        "meta": _meta(Product.MARKET_BAR, 20, available=21),
        "period_start_us": 10,
        "period_end_us": 20,
        "open": Decimal("100"),
        "high": Decimal("110"),
        "low": Decimal("90"),
        "close": Decimal("105"),
        "base_volume": Decimal("2"),
        "quote_volume": Decimal("205"),
    }
    values.update(kwargs)
    return MarketBarObservation(**values)  # type: ignore[arg-type]


def _flow(**kwargs: object) -> TradeFlowObservation:
    values = {
        "meta": _meta(Product.TRADE_FLOW, 20),
        "period_start_us": 10,
        "period_end_us": 20,
        "total_quote_volume": Decimal(0),
        "taker_buy_quote_volume": Decimal(0),
    }
    values.update(kwargs)
    return TradeFlowObservation(**values)  # type: ignore[arg-type]


def _oi(**kwargs: object) -> OpenInterestObservation:
    values = {
        "meta": _meta(Product.OPEN_INTEREST, 20),
        "native_quantity": Decimal("100"),
        "base_quantity": Decimal("10"),
        "notional_usd": Decimal("1000"),
        "conversion_price": Decimal("100"),
    }
    values.update(kwargs)
    return OpenInterestObservation(**values)  # type: ignore[arg-type]


def _funding(*, realized: bool = True, **kwargs: object) -> FundingObservation:
    event = 40 if realized else 20
    values = {
        "meta": _meta(
            Product.FUNDING_REALIZED if realized else Product.FUNDING_INDICATIVE, event
        ),
        "kind": FundingKind.REALIZED if realized else FundingKind.INDICATIVE,
        "rate": Decimal("0.0002") if realized else Decimal("0.0001"),
        "effective_time_us": 40,
        "interval_us": 20,
        "positive_rate_long_pays_short": True,
    }
    values.update(kwargs)
    return FundingObservation(**values)  # type: ignore[arg-type]


def _basis(**kwargs: object) -> BasisObservation:
    values = {
        "meta": _meta(Product.MARK_INDEX_BASIS, 20),
        "mark_price": Decimal("101"),
        "index_price": Decimal("100"),
        "basis_ratio": Decimal("0.01"),
    }
    values.update(kwargs)
    return BasisObservation(**values)  # type: ignore[arg-type]


def _liquidation(**kwargs: object) -> LiquidationObservation:
    values = {
        "meta": _meta(Product.LIQUIDATION_OBSERVED, 20),
        "period_start_us": 10,
        "period_end_us": 20,
        "long_liquidation_usd": Decimal(0),
        "short_liquidation_usd": Decimal(0),
        "venue_publication_censored": True,
    }
    values.update(kwargs)
    return LiquidationObservation(**values)  # type: ignore[arg-type]


def _cost(**kwargs: object) -> CostCalibrationObservation:
    values = {
        "meta": _meta(Product.COST_CALIBRATION, 20),
        "bid_price": Decimal("100"),
        "ask_price": Decimal("101"),
        "bid_depth_usd": Decimal("50"),
        "ask_depth_usd": Decimal("60"),
        "maker_fee_rate": Decimal("0.0002"),
        "taker_fee_rate": Decimal("0.0004"),
    }
    values.update(kwargs)
    return CostCalibrationObservation(**values)  # type: ignore[arg-type]


def _all_observations() -> tuple[object, ...]:
    return (
        _bar(),
        _flow(),
        _oi(),
        _funding(realized=True),
        _funding(realized=False),
        _basis(),
        _liquidation(),
        _cost(),
    )


def test_every_observation_variant_round_trips_exact_semantic_facts() -> None:
    for observation in _all_observations():
        encoded = encode_observation(observation)
        restored = decode_observation(encoded)
        assert restored == observation
        assert encode_observation(restored) == encoded
        assert observation_sha256(restored) == observation_sha256(observation)
        payload = json.loads(encoded)
        for field in fields(observation):
            value = getattr(observation, field.name)
            if field.name == "meta" or not isinstance(value, Decimal):
                continue
            assert payload[field.name] == str(value)
            assert isinstance(payload[field.name], str)
    flow = decode_observation(encode_observation(_flow()))
    assert flow.total_quote_volume == 0
    liquidation = decode_observation(encode_observation(_liquidation()))
    assert liquidation.venue_publication_censored is True
    indicative = decode_observation(encode_observation(_funding(realized=False)))
    assert indicative.kind is FundingKind.INDICATIVE
    assert indicative.effective_time_us != indicative.meta.event_time_us
    realized = decode_observation(encode_observation(_funding(realized=True)))
    assert realized.kind is FundingKind.REALIZED
    assert realized.effective_time_us == realized.meta.event_time_us


def test_canonical_bytes_and_hash_are_stable_and_order_independent() -> None:
    observation = _bar()
    first = encode_observation(observation)
    second = encode_observation(_bar())
    assert first == second
    assert observation_sha256(observation) == observation_sha256(_bar())
    loaded = json.loads(first)
    canonical = json.dumps(loaded, sort_keys=True, separators=(",", ":")) + "\n"
    assert canonical.encode("ascii") == first
    assert decode_observation(first) == observation
    pretty = json.dumps(loaded, indent=2).encode()
    with pytest.raises(NautilusDataError, match="canonical"):
        decode_observation(pretty)
    inner = wrap_observation(observation).data
    reversed_mapping = {
        "ts_init": inner.ts_init,
        "payload_sha256": inner.payload_sha256,
        "payload": inner.payload,
        "ts_event": inner.ts_event,
    }
    assert tuple(reversed_mapping) != ("payload", "payload_sha256", "ts_event", "ts_init")
    restored = HarmonicObservationData.from_json(reversed_mapping)
    assert restored.to_json() == inner.to_json()
    pretty_envelope = json.dumps(json.loads(inner.to_json()), indent=2)
    with pytest.raises(NautilusDataError, match="canonical"):
        HarmonicObservationData.from_json(pretty_envelope)


def test_custom_data_json_bytes_round_trip_preserves_data_type() -> None:
    register_harmonic_observation_data()
    wrapper = wrap_observation(_bar())
    restored = unwrap_observation(CustomData.from_json_bytes(wrapper.to_json_bytes()))
    assert restored.data_type.type_name == TYPE_NAME
    assert dict(restored.data_type.metadata) == dict(wrapper.data_type.metadata)
    assert restored.data_type.identifier == wrapper.data_type.identifier
    assert restored.ts_event == wrapper.ts_event
    assert restored.ts_init == wrapper.ts_init
    assert restored.data.payload == wrapper.data.payload
    assert restored.data.payload_sha256 == wrapper.data.payload_sha256
    assert restored.data.observation == wrapper.data.observation


def test_catalog_round_trip_for_multiple_products_and_instruments(tmp_path) -> None:
    register_harmonic_observation_data()
    observations = (
        _bar(),
        _bar(
            meta=_meta(Product.MARKET_BAR, 30, available=31, instrument="ETHUSDT-PERP"),
            period_start_us=20,
            period_end_us=30,
        ),
        _oi(),
        _funding(realized=False),
        _cost(),
    )
    wrappers = prepare_observation_batch(observations)
    inits = [wrapper.ts_init for wrapper in wrappers]
    assert inits == sorted(inits)
    catalog = ParquetDataCatalog(str(tmp_path))
    write_catalog_partitions(catalog, wrappers)
    restored: list[CustomData] = []
    for identifier in sorted({wrapper.data_type.identifier for wrapper in wrappers}):
        restored.extend(
            catalog.query_custom_data(TYPE_NAME, identifiers=[identifier])
        )
    restored_sorted = tuple(
        sorted(
            restored,
            key=lambda wrapper: (
                wrapper.ts_init,
                wrapper.ts_event,
                wrapper.data_type.metadata["product"],
                wrapper.data_type.metadata["instrument_id"],
                wrapper.data.payload_sha256,
            ),
        )
    )
    assert [item.data.payload_sha256 for item in restored_sorted] == [
        item.data.payload_sha256 for item in wrappers
    ]
    assert [item.data.observation for item in restored_sorted] == [
        item.data.observation for item in wrappers
    ]
    assert {item.data_type.identifier for item in restored_sorted} == {
        item.data_type.identifier for item in wrappers
    }


def test_catalog_identifier_is_delimiter_safe() -> None:
    dotted = catalog_identifier(product="binance_usdm_bar_1h", instrument_id="BTCUSDT-PERP")
    weird = catalog_identifier(product="binance_usdm_bar_1h", instrument_id="BTC|PERP/USDT")
    other = catalog_identifier(product="binance_usdm_trade_flow_1h", instrument_id="BTC|PERP/USDT")
    assert dotted != weird != other
    for identifier in (dotted, weird, other):
        assert "/" not in identifier
        assert "|" not in identifier
        assert "\\" not in identifier
        assert len(identifier) == 64


def test_fail_closed_on_invalid_codec_wrapper_and_batch_inputs() -> None:
    bar = _bar()
    encoded = json.loads(encode_observation(bar))
    encoded["extra"] = "nope"
    with pytest.raises(NautilusDataError, match="unexpected"):
        decode_observation(
            (json.dumps(encoded, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
    encoded = json.loads(encode_observation(bar))
    del encoded["close"]
    with pytest.raises(NautilusDataError, match="unexpected"):
        decode_observation(
            (json.dumps(encoded, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
    encoded = json.loads(encode_observation(bar))
    encoded["observation_type"] = "UnknownObservation"
    with pytest.raises(NautilusDataError, match="unknown observation type"):
        decode_observation(
            (json.dumps(encoded, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
    encoded = json.loads(encode_observation(bar))
    encoded["high"] = "80"
    with pytest.raises(NautilusDataError, match="invalid observation"):
        decode_observation(
            (json.dumps(encoded, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
    with pytest.raises(NautilusDataError, match="invalid observation JSON"):
        decode_observation(b"{not-json")
    payload = encode_observation(bar).decode("ascii")
    with pytest.raises(NautilusDataError, match="SHA-256"):
        wrap_observation(bar).data.__class__(
            ts_event=bar.meta.event_time_us * 1000,
            ts_init=21_000,
            payload=payload,
            payload_sha256="0" * 64,
        )
    unknown = replace(
        bar,
        meta=replace(bar.meta, source_available_at_us=None, retrieved_at_us=1_000),
    )
    with pytest.raises(NautilusDataError, match="source_available_at_us must be known"):
        wrap_observation(unknown)
    huge = replace(
        _oi(),
        meta=replace(
            _oi().meta,
            event_time_us=2**64,
            source_available_at_us=2**64,
            retrieved_at_us=2**64,
        ),
    )
    with pytest.raises(NautilusDataError, match="overflow"):
        observation_clocks(huge)
    with pytest.raises(NautilusDataError, match="non-empty"):
        prepare_observation_batch(())
    with pytest.raises(NautilusDataError, match="duplicate causal identities"):
        prepare_observation_batch((bar, bar))
    wrapper = wrap_observation(bar)
    mismatched = CustomData(
        DataType(
            TYPE_NAME,
            metadata={
                "instrument_id": "ETHUSDT-PERP",
                "product": Product.TRADE_FLOW.value,
                "schema_version": SCHEMA_VERSION,
            },
            identifier=catalog_identifier(
                product=Product.TRADE_FLOW.value, instrument_id="ETHUSDT-PERP"
            ),
        ),
        wrapper.data,
    )
    with pytest.raises(NautilusDataError, match="metadata"):
        unwrap_observation(mismatched)
    identifier_only = CustomData(
        DataType(
            TYPE_NAME,
            metadata=dict(wrapper.data_type.metadata),
            identifier="0" * 64,
        ),
        wrapper.data,
    )
    with pytest.raises(NautilusDataError, match="identifier"):
        unwrap_observation(identifier_only)
    with pytest.raises(NautilusDataError, match="wrapper timestamps"):
        HarmonicObservationData(
            ts_event=wrapper.ts_event + 1,
            ts_init=wrapper.ts_init,
            payload=wrapper.data.payload,
            payload_sha256=wrapper.data.payload_sha256,
        )
    numeric = json.loads(encode_observation(bar))
    numeric["open"] = 100
    with pytest.raises(NautilusDataError, match="decimal string"):
        decode_observation(
            (json.dumps(numeric, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
    assert json.loads(encode_observation(bar))["open"] == "100"

    class MarketBarObservation:  # impostor name, wrong class
        meta = bar.meta

    with pytest.raises(NautilusDataError, match="unsupported observation type"):
        wrap_observation(MarketBarObservation())  # type: ignore[arg-type]

    batch = wrapper.data.encode_record_batch_py((wrapper.data,))
    metadata = {
        "instrument_id": bar.meta.instrument_id,
        "product": bar.meta.product.value,
        "schema_version": SCHEMA_VERSION,
        "type_name": TYPE_NAME,
    }
    decoded = HarmonicObservationData.decode_record_batch_py(metadata, batch)
    assert decoded[0] == wrapper.data
    with pytest.raises(NautilusDataError, match="string mapping"):
        HarmonicObservationData.decode_record_batch_py(
            {**metadata, "product": 1}, batch  # type: ignore[dict-item]
        )
    with pytest.raises(NautilusDataError, match="record batch"):
        HarmonicObservationData.decode_record_batch_py(
            metadata, type("Fake", (), {"to_pylist": lambda self: []})()
        )
