"""Independent exact linear-perpetual ledger. Does not import NautilusTrader."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

_U64_MAX = (1 << 64) - 1
_ZERO = Decimal("0")


class AccountingError(ValueError):
    """A ledger configuration, event, or identity violates the fixture contract."""


class FillSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


def _decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise AccountingError(f"{field} must be a finite Decimal")
    if not value.is_finite():
        raise AccountingError(f"{field} must be a finite Decimal")
    return value


def _nonnegative_decimal(value: object, *, field: str) -> Decimal:
    result = _decimal(value, field=field)
    if result < 0:
        raise AccountingError(f"{field} must be non-negative")
    return result


def _positive_decimal(value: object, *, field: str) -> Decimal:
    result = _decimal(value, field=field)
    if result <= 0:
        raise AccountingError(f"{field} must be positive")
    return result


def _uint64(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > _U64_MAX:
        raise AccountingError(f"{field} must be a non-boolean unsigned-64-bit integer")
    return value


def _positive_uint64(value: object, *, field: str) -> int:
    result = _uint64(value, field=field)
    if result <= 0:
        raise AccountingError(f"{field} must be a strictly positive nanosecond duration")
    return result


def _bool_field(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise AccountingError(f"{field} must be a boolean")
    return value


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AccountingError(f"{field} must be a non-empty string")
    return value


def _checked_add(left: int, right: int, *, field: str) -> int:
    if left > _U64_MAX - right:
        raise AccountingError(f"{field} overflows unsigned-64-bit nanoseconds")
    return left + right


def _within_precision(value: Decimal, precision: int, *, field: str) -> Decimal:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -precision:
        raise AccountingError(f"{field} exceeds settlement-currency precision")
    return value


@dataclass(frozen=True, slots=True)
class LedgerConfig:
    starting_cash: Decimal
    multiplier: Decimal
    price_increment: Decimal
    taker_fee_rate: Decimal
    adverse_slippage_ticks: Decimal
    is_inverse: bool
    settlement_currency: str
    settlement_precision: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "starting_cash", _nonnegative_decimal(self.starting_cash, field="starting_cash")
        )
        object.__setattr__(
            self, "multiplier", _positive_decimal(self.multiplier, field="multiplier")
        )
        object.__setattr__(
            self,
            "price_increment",
            _positive_decimal(self.price_increment, field="price_increment"),
        )
        object.__setattr__(
            self,
            "taker_fee_rate",
            _nonnegative_decimal(self.taker_fee_rate, field="taker_fee_rate"),
        )
        ticks = _nonnegative_decimal(
            self.adverse_slippage_ticks, field="adverse_slippage_ticks"
        )
        if ticks != ticks.to_integral_value():
            raise AccountingError("adverse_slippage_ticks must be an integral Decimal")
        object.__setattr__(self, "adverse_slippage_ticks", ticks)
        object.__setattr__(self, "is_inverse", _bool_field(self.is_inverse, field="is_inverse"))
        if self.is_inverse:
            raise AccountingError("inverse instruments are not supported")
        object.__setattr__(
            self,
            "settlement_currency",
            _text(self.settlement_currency, field="settlement_currency"),
        )
        precision = _uint64(self.settlement_precision, field="settlement_precision")
        object.__setattr__(self, "settlement_precision", precision)
        _within_precision(self.starting_cash, precision, field="starting_cash")
        _within_precision(self.multiplier, precision, field="multiplier")
        _within_precision(self.price_increment, precision, field="price_increment")
        _within_precision(self.taker_fee_rate, precision, field="taker_fee_rate")


@dataclass(frozen=True, slots=True)
class FillRecord:
    side: FillSide
    quantity: Decimal
    actual_fill_price: Decimal
    arrival_bid: Decimal
    arrival_ask: Decimal
    commission: Decimal
    settlement_currency: str
    availability_ns: int
    decision_ns: int
    computation_latency_ns: int
    submission_ns: int
    venue_latency_ns: int
    arrival_quote_ns: int
    fill_ns: int

    def __post_init__(self) -> None:
        if not isinstance(self.side, FillSide):
            raise AccountingError("side must be a FillSide")
        object.__setattr__(self, "quantity", _positive_decimal(self.quantity, field="quantity"))
        object.__setattr__(
            self,
            "actual_fill_price",
            _positive_decimal(self.actual_fill_price, field="actual_fill_price"),
        )
        object.__setattr__(
            self, "arrival_bid", _positive_decimal(self.arrival_bid, field="arrival_bid")
        )
        object.__setattr__(
            self, "arrival_ask", _positive_decimal(self.arrival_ask, field="arrival_ask")
        )
        if self.arrival_ask <= self.arrival_bid:
            raise AccountingError("arrival quotes must be uncrossed and non-empty")
        object.__setattr__(
            self, "commission", _nonnegative_decimal(self.commission, field="commission")
        )
        object.__setattr__(
            self,
            "settlement_currency",
            _text(self.settlement_currency, field="settlement_currency"),
        )
        object.__setattr__(
            self, "availability_ns", _uint64(self.availability_ns, field="availability_ns")
        )
        object.__setattr__(self, "decision_ns", _uint64(self.decision_ns, field="decision_ns"))
        object.__setattr__(
            self,
            "computation_latency_ns",
            _positive_uint64(self.computation_latency_ns, field="computation_latency_ns"),
        )
        object.__setattr__(
            self, "submission_ns", _uint64(self.submission_ns, field="submission_ns")
        )
        object.__setattr__(
            self,
            "venue_latency_ns",
            _positive_uint64(self.venue_latency_ns, field="venue_latency_ns"),
        )
        object.__setattr__(
            self, "arrival_quote_ns", _uint64(self.arrival_quote_ns, field="arrival_quote_ns")
        )
        object.__setattr__(self, "fill_ns", _uint64(self.fill_ns, field="fill_ns"))
        if self.availability_ns > self.decision_ns:
            raise AccountingError("observation availability cannot follow the economic decision")
        earliest_submit = _checked_add(
            self.decision_ns, self.computation_latency_ns, field="strategy submission"
        )
        if self.submission_ns < earliest_submit:
            raise AccountingError("strategy submission precedes decision plus computation latency")
        earliest_fill = _checked_add(
            self.submission_ns, self.venue_latency_ns, field="fill timestamp"
        )
        if self.fill_ns < earliest_fill:
            raise AccountingError("fill precedes strategy submission plus venue latency")
        if self.arrival_quote_ns != self.fill_ns:
            raise AccountingError("arrival quote timestamp must equal fill timestamp")
        if self.side is FillSide.BUY and self.actual_fill_price < self.arrival_ask:
            raise AccountingError("buy fill is on the improving side of the arrival ask")
        if self.side is FillSide.SELL and self.actual_fill_price > self.arrival_bid:
            raise AccountingError("sell fill is on the improving side of the arrival bid")

    @property
    def timestamp_ns(self) -> int:
        return self.fill_ns

    @property
    def midpoint(self) -> Decimal:
        return (self.arrival_bid + self.arrival_ask) / Decimal(2)


@dataclass(frozen=True, slots=True)
class MarkRecord:
    timestamp_ns: int
    mark_price: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "timestamp_ns", _uint64(self.timestamp_ns, field="timestamp_ns")
        )
        object.__setattr__(
            self, "mark_price", _positive_decimal(self.mark_price, field="mark_price")
        )


@dataclass(frozen=True, slots=True)
class FundingRecord:
    publication_ns: int
    effective_ns: int
    rate: Decimal
    settlement_mark: Decimal
    settlement_currency: str
    observed_cashflow: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "publication_ns", _uint64(self.publication_ns, field="publication_ns")
        )
        object.__setattr__(
            self, "effective_ns", _uint64(self.effective_ns, field="effective_ns")
        )
        if self.publication_ns >= self.effective_ns:
            raise AccountingError("funding publication must precede the effective time")
        object.__setattr__(self, "rate", _decimal(self.rate, field="rate"))
        object.__setattr__(
            self,
            "settlement_mark",
            _positive_decimal(self.settlement_mark, field="settlement_mark"),
        )
        object.__setattr__(
            self,
            "settlement_currency",
            _text(self.settlement_currency, field="settlement_currency"),
        )
        if self.observed_cashflow is not None:
            object.__setattr__(
                self,
                "observed_cashflow",
                _decimal(self.observed_cashflow, field="observed_cashflow"),
            )

    @property
    def timestamp_ns(self) -> int:
        return self.effective_ns


LedgerEvent = FillRecord | MarkRecord | FundingRecord


@dataclass(frozen=True, slots=True)
class LedgerSnapshot:
    timestamp_ns: int
    signed_position: Decimal
    average_actual_price: Decimal | None
    average_reference_price: Decimal | None
    realized_actual_pnl: Decimal
    realized_reference_pnl: Decimal
    unrealized_actual_pnl: Decimal | None
    unrealized_reference_pnl: Decimal | None
    turnover: Decimal
    spread_cost: Decimal
    adverse_slippage_cost: Decimal
    commissions: Decimal
    funding_cashflow: Decimal
    settlement_cash: Decimal
    actual_gross_pnl: Decimal | None
    reference_gross_pnl: Decimal | None
    net_pnl: Decimal | None
    net_equity: Decimal | None


@dataclass(frozen=True, slots=True)
class LedgerReport:
    snapshots: tuple[LedgerSnapshot, ...]
    signed_position: Decimal
    realized_actual_pnl: Decimal
    realized_reference_pnl: Decimal
    turnover: Decimal
    spread_cost: Decimal
    adverse_slippage_cost: Decimal
    commissions: Decimal
    funding_cashflow: Decimal
    settlement_cash: Decimal
    net_pnl: Decimal | None
    net_equity: Decimal | None


def _expected_fill_price(fill: FillRecord, config: LedgerConfig) -> Decimal:
    slip = config.price_increment * config.adverse_slippage_ticks
    if fill.side is FillSide.BUY:
        return fill.arrival_ask + slip
    return fill.arrival_bid - slip


def _expected_commission(fill: FillRecord, config: LedgerConfig) -> Decimal:
    return fill.quantity * fill.actual_fill_price * config.multiplier * config.taker_fee_rate


def _sign(quantity: Decimal) -> Decimal:
    if quantity > 0:
        return Decimal(1)
    if quantity < 0:
        return Decimal(-1)
    return _ZERO


def _snapshot(
    *,
    timestamp_ns: int,
    signed: Decimal,
    avg_actual: Decimal | None,
    avg_ref: Decimal | None,
    realized_actual: Decimal,
    realized_ref: Decimal,
    turnover: Decimal,
    spread_cost: Decimal,
    slip_cost: Decimal,
    commissions: Decimal,
    funding_cf: Decimal,
    cash: Decimal,
    mark: Decimal | None,
    starting_cash: Decimal,
    multiplier: Decimal,
) -> LedgerSnapshot:
    valued = signed == 0 or mark is not None
    if signed == 0:
        unreal_a: Decimal | None = _ZERO
        unreal_r: Decimal | None = _ZERO
    elif mark is None or avg_actual is None or avg_ref is None:
        unreal_a = None
        unreal_r = None
        valued = False
    else:
        unreal_a = signed * (mark - avg_actual) * multiplier
        unreal_r = signed * (mark - avg_ref) * multiplier
    actual_gross = None if not valued else realized_actual + (unreal_a or _ZERO)
    ref_gross = None if not valued else realized_ref + (unreal_r or _ZERO)
    net_pnl = None
    net_equity = None
    if valued and actual_gross is not None and ref_gross is not None:
        if actual_gross + spread_cost + slip_cost != ref_gross:
            raise AccountingError("reference-mid gross P&L identity failed")
        net_pnl = actual_gross - commissions + funding_cf
        if net_pnl != ref_gross - spread_cost - slip_cost - commissions + funding_cf:
            raise AccountingError("net P&L identity failed")
        net_equity = starting_cash + net_pnl
        if net_equity != cash + (unreal_a or _ZERO):
            raise AccountingError("net equity identity failed")
    return LedgerSnapshot(
        timestamp_ns=timestamp_ns,
        signed_position=signed,
        average_actual_price=avg_actual,
        average_reference_price=avg_ref,
        realized_actual_pnl=realized_actual,
        realized_reference_pnl=realized_ref,
        unrealized_actual_pnl=unreal_a,
        unrealized_reference_pnl=unreal_r,
        turnover=turnover,
        spread_cost=spread_cost,
        adverse_slippage_cost=slip_cost,
        commissions=commissions,
        funding_cashflow=funding_cf,
        settlement_cash=cash,
        actual_gross_pnl=actual_gross,
        reference_gross_pnl=ref_gross,
        net_pnl=net_pnl,
        net_equity=net_equity,
    )


def reconcile_ledger(
    config: LedgerConfig, events: Sequence[LedgerEvent]
) -> LedgerReport:
    if not isinstance(config, LedgerConfig):
        raise AccountingError("config must be a LedgerConfig")
    materialized = tuple(events)
    previous = -1
    seen: set[int] = set()
    for event in materialized:
        if not isinstance(event, (FillRecord, MarkRecord, FundingRecord)):
            raise AccountingError("unsupported ledger event")
        timestamp = event.timestamp_ns
        if timestamp in seen:
            raise AccountingError("duplicate event identities")
        if timestamp <= previous:
            raise AccountingError("timestamps must strictly increase")
        seen.add(timestamp)
        previous = timestamp
    ordered = materialized

    signed = _ZERO
    avg_actual: Decimal | None = None
    avg_ref: Decimal | None = None
    realized_actual = _ZERO
    realized_ref = _ZERO
    turnover = _ZERO
    spread_cost = _ZERO
    slip_cost = _ZERO
    commissions = _ZERO
    funding_cf = _ZERO
    cash = config.starting_cash
    mark: Decimal | None = None
    mark_time: int | None = None
    snapshots: list[LedgerSnapshot] = []
    multiplier = config.multiplier
    precision = config.settlement_precision

    for event in ordered:
        if isinstance(event, MarkRecord):
            _within_precision(event.mark_price, precision, field="mark_price")
            mark = event.mark_price
            mark_time = event.timestamp_ns
        elif isinstance(event, FundingRecord):
            if event.settlement_currency != config.settlement_currency:
                raise AccountingError("settlement currency mismatch")
            _within_precision(event.rate, precision, field="rate")
            _within_precision(event.settlement_mark, precision, field="settlement_mark")
            if mark is None or mark_time is None:
                raise AccountingError("funding requires a preceding mark")
            if mark_time > event.effective_ns:
                raise AccountingError("latest mark time cannot follow funding effective time")
            if event.settlement_mark != mark:
                raise AccountingError(
                    "funding settlement mark must equal the latest declared mark"
                )
            computed = -signed * event.settlement_mark * multiplier * event.rate
            if signed == 0:
                computed = _ZERO
                if event.observed_cashflow is not None:
                    raise AccountingError("flat position cannot have a native funding adjustment")
            elif (
                event.observed_cashflow is not None and event.observed_cashflow != computed
            ):
                raise AccountingError("observed funding cashflow does not match the independent identity")
            _within_precision(computed, precision, field="funding_cashflow")
            funding_cf += computed
            cash += computed
        elif isinstance(event, FillRecord):
            if event.settlement_currency != config.settlement_currency:
                raise AccountingError("settlement currency mismatch")
            _within_precision(event.quantity, precision, field="quantity")
            _within_precision(event.actual_fill_price, precision, field="actual_fill_price")
            _within_precision(event.arrival_bid, precision, field="arrival_bid")
            _within_precision(event.arrival_ask, precision, field="arrival_ask")
            _within_precision(event.commission, precision, field="commission")
            expected_price = _expected_fill_price(event, config)
            if event.actual_fill_price != expected_price:
                raise AccountingError("actual fill price does not match configured adverse slippage")
            expected_fee = _expected_commission(event, config)
            if event.commission != expected_fee:
                raise AccountingError("commission does not match the independent fee identity")
            signed_fill = event.quantity if event.side is FillSide.BUY else -event.quantity
            mid = event.midpoint
            half = (event.arrival_ask - event.arrival_bid) / Decimal(2)
            abs_qty = event.quantity
            turnover += abs_qty * event.actual_fill_price * multiplier
            spread_cost += half * abs_qty * multiplier
            slip_cost += config.price_increment * config.adverse_slippage_ticks * abs_qty * multiplier
            commissions += event.commission
            cash -= event.commission
            if signed == 0:
                signed = signed_fill
                avg_actual = event.actual_fill_price
                avg_ref = mid
            elif signed * signed_fill > 0:
                new_abs = abs(signed) + abs_qty
                avg_actual = (avg_actual * abs(signed) + event.actual_fill_price * abs_qty) / new_abs
                avg_ref = (avg_ref * abs(signed) + mid * abs_qty) / new_abs
                signed += signed_fill
            else:
                close_qty = min(abs(signed), abs_qty)
                pnl_actual = _sign(signed) * (event.actual_fill_price - avg_actual) * close_qty * multiplier
                pnl_ref = _sign(signed) * (mid - avg_ref) * close_qty * multiplier
                realized_actual += pnl_actual
                realized_ref += pnl_ref
                cash += pnl_actual
                signed += signed_fill
                if signed == 0:
                    avg_actual = None
                    avg_ref = None
                elif _sign(signed) == _sign(signed_fill):
                    avg_actual = event.actual_fill_price
                    avg_ref = mid
        else:
            raise AccountingError("unsupported ledger event")
        snapshots.append(
            _snapshot(
                timestamp_ns=event.timestamp_ns,
                signed=signed,
                avg_actual=avg_actual,
                avg_ref=avg_ref,
                realized_actual=realized_actual,
                realized_ref=realized_ref,
                turnover=turnover,
                spread_cost=spread_cost,
                slip_cost=slip_cost,
                commissions=commissions,
                funding_cf=funding_cf,
                cash=cash,
                mark=mark,
                starting_cash=config.starting_cash,
                multiplier=multiplier,
            )
        )

    final = snapshots[-1] if snapshots else None
    return LedgerReport(
        snapshots=tuple(snapshots),
        signed_position=signed,
        realized_actual_pnl=realized_actual,
        realized_reference_pnl=realized_ref,
        turnover=turnover,
        spread_cost=spread_cost,
        adverse_slippage_cost=slip_cost,
        commissions=commissions,
        funding_cashflow=funding_cf,
        settlement_cash=cash,
        net_pnl=None if final is None else final.net_pnl,
        net_equity=None if final is None else final.net_equity,
    )
