"""Causal product windows and complete-case eligibility evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from harmonic_trader.data.contracts import (
    CausalObservation,
    CoverageGap,
    Product,
)


class StateError(ValueError):
    """Observation state is ambiguous, duplicated, or temporally invalid."""


class EligibilityCode(StrEnum):
    COVERAGE_GAP = "coverage_gap"
    UNKNOWN_AVAILABILITY = "unknown_availability"
    INSUFFICIENT_HISTORY = "insufficient_history"
    STALE_LATEST_OBSERVATION = "stale_latest_observation"


@dataclass(frozen=True, slots=True)
class WindowRequirement:
    product: Product
    lookback_us: int
    min_observations: int
    max_staleness_us: int

    def __post_init__(self) -> None:
        if not isinstance(self.product, Product):
            raise StateError("requirement product must be a Product")
        for field in ("lookback_us", "min_observations"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise StateError(f"{field} must be a positive integer")
        if (
            isinstance(self.max_staleness_us, bool)
            or not isinstance(self.max_staleness_us, int)
            or self.max_staleness_us < 0
        ):
            raise StateError("max_staleness_us must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class EligibilityIssue:
    product: Product
    code: EligibilityCode
    detail: str


@dataclass(frozen=True, slots=True)
class CausalSnapshot:
    instrument_id: str
    decision_time_us: int
    series: tuple[tuple[Product, tuple[CausalObservation, ...]], ...]
    issues: tuple[EligibilityIssue, ...]

    @property
    def eligible(self) -> bool:
        return not self.issues

    def observations(self, product: Product) -> tuple[CausalObservation, ...]:
        for candidate, observations in self.series:
            if candidate == product:
                return observations
        raise KeyError(product)


class AsOfStateStore:
    """Immutable in-memory view of released semantic observations."""

    def __init__(
        self,
        observations: Iterable[CausalObservation],
        gaps: Iterable[CoverageGap] = (),
    ) -> None:
        self._observations: dict[
            tuple[Product, str], tuple[CausalObservation, ...]
        ] = {}
        grouped: dict[tuple[Product, str], list[CausalObservation]] = {}
        economic_keys: set[tuple[Product, str, int]] = set()
        for observation in observations:
            meta = observation.meta
            key = (meta.product, meta.instrument_id, meta.event_time_us)
            if key in economic_keys:
                raise StateError(f"duplicate economic observation: {key!r}")
            economic_keys.add(key)
            grouped.setdefault((meta.product, meta.instrument_id), []).append(observation)
        for key, values in grouped.items():
            self._observations[key] = tuple(
                sorted(
                    values,
                    key=lambda item: (
                        item.meta.event_time_us,
                        item.meta.source_available_at_us
                        if item.meta.source_available_at_us is not None
                        else 2**63,
                    ),
                )
            )

        self._gaps: dict[tuple[Product, str], tuple[CoverageGap, ...]] = {}
        grouped_gaps: dict[tuple[Product, str], list[CoverageGap]] = {}
        for gap in gaps:
            grouped_gaps.setdefault((gap.product, gap.instrument_id), []).append(gap)
        for key, values in grouped_gaps.items():
            ordered = sorted(values, key=lambda item: (item.start_us, item.end_us))
            for previous, current in zip(ordered, ordered[1:]):
                if previous.end_us > current.start_us:
                    raise StateError(f"overlapping coverage gaps for {key!r}")
            self._gaps[key] = tuple(ordered)

    def snapshot(
        self,
        instrument_id: str,
        decision_time_us: int,
        requirements: Iterable[WindowRequirement],
    ) -> CausalSnapshot:
        instrument = str(instrument_id).strip()
        if not instrument:
            raise StateError("instrument_id must be non-empty")
        if (
            isinstance(decision_time_us, bool)
            or not isinstance(decision_time_us, int)
            or decision_time_us < 0
        ):
            raise StateError(
                "decision_time_us must be a non-negative integer timestamp"
            )
        requirement_list = tuple(requirements)
        products = [requirement.product for requirement in requirement_list]
        if len(set(products)) != len(products):
            raise StateError("snapshot requirements contain duplicate products")

        result: list[tuple[Product, tuple[CausalObservation, ...]]] = []
        issues: list[EligibilityIssue] = []
        for requirement in requirement_list:
            start = max(0, decision_time_us - requirement.lookback_us)
            key = (requirement.product, instrument)
            economic_window = tuple(
                observation
                for observation in self._observations.get(key, ())
                if start < observation.meta.event_time_us <= decision_time_us
            )
            unknown = tuple(
                observation
                for observation in economic_window
                if observation.meta.source_available_at_us is None
            )
            available = tuple(
                observation
                for observation in economic_window
                if observation.meta.source_available_at_us is not None
                and observation.meta.source_available_at_us <= decision_time_us
            )
            gaps = tuple(
                gap
                for gap in self._gaps.get(key, ())
                if gap.overlaps(start, decision_time_us + 1)
            )
            if gaps:
                detail = "; ".join(
                    f"[{gap.start_us},{gap.end_us}): {gap.reason}" for gap in gaps
                )
                issues.append(
                    EligibilityIssue(
                        requirement.product, EligibilityCode.COVERAGE_GAP, detail
                    )
                )
            if unknown:
                issues.append(
                    EligibilityIssue(
                        requirement.product,
                        EligibilityCode.UNKNOWN_AVAILABILITY,
                        f"{len(unknown)} observations have unknown source availability",
                    )
                )
            if len(available) < requirement.min_observations:
                issues.append(
                    EligibilityIssue(
                        requirement.product,
                        EligibilityCode.INSUFFICIENT_HISTORY,
                        f"required {requirement.min_observations}, found {len(available)}",
                    )
                )
            elif (
                decision_time_us - available[-1].meta.event_time_us
                > requirement.max_staleness_us
            ):
                issues.append(
                    EligibilityIssue(
                        requirement.product,
                        EligibilityCode.STALE_LATEST_OBSERVATION,
                        "latest causally available observation exceeds staleness limit",
                    )
                )
            result.append((requirement.product, available))
        return CausalSnapshot(
            instrument_id=instrument,
            decision_time_us=decision_time_us,
            series=tuple(result),
            issues=tuple(issues),
        )
