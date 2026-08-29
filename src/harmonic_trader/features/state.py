"""Join geometry and derivatives state without relaxing their causal clocks."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from harmonic_trader.discovery.geometry import GeometryVector
from harmonic_trader.features.microstructure import FeatureError, MicrostructureVector


@dataclass(frozen=True, slots=True)
class MultimodalVector:
    instrument_id: str
    decision_time_us: int
    availability_time_us: int
    geometry: GeometryVector
    microstructure: MicrostructureVector

    @property
    def feature_items(self) -> tuple[tuple[str, Decimal], ...]:
        return tuple(
            (f"geometry.{name}", value) for name, value in self.geometry.feature_items
        ) + tuple(
            (f"microstructure.{name}", value)
            for name, value in self.microstructure.feature_items
        )

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.feature_items)

    @property
    def feature_values(self) -> tuple[Decimal, ...]:
        return tuple(value for _, value in self.feature_items)


def join_multimodal_vector(
    geometry: GeometryVector, microstructure: MicrostructureVector
) -> MultimodalVector:
    """Require exact instrument/decision alignment for a primary model row."""

    if geometry.instrument_id != microstructure.instrument_id:
        raise FeatureError("geometry and microstructure instruments do not match")
    if geometry.decision_time_us != microstructure.decision_time_us:
        raise FeatureError("geometry and microstructure decision times do not match")
    availability = max(
        geometry.availability_time_us, microstructure.availability_time_us
    )
    if availability > geometry.decision_time_us:
        raise FeatureError("multimodal features are not available by the decision")
    return MultimodalVector(
        instrument_id=geometry.instrument_id,
        decision_time_us=geometry.decision_time_us,
        availability_time_us=availability,
        geometry=geometry,
        microstructure=microstructure,
    )
