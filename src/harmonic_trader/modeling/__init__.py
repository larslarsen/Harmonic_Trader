"""Training-only representation transforms for later unsupervised models."""

from harmonic_trader.modeling.representation import (
    EventKey,
    RepresentationArtifact,
    RepresentationConfig,
    RepresentationError,
    TransformedRepresentation,
    fit_representation,
    parse_representation_artifact,
    transform_representation,
)

__all__ = [
    "EventKey",
    "RepresentationArtifact",
    "RepresentationConfig",
    "RepresentationError",
    "TransformedRepresentation",
    "fit_representation",
    "parse_representation_artifact",
    "transform_representation",
]
