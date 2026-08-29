"""Causal event extraction and representation primitives."""

from harmonic_trader.discovery.geometry import (
    GeometryConfig,
    GeometryError,
    GeometryVector,
    OnlineGeometryBuilder,
    build_geometry_vectors,
)
from harmonic_trader.discovery.pivots import (
    BarObservation,
    ConfirmedPivot,
    OnlineDirectionalChange,
    PivotConfig,
    PivotError,
    PivotKind,
    extract_market_pivots,
    extract_pivots,
    observations_from_market_table,
)

__all__ = [
    "BarObservation",
    "ConfirmedPivot",
    "GeometryConfig",
    "GeometryError",
    "GeometryVector",
    "OnlineDirectionalChange",
    "OnlineGeometryBuilder",
    "PivotConfig",
    "PivotError",
    "PivotKind",
    "build_geometry_vectors",
    "extract_market_pivots",
    "extract_pivots",
    "observations_from_market_table",
]
