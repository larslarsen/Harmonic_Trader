"""Typed semantic observations independent of the upstream storage schema."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import TypeAlias


class ContractError(ValueError):
    """A released observation cannot satisfy the consumer semantic contract."""


class Product(StrEnum):
    MARKET_BAR = "binance_usdm_bar_1h"
    TRADE_FLOW = "binance_usdm_trade_flow_1h"
    OPEN_INTEREST = "binance_usdm_open_interest_5m"
    FUNDING_REALIZED = "binance_usdm_funding_realized"
    FUNDING_INDICATIVE = "binance_usdm_funding_indicative_1h"
    MARK_INDEX_BASIS = "binance_usdm_mark_index_basis_1h"
    LIQUIDATION_OBSERVED = "binance_usdm_liquidation_observed_daily"
    COST_CALIBRATION = "binance_usdm_cost_calibration"


class FundingKind(StrEnum):
    REALIZED = "realized"
    INDICATIVE = "indicative"


def _text(value: object, *, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise ContractError(f"{field} must be non-empty")
    return result


def _time(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{field} must be a non-negative integer microsecond timestamp")
    return value


def _decimal(
    value: object, *, field: str, positive: bool = False, nonnegative: bool = False
) -> Decimal:
    if isinstance(value, bool):
        raise ContractError(f"{field} must be a finite decimal")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ContractError(f"{field} must be a finite decimal") from exc
    if not result.is_finite():
        raise ContractError(f"{field} must be a finite decimal")
    if positive and result <= 0:
        raise ContractError(f"{field} must be positive")
    if nonnegative and result < 0:
        raise ContractError(f"{field} must be non-negative")
    return result


def _sha256(value: object, *, field: str) -> str:
    result = _text(value, field=field).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise ContractError(f"{field} must be a lowercase SHA-256")
    return result


@dataclass(frozen=True, slots=True)
class ReleaseLineage:
    dataset_id: str
    manifest_sha256: str
    raw_identity: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_id", _text(self.dataset_id, field="dataset_id"))
        object.__setattr__(
            self,
            "manifest_sha256",
            _sha256(self.manifest_sha256, field="manifest_sha256"),
        )
        object.__setattr__(
            self, "raw_identity", _text(self.raw_identity, field="raw_identity")
        )


@dataclass(frozen=True, slots=True)
class ObservationMeta:
    product: Product
    instrument_id: str
    event_time_us: int
    source_available_at_us: int | None
    retrieved_at_us: int
    lineage: ReleaseLineage

    def __post_init__(self) -> None:
        if not isinstance(self.product, Product):
            raise ContractError("product must be a Product")
        object.__setattr__(
            self, "instrument_id", _text(self.instrument_id, field="instrument_id")
        )
        event = _time(self.event_time_us, field="event_time_us")
        retrieved = _time(self.retrieved_at_us, field="retrieved_at_us")
        available = self.source_available_at_us
        if available is not None:
            available = _time(available, field="source_available_at_us")
            if available < event:
                raise ContractError("source_available_at_us cannot precede event_time_us")
            if retrieved < available:
                raise ContractError("retrieved_at_us cannot precede source_available_at_us")
        if retrieved < event:
            raise ContractError("retrieved_at_us cannot precede event_time_us")
        object.__setattr__(self, "event_time_us", event)
        object.__setattr__(self, "retrieved_at_us", retrieved)
        object.__setattr__(self, "source_available_at_us", available)


def _require_product(meta: ObservationMeta, expected: Product) -> None:
    if meta.product != expected:
        raise ContractError(
            f"expected product {expected.value!r}, got {meta.product.value!r}"
        )


def _period(start: object, end: object, *, event_time_us: int) -> tuple[int, int]:
    start_value = _time(start, field="period_start_us")
    end_value = _time(end, field="period_end_us")
    if not start_value < end_value:
        raise ContractError("period_start_us must precede period_end_us")
    if end_value != event_time_us:
        raise ContractError("period_end_us must equal meta.event_time_us")
    return start_value, end_value


@dataclass(frozen=True, slots=True)
class MarketBarObservation:
    meta: ObservationMeta
    period_start_us: int
    period_end_us: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    base_volume: Decimal
    quote_volume: Decimal

    def __post_init__(self) -> None:
        _require_product(self.meta, Product.MARKET_BAR)
        start, end = _period(
            self.period_start_us,
            self.period_end_us,
            event_time_us=self.meta.event_time_us,
        )
        prices = tuple(
            _decimal(value, field=name, positive=True)
            for name, value in (
                ("open", self.open),
                ("high", self.high),
                ("low", self.low),
                ("close", self.close),
            )
        )
        open_price, high, low, close = prices
        if high < max(open_price, close) or low > min(open_price, close) or high < low:
            raise ContractError("invalid OHLC ordering")
        object.__setattr__(self, "period_start_us", start)
        object.__setattr__(self, "period_end_us", end)
        object.__setattr__(self, "open", open_price)
        object.__setattr__(self, "high", high)
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "close", close)
        object.__setattr__(
            self,
            "base_volume",
            _decimal(self.base_volume, field="base_volume", nonnegative=True),
        )
        object.__setattr__(
            self,
            "quote_volume",
            _decimal(self.quote_volume, field="quote_volume", nonnegative=True),
        )


@dataclass(frozen=True, slots=True)
class TradeFlowObservation:
    meta: ObservationMeta
    period_start_us: int
    period_end_us: int
    total_quote_volume: Decimal
    taker_buy_quote_volume: Decimal

    def __post_init__(self) -> None:
        _require_product(self.meta, Product.TRADE_FLOW)
        start, end = _period(
            self.period_start_us,
            self.period_end_us,
            event_time_us=self.meta.event_time_us,
        )
        total = _decimal(
            self.total_quote_volume, field="total_quote_volume", nonnegative=True
        )
        taker_buy = _decimal(
            self.taker_buy_quote_volume,
            field="taker_buy_quote_volume",
            nonnegative=True,
        )
        if taker_buy > total:
            raise ContractError("taker_buy_quote_volume cannot exceed total_quote_volume")
        object.__setattr__(self, "period_start_us", start)
        object.__setattr__(self, "period_end_us", end)
        object.__setattr__(self, "total_quote_volume", total)
        object.__setattr__(self, "taker_buy_quote_volume", taker_buy)

    @property
    def taker_imbalance(self) -> Decimal | None:
        if self.total_quote_volume == 0:
            return None
        return (
            Decimal(2) * self.taker_buy_quote_volume / self.total_quote_volume
            - Decimal(1)
        )


@dataclass(frozen=True, slots=True)
class OpenInterestObservation:
    meta: ObservationMeta
    native_quantity: Decimal
    base_quantity: Decimal
    notional_usd: Decimal
    conversion_price: Decimal

    def __post_init__(self) -> None:
        _require_product(self.meta, Product.OPEN_INTEREST)
        for field in ("native_quantity", "base_quantity", "notional_usd"):
            object.__setattr__(
                self,
                field,
                _decimal(getattr(self, field), field=field, nonnegative=True),
            )
        object.__setattr__(
            self,
            "conversion_price",
            _decimal(self.conversion_price, field="conversion_price", positive=True),
        )


@dataclass(frozen=True, slots=True)
class FundingObservation:
    meta: ObservationMeta
    kind: FundingKind
    rate: Decimal
    effective_time_us: int
    interval_us: int
    positive_rate_long_pays_short: bool

    def __post_init__(self) -> None:
        if not isinstance(self.kind, FundingKind):
            raise ContractError("kind must be a FundingKind")
        expected = (
            Product.FUNDING_REALIZED
            if self.kind == FundingKind.REALIZED
            else Product.FUNDING_INDICATIVE
        )
        _require_product(self.meta, expected)
        object.__setattr__(self, "rate", _decimal(self.rate, field="rate"))
        effective = _time(self.effective_time_us, field="effective_time_us")
        if self.kind == FundingKind.REALIZED and effective != self.meta.event_time_us:
            raise ContractError("realized funding event_time_us must equal effective_time_us")
        if (
            isinstance(self.interval_us, bool)
            or not isinstance(self.interval_us, int)
            or self.interval_us <= 0
        ):
            raise ContractError("interval_us must be a positive integer")
        if not isinstance(self.positive_rate_long_pays_short, bool):
            raise ContractError("positive_rate_long_pays_short must be a boolean")
        object.__setattr__(self, "effective_time_us", effective)


@dataclass(frozen=True, slots=True)
class BasisObservation:
    meta: ObservationMeta
    mark_price: Decimal
    index_price: Decimal
    basis_ratio: Decimal

    def __post_init__(self) -> None:
        _require_product(self.meta, Product.MARK_INDEX_BASIS)
        mark = _decimal(self.mark_price, field="mark_price", positive=True)
        index = _decimal(self.index_price, field="index_price", positive=True)
        basis = _decimal(self.basis_ratio, field="basis_ratio")
        if basis != mark / index - Decimal(1):
            raise ContractError("basis_ratio does not reconcile to mark_price/index_price")
        object.__setattr__(self, "mark_price", mark)
        object.__setattr__(self, "index_price", index)
        object.__setattr__(self, "basis_ratio", basis)


@dataclass(frozen=True, slots=True)
class LiquidationObservation:
    meta: ObservationMeta
    period_start_us: int
    period_end_us: int
    long_liquidation_usd: Decimal
    short_liquidation_usd: Decimal
    venue_publication_censored: bool

    def __post_init__(self) -> None:
        _require_product(self.meta, Product.LIQUIDATION_OBSERVED)
        start, end = _period(
            self.period_start_us,
            self.period_end_us,
            event_time_us=self.meta.event_time_us,
        )
        object.__setattr__(self, "period_start_us", start)
        object.__setattr__(self, "period_end_us", end)
        for field in ("long_liquidation_usd", "short_liquidation_usd"):
            object.__setattr__(
                self,
                field,
                _decimal(getattr(self, field), field=field, nonnegative=True),
            )
        if not isinstance(self.venue_publication_censored, bool):
            raise ContractError("venue_publication_censored must be a boolean")

    @property
    def imbalance(self) -> Decimal:
        total = self.long_liquidation_usd + self.short_liquidation_usd
        if total == 0:
            return Decimal(0)
        return (self.long_liquidation_usd - self.short_liquidation_usd) / total


@dataclass(frozen=True, slots=True)
class CostCalibrationObservation:
    meta: ObservationMeta
    bid_price: Decimal
    ask_price: Decimal
    bid_depth_usd: Decimal
    ask_depth_usd: Decimal
    maker_fee_rate: Decimal
    taker_fee_rate: Decimal

    def __post_init__(self) -> None:
        _require_product(self.meta, Product.COST_CALIBRATION)
        bid = _decimal(self.bid_price, field="bid_price", positive=True)
        ask = _decimal(self.ask_price, field="ask_price", positive=True)
        if ask < bid:
            raise ContractError("ask_price cannot be below bid_price")
        object.__setattr__(self, "bid_price", bid)
        object.__setattr__(self, "ask_price", ask)
        for field in ("bid_depth_usd", "ask_depth_usd"):
            object.__setattr__(
                self,
                field,
                _decimal(getattr(self, field), field=field, nonnegative=True),
            )
        for field in ("maker_fee_rate", "taker_fee_rate"):
            object.__setattr__(
                self,
                field,
                _decimal(getattr(self, field), field=field, nonnegative=True),
            )


@dataclass(frozen=True, slots=True)
class CoverageGap:
    product: Product
    instrument_id: str
    start_us: int
    end_us: int
    reason: str
    evidence_identity: str

    def __post_init__(self) -> None:
        if not isinstance(self.product, Product):
            raise ContractError("gap product must be a Product")
        object.__setattr__(
            self, "instrument_id", _text(self.instrument_id, field="instrument_id")
        )
        start = _time(self.start_us, field="start_us")
        end = _time(self.end_us, field="end_us")
        if not start < end:
            raise ContractError("gap start_us must precede end_us")
        object.__setattr__(self, "start_us", start)
        object.__setattr__(self, "end_us", end)
        object.__setattr__(self, "reason", _text(self.reason, field="reason"))
        object.__setattr__(
            self,
            "evidence_identity",
            _text(self.evidence_identity, field="evidence_identity"),
        )

    def overlaps(self, start_us: int, end_us: int) -> bool:
        return self.start_us < end_us and start_us < self.end_us


CausalObservation: TypeAlias = (
    MarketBarObservation
    | TradeFlowObservation
    | OpenInterestObservation
    | FundingObservation
    | BasisObservation
    | LiquidationObservation
    | CostCalibrationObservation
)
