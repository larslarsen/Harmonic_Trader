"""Dependency-light causal clock guards for Nautilus strategy callbacks."""

from __future__ import annotations

from harmonic_trader.features.state import MultimodalVector

_US_TO_NS = 1_000
_U64_MAX = (1 << 64) - 1
_MAX_MICROSECONDS = _U64_MAX // _US_TO_NS


class ClockGuardError(ValueError):
    """A strategy-clock relation or conversion violates the causal contract."""


def nanoseconds_from_microseconds(value: object, *, field: str) -> int:
    """Convert a non-boolean microsecond clock into unsigned-64-bit nanoseconds."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ClockGuardError(f"{field} must be a non-negative integer microsecond timestamp")
    if value > _MAX_MICROSECONDS:
        raise ClockGuardError(f"{field} overflows the unsigned-64-bit nanosecond range")
    converted = value * _US_TO_NS
    if converted > _U64_MAX:
        raise ClockGuardError(f"{field} overflows the unsigned-64-bit nanosecond range")
    return converted


def require_uint64_ns(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > _U64_MAX:
        raise ClockGuardError(f"{field} must be a non-boolean unsigned-64-bit nanosecond value")
    return value


def require_observation_available(*, ts_init_ns: object, callback_ns: object) -> None:
    """Require observation ts_init <= strategy callback clock."""

    ts_init = require_uint64_ns(ts_init_ns, field="ts_init_ns")
    callback = require_uint64_ns(callback_ns, field="callback_ns")
    if callback < ts_init:
        raise ClockGuardError("observation ts_init cannot follow the strategy callback clock")


def require_multimodal_decision_ready(
    vector: MultimodalVector, *, callback_ns: object
) -> tuple[int, int]:
    """Require multimodal availability <= decision time <= strategy callback clock."""

    if not isinstance(vector, MultimodalVector):
        raise ClockGuardError("vector must be a MultimodalVector")
    availability_ns = nanoseconds_from_microseconds(
        vector.availability_time_us, field="availability_time_us"
    )
    decision_ns = nanoseconds_from_microseconds(
        vector.decision_time_us, field="decision_time_us"
    )
    callback = require_uint64_ns(callback_ns, field="callback_ns")
    if availability_ns > decision_ns:
        raise ClockGuardError("multimodal availability cannot follow the decision time")
    if decision_ns > callback:
        raise ClockGuardError("decision time cannot follow the strategy callback clock")
    return availability_ns, decision_ns


def require_submission_after_latency(
    *,
    decision_ns: object,
    latency_ns: object,
    submission_ns: object,
) -> int:
    """Require decision time + strictly positive declared latency <= submission clock."""

    decision = require_uint64_ns(decision_ns, field="decision_ns")
    latency = require_uint64_ns(latency_ns, field="latency_ns")
    submission = require_uint64_ns(submission_ns, field="submission_ns")
    if latency <= 0:
        raise ClockGuardError("declared latency must be a strictly positive nanosecond duration")
    if decision > _U64_MAX - latency:
        raise ClockGuardError("decision time plus latency overflows unsigned-64-bit nanoseconds")
    earliest = decision + latency
    if submission < earliest:
        raise ClockGuardError("submission clock cannot precede decision time plus declared latency")
    if submission == decision:
        raise ClockGuardError("submission clock cannot equal the economic decision time")
    return earliest
