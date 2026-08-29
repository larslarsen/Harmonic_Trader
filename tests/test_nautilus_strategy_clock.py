from __future__ import annotations

from decimal import Decimal

import pytest
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggerConfig
from nautilus_trader.model import CustomData, TraderId
from nautilus_trader.trading import Strategy

from harmonic_trader.data.contracts import (
    MarketBarObservation,
    ObservationMeta,
    Product,
    ReleaseLineage,
)
from harmonic_trader.discovery.geometry import GeometryVector
from harmonic_trader.discovery.pivots import PivotKind
from harmonic_trader.features.microstructure import MicrostructureVector
from harmonic_trader.features.state import MultimodalVector
from harmonic_trader.integration.nautilus_data import (
    prepare_observation_batch,
    register_harmonic_observation_data,
    wrap_observation,
)
from harmonic_trader.integration.strategy_clock import (
    ClockGuardError,
    nanoseconds_from_microseconds,
    require_multimodal_decision_ready,
    require_observation_available,
    require_submission_after_latency,
    require_uint64_ns,
)


_SHA = "a" * 64
_INSTRUMENT = "BTCUSDT-PERP"


def _bar(
    event: int, *, available: int | None = None, instrument: str = _INSTRUMENT
) -> MarketBarObservation:
    close = Decimal("100")
    return MarketBarObservation(
        meta=ObservationMeta(
            product=Product.MARKET_BAR,
            instrument_id=instrument,
            event_time_us=event,
            source_available_at_us=event if available is None else available,
            retrieved_at_us=10_000,
            lineage=ReleaseLineage("dataset", _SHA, f"raw-{event}"),
        ),
        period_start_us=event - 10,
        period_end_us=event,
        open=close,
        high=close + Decimal(1),
        low=close - Decimal(1),
        close=close,
        base_volume=Decimal(1),
        quote_volume=Decimal(100),
    )


def _vector(*, decision: int = 100, availability: int = 90) -> MultimodalVector:
    geometry = GeometryVector(
        instrument_id=_INSTRUMENT,
        terminal_sequence=5,
        terminal_kind=PivotKind.LOW,
        decision_time_us=decision,
        availability_time_us=availability,
        first_pivot_time_us=10,
        terminal_pivot_time_us=90,
        pivot_sequences=(1, 2, 3, 4, 5),
        direction_normalized=True,
        swing_atr=(Decimal(1), Decimal(-1), Decimal(2), Decimal(-2)),
        log_duration_ratios=(Decimal(0), Decimal(0), Decimal(0)),
        swing_velocity=(Decimal(1), Decimal(-1), Decimal(2), Decimal(-2)),
        retracement_ratios=(Decimal(1), Decimal(2), Decimal(1)),
        terminal_displacement_atr=Decimal(0),
        path_efficiency=Decimal(6),
        terminal_leg_share=Decimal(1) / Decimal(3),
        confirmation_delays=(Decimal(1),) * 5,
    )
    microstructure = MicrostructureVector(
        instrument_id=_INSTRUMENT,
        decision_time_us=decision,
        availability_time_us=availability,
        source_lineages=(),
        feature_items=(("flow", Decimal("1")), ("oi", Decimal("2"))),
    )
    return MultimodalVector(
        instrument_id=_INSTRUMENT,
        decision_time_us=decision,
        availability_time_us=availability,
        geometry=geometry,
        microstructure=microstructure,
    )


def _engine() -> BacktestEngine:
    return BacktestEngine(
        BacktestEngineConfig(
            trader_id=TraderId("HT-002-001"),
            bypass_logging=True,
            run_analysis=False,
            logging=LoggerConfig(bypass_logging=True),
        )
    )


class _ClockProbe(Strategy):
    def __init__(self, data_type) -> None:
        super().__init__()
        self._data_type = data_type
        self.records: list[tuple[int, int, str, int, str]] = []
        self.first_evidence: tuple[int, int, str, int, str] | None = None

    def on_start(self) -> None:
        self.subscribe_data(self._data_type)

    def on_data(self, data: CustomData) -> None:
        callback = self.clock.timestamp_ns()
        require_observation_available(ts_init_ns=data.ts_init, callback_ns=callback)
        record = (
            data.ts_init,
            data.ts_event,
            data.data.payload_sha256,
            callback,
            data.data.payload,
        )
        if self.first_evidence is None:
            self.first_evidence = record
        self.records.append(record)


def test_probe_receives_custom_data_and_records_callback_clock() -> None:
    register_harmonic_observation_data()
    wrappers = prepare_observation_batch((_bar(20, available=21), _bar(40, available=41)))
    probe = _ClockProbe(wrappers[0].data_type)
    engine = _engine()
    try:
        engine.add_strategy(probe)
        engine.add_data(wrappers, sort=True)
        engine.run()
    finally:
        engine.dispose()
    assert [record[0] for record in probe.records] == [wrapper.ts_init for wrapper in wrappers]
    assert [record[3] for record in probe.records] == [wrapper.ts_init for wrapper in wrappers]


def test_reversed_unique_ts_init_is_observed_ascending() -> None:
    register_harmonic_observation_data()
    wrappers = prepare_observation_batch(
        (_bar(50, available=50), _bar(10, available=10), _bar(30, available=30))
    )
    reversed_wrappers = tuple(reversed(wrappers))
    assert [wrapper.ts_init for wrapper in reversed_wrappers] != sorted(
        wrapper.ts_init for wrapper in reversed_wrappers
    )
    probe = _ClockProbe(wrappers[0].data_type)
    engine = _engine()
    try:
        engine.add_strategy(probe)
        engine.add_data(reversed_wrappers, sort=True)
        engine.run()
    finally:
        engine.dispose()
    observed = tuple(record[0] for record in probe.records)
    assert observed == tuple(sorted(observed))
    assert observed == (10_000, 30_000, 50_000)
    assert tuple(record[3] for record in probe.records) == observed


def test_late_published_older_event_cannot_revise_earlier_evidence() -> None:
    register_harmonic_observation_data()
    first = wrap_observation(_bar(100, available=100))
    late_older = wrap_observation(_bar(50, available=200))
    probe = _ClockProbe(first.data_type)
    engine = _engine()
    try:
        engine.add_strategy(probe)
        engine.add_data((late_older, first), sort=True)
        engine.run()
    finally:
        engine.dispose()
    assert probe.first_evidence is not None
    assert probe.first_evidence[1] == 100_000
    assert probe.first_evidence[0] == 100_000
    assert probe.records[0] is probe.first_evidence
    assert probe.records[-1][1] == 50_000
    assert probe.records[-1][0] == 200_000
    assert probe.first_evidence[1] == 100_000
    assert probe.first_evidence != probe.records[-1]
    assert probe.first_evidence[4] != probe.records[-1][4]


def test_multimodal_and_submission_guards_accept_boundaries_and_reject_invalid() -> None:
    vector = _vector(decision=100, availability=90)
    availability_ns, decision_ns = require_multimodal_decision_ready(
        vector, callback_ns=100_000
    )
    assert availability_ns == 90_000
    assert decision_ns == 100_000
    require_observation_available(ts_init_ns=20_000, callback_ns=20_000)
    earliest = require_submission_after_latency(
        decision_ns=decision_ns, latency_ns=1, submission_ns=100_001
    )
    assert earliest == 100_001
    with pytest.raises(ClockGuardError, match="follow the strategy callback"):
        require_observation_available(ts_init_ns=21, callback_ns=20)
    with pytest.raises(ClockGuardError, match="follow the strategy callback"):
        require_multimodal_decision_ready(vector, callback_ns=99_999)
    with pytest.raises(ClockGuardError, match="strictly positive"):
        require_submission_after_latency(
            decision_ns=decision_ns, latency_ns=0, submission_ns=decision_ns
        )
    with pytest.raises(ClockGuardError, match="submission clock"):
        require_submission_after_latency(
            decision_ns=decision_ns, latency_ns=1, submission_ns=decision_ns
        )
    with pytest.raises(ClockGuardError, match="overflows"):
        nanoseconds_from_microseconds((1 << 64), field="decision_time_us")
    with pytest.raises(ClockGuardError, match="unsigned-64-bit"):
        require_uint64_ns(True, field="callback_ns")
    with pytest.raises(ClockGuardError, match="unsigned-64-bit"):
        require_uint64_ns(-1, field="callback_ns")
    with pytest.raises(ClockGuardError, match="MultimodalVector"):
        require_multimodal_decision_ready(object(), callback_ns=1)  # type: ignore[arg-type]
    with pytest.raises(ClockGuardError, match="overflows unsigned-64-bit"):
        require_submission_after_latency(
            decision_ns=(1 << 64) - 1, latency_ns=1, submission_ns=(1 << 64) - 1
        )
