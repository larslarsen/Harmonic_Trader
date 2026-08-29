"""Causal microstructure features for the primary multimodal experiment."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TypeVar, cast

from harmonic_trader.data.asof import CausalSnapshot
from harmonic_trader.data.contracts import (
    BasisObservation,
    FundingObservation,
    LiquidationObservation,
    MarketBarObservation,
    OpenInterestObservation,
    Product,
    TradeFlowObservation,
)


class FeatureError(ValueError):
    """A causal snapshot cannot produce the frozen semantic feature block."""


_ObservationT = TypeVar("_ObservationT")


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise FeatureError("cannot calculate a mean from no values")
    return sum(values, Decimal(0)) / Decimal(len(values))


def _standard_deviation(values: tuple[Decimal, ...]) -> Decimal:
    mean = _mean(values)
    variance = _mean(tuple((value - mean) ** 2 for value in values))
    return variance.sqrt()


def _latest_zscore(values: tuple[Decimal, ...]) -> Decimal:
    standard_deviation = _standard_deviation(values)
    if standard_deviation == 0:
        return Decimal(0)
    return (values[-1] - _mean(values)) / standard_deviation


def _sign(value: Decimal) -> Decimal:
    if value > 0:
        return Decimal(1)
    if value < 0:
        return Decimal(-1)
    return Decimal(0)


def _typed_observations(
    snapshot: CausalSnapshot,
    product: Product,
    expected_type: type[_ObservationT],
    *,
    minimum: int,
) -> tuple[_ObservationT, ...]:
    try:
        observations = snapshot.observations(product)
    except KeyError as exc:
        raise FeatureError(f"snapshot does not contain {product.value}") from exc
    if len(observations) < minimum:
        raise FeatureError(
            f"{product.value} requires at least {minimum} causally available observations"
        )
    if not all(isinstance(observation, expected_type) for observation in observations):
        raise FeatureError(f"{product.value} contains an incompatible semantic type")
    return cast(tuple[_ObservationT, ...], observations)


@dataclass(frozen=True, slots=True)
class MicrostructureVector:
    instrument_id: str
    decision_time_us: int
    availability_time_us: int
    source_lineages: tuple[tuple[str, str, str], ...]
    feature_items: tuple[tuple[str, Decimal], ...]

    def __post_init__(self) -> None:
        if self.availability_time_us > self.decision_time_us:
            raise FeatureError("feature availability cannot follow the decision")
        names = tuple(name for name, _ in self.feature_items)
        if len(names) != len(set(names)):
            raise FeatureError("microstructure feature names must be unique")
        if not self.feature_items or any(
            not value.is_finite() for _, value in self.feature_items
        ):
            raise FeatureError("microstructure features must be non-empty and finite")

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.feature_items)

    @property
    def feature_values(self) -> tuple[Decimal, ...]:
        return tuple(value for _, value in self.feature_items)


def _source_lineages(
    products: tuple[
        tuple[
            Product,
            tuple[
                MarketBarObservation
                | TradeFlowObservation
                | OpenInterestObservation
                | FundingObservation
                | BasisObservation
                | LiquidationObservation,
                ...,
            ],
        ],
        ...,
    ],
) -> tuple[tuple[str, str, str], ...]:
    result: list[tuple[str, str, str]] = []
    for product, observations in products:
        identities = {
            (
                observation.meta.lineage.dataset_id,
                observation.meta.lineage.manifest_sha256,
            )
            for observation in observations
        }
        if len(identities) != 1:
            raise FeatureError(
                f"{product.value} window crosses dataset or manifest identities"
            )
        dataset_id, manifest_sha256 = identities.pop()
        result.append((product.value, dataset_id, manifest_sha256))
    return tuple(result)


def build_microstructure_vector(snapshot: CausalSnapshot) -> MicrostructureVector:
    """Build the label-free primary microstructure block from one causal snapshot."""

    if not snapshot.eligible:
        codes = ",".join(issue.code.value for issue in snapshot.issues)
        raise FeatureError(f"snapshot is not primary-eligible: {codes}")

    bars = _typed_observations(
        snapshot, Product.MARKET_BAR, MarketBarObservation, minimum=3
    )
    flows = _typed_observations(
        snapshot, Product.TRADE_FLOW, TradeFlowObservation, minimum=3
    )
    open_interest = _typed_observations(
        snapshot, Product.OPEN_INTEREST, OpenInterestObservation, minimum=3
    )
    realized_funding = _typed_observations(
        snapshot, Product.FUNDING_REALIZED, FundingObservation, minimum=3
    )
    indicative_funding = _typed_observations(
        snapshot, Product.FUNDING_INDICATIVE, FundingObservation, minimum=3
    )
    basis = _typed_observations(
        snapshot, Product.MARK_INDEX_BASIS, BasisObservation, minimum=3
    )
    liquidations = _typed_observations(
        snapshot,
        Product.LIQUIDATION_OBSERVED,
        LiquidationObservation,
        minimum=3,
    )

    closes = tuple(bar.close for bar in bars)
    bar_returns = tuple(
        (current / previous).ln() for previous, current in zip(closes, closes[1:])
    )
    bar_volumes = tuple(bar.quote_volume for bar in bars)

    flow_totals = tuple(flow.total_quote_volume for flow in flows)
    if any(total == 0 for total in flow_totals):
        raise FeatureError("taker imbalance is undefined for a zero-volume flow bar")
    flow_imbalances = tuple(
        cast(Decimal, flow.taker_imbalance) for flow in flows
    )
    aggregate_flow_total = sum(flow_totals, Decimal(0))
    aggregate_taker_buy = sum(
        (flow.taker_buy_quote_volume for flow in flows), Decimal(0)
    )
    aggregate_taker_imbalance = (
        Decimal(2) * aggregate_taker_buy / aggregate_flow_total - Decimal(1)
    )

    oi_values = tuple(observation.notional_usd for observation in open_interest)
    if any(value <= 0 for value in oi_values):
        raise FeatureError("OI log changes require strictly positive USD notional")
    oi_returns = tuple(
        (current / previous).ln()
        for previous, current in zip(oi_values, oi_values[1:])
    )

    realized_rates = tuple(observation.rate for observation in realized_funding)
    indicative_rates = tuple(observation.rate for observation in indicative_funding)
    basis_values = tuple(observation.basis_ratio for observation in basis)

    liquidation_long = sum(
        (observation.long_liquidation_usd for observation in liquidations), Decimal(0)
    )
    liquidation_short = sum(
        (observation.short_liquidation_usd for observation in liquidations), Decimal(0)
    )
    liquidation_total = liquidation_long + liquidation_short
    liquidation_imbalance = (
        Decimal(0)
        if liquidation_total == 0
        else (liquidation_long - liquidation_short) / liquidation_total
    )
    liquidation_intensities = tuple(
        observation.long_liquidation_usd + observation.short_liquidation_usd
        for observation in liquidations
    )
    liquidation_std = _standard_deviation(liquidation_intensities)
    liquidation_change_z = (
        Decimal(0)
        if liquidation_std == 0
        else (liquidation_intensities[-1] - liquidation_intensities[-2])
        / liquidation_std
    )

    feature_items = (
        ("bar_return_latest", bar_returns[-1]),
        ("bar_realized_volatility", _standard_deviation(bar_returns)),
        ("bar_quote_volume_zscore", _latest_zscore(bar_volumes)),
        ("taker_imbalance_window", aggregate_taker_imbalance),
        (
            "taker_imbalance_change",
            flow_imbalances[-1] - flow_imbalances[-2],
        ),
        ("trade_flow_volume_zscore", _latest_zscore(flow_totals)),
        ("oi_log_change_window", (oi_values[-1] / oi_values[0]).ln()),
        ("oi_log_change_latest", oi_returns[-1]),
        ("oi_change_acceleration", oi_returns[-1] - oi_returns[-2]),
        ("oi_level_zscore", _latest_zscore(oi_values)),
        ("funding_realized_latest", realized_rates[-1]),
        ("funding_realized_mean", _mean(realized_rates)),
        ("funding_realized_zscore", _latest_zscore(realized_rates)),
        (
            "funding_realized_sign_persistence",
            _mean(tuple(_sign(rate) for rate in realized_rates)),
        ),
        ("funding_indicative_latest", indicative_rates[-1]),
        (
            "funding_indicative_change",
            indicative_rates[-1] - indicative_rates[-2],
        ),
        ("funding_indicative_zscore", _latest_zscore(indicative_rates)),
        ("basis_latest", basis_values[-1]),
        ("basis_change", basis_values[-1] - basis_values[-2]),
        ("basis_zscore", _latest_zscore(basis_values)),
        ("liquidation_imbalance_window", liquidation_imbalance),
        ("liquidation_imbalance_latest", liquidations[-1].imbalance),
        (
            "liquidation_intensity_zscore",
            _latest_zscore(liquidation_intensities),
        ),
        ("liquidation_intensity_change_z", liquidation_change_z),
        (
            "liquidation_publication_censored",
            Decimal(int(liquidations[-1].venue_publication_censored)),
        ),
    )

    product_windows = (
        (Product.MARKET_BAR, bars),
        (Product.TRADE_FLOW, flows),
        (Product.OPEN_INTEREST, open_interest),
        (Product.FUNDING_REALIZED, realized_funding),
        (Product.FUNDING_INDICATIVE, indicative_funding),
        (Product.MARK_INDEX_BASIS, basis),
        (Product.LIQUIDATION_OBSERVED, liquidations),
    )
    availability = max(
        cast(int, observation.meta.source_available_at_us)
        for _, observations in product_windows
        for observation in observations
    )
    return MicrostructureVector(
        instrument_id=snapshot.instrument_id,
        decision_time_us=snapshot.decision_time_us,
        availability_time_us=availability,
        source_lineages=_source_lineages(product_windows),
        feature_items=feature_items,
    )
