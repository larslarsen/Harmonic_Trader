from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import pytest
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggerConfig
from nautilus_trader.execution import (
    MakerTakerFeeModel,
    OneTickSlippageFillModel,
    StaticLatencyModel,
)
from nautilus_trader.model import (
    AccountType,
    BookType,
    CryptoPerpetual,
    Currency,
    CurrencyType,
    FundingRateUpdate,
    InstrumentId,
    LiquiditySide,
    MarkPriceUpdate,
    Money,
    OmsType,
    OrderFilled,
    OrderSide,
    OrderSubmitted,
    PositionAdjustmentType,
    PositionClosed,
    PositionOpened,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    TraderId,
    Venue,
)
from nautilus_trader.trading import Strategy, StrategyConfig

from harmonic_trader.integration.accounting import (
    AccountingError,
    FillRecord,
    FillSide,
    FundingRecord,
    LedgerConfig,
    LedgerSnapshot,
    MarkRecord,
    reconcile_ledger,
)
from harmonic_trader.integration.strategy_clock import require_submission_after_latency


_COMP_LAT_NS = 1_000_000_000
_VENUE_LAT_NS = 2_000_000_000
_T0 = 1_000_000_000_000
_ENTRY_DEC_NS = _T0 + 10_000_000_000
_ENTRY_SUB_NS = _ENTRY_DEC_NS + _COMP_LAT_NS
_ENTRY_FILL_NS = _ENTRY_SUB_NS + _VENUE_LAT_NS
_MARK_NS = _ENTRY_FILL_NS + 1_000_000_000
_FUND_PUB_NS = _MARK_NS + 1_000_000_000
_FUND_EFF_NS = _FUND_PUB_NS + 5_000_000_000
_EXIT_DEC_NS = _FUND_EFF_NS + 5_000_000_000
_EXIT_SUB_NS = _EXIT_DEC_NS + _COMP_LAT_NS
_EXIT_FILL_NS = _EXIT_SUB_NS + _VENUE_LAT_NS
_FLAT_PUB_NS = _EXIT_FILL_NS + 1_000_000_000
_FLAT_EFF_NS = _FLAT_PUB_NS + 5_000_000_000
_FLAT_TICK_NS = _FLAT_EFF_NS + 1_000_000_000

_STARTING_CASH = Decimal("10000.00000000")
_MULTIPLIER = Decimal("1")
_INCREMENT = Decimal("0.5")
_TAKER_FEE = Decimal("0.0004")
_SLIP_TICKS = Decimal("1")
_QTY = Decimal("2")
_ENTRY_BID = Decimal("100.0")
_ENTRY_ASK = Decimal("100.5")
_EXIT_BID = Decimal("110.0")
_EXIT_ASK = Decimal("110.5")
_MARK_PX = Decimal("102.0")
_FUND_RATE = Decimal("0.0001")
_SETTLEMENT_PRECISION = 8


def _ledger_config() -> LedgerConfig:
    return LedgerConfig(
        starting_cash=_STARTING_CASH,
        multiplier=_MULTIPLIER,
        price_increment=_INCREMENT,
        taker_fee_rate=_TAKER_FEE,
        adverse_slippage_ticks=_SLIP_TICKS,
        is_inverse=False,
        settlement_currency="USDT",
        settlement_precision=_SETTLEMENT_PRECISION,
    )


def _usdt() -> Currency:
    currency = Currency("USDT", 8, 0, "Tether", CurrencyType.CRYPTO)
    Currency.register(currency, overwrite=True)
    return Currency.from_str("USDT")


def _price(value: Decimal) -> Price:
    return Price.from_str(str(value))


def _qty(value: Decimal) -> Quantity:
    return Quantity.from_int(int(value))


def _quote(instrument_id: InstrumentId, bid: Decimal, ask: Decimal, ts: int) -> QuoteTick:
    size = Quantity.from_int(1_000)
    return QuoteTick(
        instrument_id,
        _price(bid),
        _price(ask),
        size,
        size,
        ts,
        ts,
    )


def _commission(quantity: Decimal, fill_price: Decimal) -> Decimal:
    return quantity * fill_price * _MULTIPLIER * _TAKER_FEE


@dataclass(frozen=True, slots=True)
class _ExpectedSnapshot:
    signed_position: Decimal
    turnover: Decimal
    spread_cost: Decimal
    adverse_slippage_cost: Decimal
    commissions: Decimal
    realized_actual_pnl: Decimal
    realized_reference_pnl: Decimal
    unrealized_actual_pnl: Decimal
    unrealized_reference_pnl: Decimal
    funding_cashflow: Decimal
    settlement_cash: Decimal
    net_equity: Decimal


def _hand_round_trip(
    side_name: str,
) -> tuple[_ExpectedSnapshot, _ExpectedSnapshot, _ExpectedSnapshot]:
    long = side_name == "long"
    signed = _QTY if long else -_QTY
    slip = _INCREMENT * _SLIP_TICKS
    entry_px = (_ENTRY_ASK + slip) if long else (_ENTRY_BID - slip)
    exit_px = (_EXIT_BID - slip) if long else (_EXIT_ASK + slip)
    entry_mid = (_ENTRY_BID + _ENTRY_ASK) / Decimal(2)
    exit_mid = (_EXIT_BID + _EXIT_ASK) / Decimal(2)
    half_entry = (_ENTRY_ASK - _ENTRY_BID) / Decimal(2)
    half_exit = (_EXIT_ASK - _EXIT_BID) / Decimal(2)
    direction = Decimal(1) if long else Decimal(-1)
    entry_fee = _commission(_QTY, entry_px)
    exit_fee = _commission(_QTY, exit_px)
    entry_turn = _QTY * entry_px * _MULTIPLIER
    exit_turn = _QTY * exit_px * _MULTIPLIER
    entry_spread = half_entry * _QTY * _MULTIPLIER
    exit_spread = half_exit * _QTY * _MULTIPLIER
    entry_slip = slip * _QTY * _MULTIPLIER
    exit_slip = slip * _QTY * _MULTIPLIER
    mark_unreal_a = signed * (_MARK_PX - entry_px) * _MULTIPLIER
    mark_unreal_r = signed * (_MARK_PX - entry_mid) * _MULTIPLIER
    funding = -signed * _MARK_PX * _MULTIPLIER * _FUND_RATE
    realized_a = direction * (exit_px - entry_px) * _QTY * _MULTIPLIER
    realized_r = direction * (exit_mid - entry_mid) * _QTY * _MULTIPLIER
    mark_cash = _STARTING_CASH - entry_fee
    fund_cash = mark_cash + funding
    final_cash = _STARTING_CASH - entry_fee - exit_fee + realized_a + funding
    mark = _ExpectedSnapshot(
        signed_position=signed,
        turnover=entry_turn,
        spread_cost=entry_spread,
        adverse_slippage_cost=entry_slip,
        commissions=entry_fee,
        realized_actual_pnl=Decimal("0"),
        realized_reference_pnl=Decimal("0"),
        unrealized_actual_pnl=mark_unreal_a,
        unrealized_reference_pnl=mark_unreal_r,
        funding_cashflow=Decimal("0"),
        settlement_cash=mark_cash,
        net_equity=mark_cash + mark_unreal_a,
    )
    funded = _ExpectedSnapshot(
        signed_position=signed,
        turnover=entry_turn,
        spread_cost=entry_spread,
        adverse_slippage_cost=entry_slip,
        commissions=entry_fee,
        realized_actual_pnl=Decimal("0"),
        realized_reference_pnl=Decimal("0"),
        unrealized_actual_pnl=mark_unreal_a,
        unrealized_reference_pnl=mark_unreal_r,
        funding_cashflow=funding,
        settlement_cash=fund_cash,
        net_equity=fund_cash + mark_unreal_a,
    )
    final = _ExpectedSnapshot(
        signed_position=Decimal("0"),
        turnover=entry_turn + exit_turn,
        spread_cost=entry_spread + exit_spread,
        adverse_slippage_cost=entry_slip + exit_slip,
        commissions=entry_fee + exit_fee,
        realized_actual_pnl=realized_a,
        realized_reference_pnl=realized_r,
        unrealized_actual_pnl=Decimal("0"),
        unrealized_reference_pnl=Decimal("0"),
        funding_cashflow=funding,
        settlement_cash=final_cash,
        net_equity=final_cash,
    )
    return mark, funded, final


def _fill(
    *,
    side: FillSide,
    quantity: Decimal,
    fill_price: Decimal,
    bid: Decimal,
    ask: Decimal,
    ts: int,
    commission: Decimal | None = None,
    availability_ns: int | None = None,
    decision_ns: int | None = None,
    computation_latency_ns: int = 1,
    submission_ns: int | None = None,
    venue_latency_ns: int = 1,
) -> FillRecord:
    decision = ts - 2 if decision_ns is None else decision_ns
    return FillRecord(
        side=side,
        quantity=quantity,
        actual_fill_price=fill_price,
        arrival_bid=bid,
        arrival_ask=ask,
        commission=_commission(quantity, fill_price) if commission is None else commission,
        settlement_currency="USDT",
        availability_ns=decision if availability_ns is None else availability_ns,
        decision_ns=decision,
        computation_latency_ns=computation_latency_ns,
        submission_ns=ts - 1 if submission_ns is None else submission_ns,
        venue_latency_ns=venue_latency_ns,
        arrival_quote_ns=ts,
        fill_ns=ts,
    )


def _assert_valued(snapshot: LedgerSnapshot, config: LedgerConfig) -> None:
    assert snapshot.actual_gross_pnl is not None
    assert snapshot.reference_gross_pnl is not None
    assert snapshot.net_pnl is not None
    assert snapshot.net_equity is not None
    assert snapshot.unrealized_actual_pnl is not None
    assert snapshot.reference_gross_pnl == (
        snapshot.actual_gross_pnl + snapshot.spread_cost + snapshot.adverse_slippage_cost
    )
    assert snapshot.net_pnl == (
        snapshot.actual_gross_pnl - snapshot.commissions + snapshot.funding_cashflow
    )
    assert snapshot.net_pnl == (
        snapshot.reference_gross_pnl
        - snapshot.spread_cost
        - snapshot.adverse_slippage_cost
        - snapshot.commissions
        + snapshot.funding_cashflow
    )
    assert snapshot.net_equity == config.starting_cash + snapshot.net_pnl
    assert snapshot.net_equity == snapshot.settlement_cash + snapshot.unrealized_actual_pnl


@dataclass(frozen=True, slots=True)
class _AccountSnap:
    total: Decimal
    locked: Decimal
    free: Decimal


@dataclass(frozen=True, slots=True)
class _NativeFill:
    side: FillSide
    quantity: Decimal
    price: Decimal
    commission: Decimal
    settlement_currency: str
    liquidity: LiquiditySide
    decision_ns: int
    submission_ns: int
    fill_ns: int
    arrival_bid: Decimal
    arrival_ask: Decimal
    arrival_quote_ns: int
    availability_ns: int
    computation_latency_ns: int
    venue_latency_ns: int


@dataclass(frozen=True, slots=True)
class _RoundTripTrace:
    side: FillSide
    fills: tuple[_NativeFill, ...]
    funding_cashflows: tuple[Decimal, ...]
    open_account: _AccountSnap
    close_account: _AccountSnap
    final_account: _AccountSnap
    native_realized: Decimal
    native_equity: Decimal
    mark_price: Decimal
    mark_ns: int
    funding_pub_ns: int
    funding_eff_ns: int
    flat_funding_pub_ns: int
    flat_funding_eff_ns: int


class _RoundTripStrategy(Strategy):
    def __init__(self, config: StrategyConfig | None = None) -> None:
        super().__init__(config)
        self._instrument_id: InstrumentId
        self._venue: Venue
        self._currency: Currency
        self._quantity: Quantity
        self._entry_side: OrderSide
        self._exit_side: OrderSide
        self.quotes: dict[int, QuoteTick] = {}
        self.submitted: list[OrderSubmitted] = []
        self.filled: list[OrderFilled] = []
        self.entry_decision_ns: int | None = None
        self.exit_decision_ns: int | None = None
        self.open_account: _AccountSnap | None = None
        self.close_account: _AccountSnap | None = None

    def bind(
        self,
        *,
        instrument_id: InstrumentId,
        venue: Venue,
        currency: Currency,
        quantity: Quantity,
        entry_side: OrderSide,
    ) -> None:
        self._instrument_id = instrument_id
        self._venue = venue
        self._currency = currency
        self._quantity = quantity
        self._entry_side = entry_side
        self._exit_side = OrderSide.SELL if entry_side == OrderSide.BUY else OrderSide.BUY

    def on_start(self) -> None:
        self.subscribe_quotes(self._instrument_id)
        self.subscribe_mark_prices(self._instrument_id)
        self.subscribe_funding_rates(self._instrument_id)

    def _account_snap(self) -> _AccountSnap:
        account = self.cache.account_for_venue(self._venue)
        assert account is not None
        balance = account.balance(self._currency)
        if balance is None:
            balances = list(account.balances().values())
            assert len(balances) == 1
            balance = balances[0]
        return _AccountSnap(
            total=balance.total.as_decimal(),
            locked=balance.locked.as_decimal(),
            free=balance.free.as_decimal(),
        )

    def on_quote(self, quote: QuoteTick) -> None:
        self.quotes[quote.ts_event] = quote
        clock_ns = self.clock.timestamp_ns()
        if quote.ts_event == _ENTRY_DEC_NS:
            self.entry_decision_ns = clock_ns
            return
        if quote.ts_event == _ENTRY_SUB_NS:
            require_submission_after_latency(
                decision_ns=self.entry_decision_ns,
                latency_ns=_COMP_LAT_NS,
                submission_ns=clock_ns,
            )
            self.submit_order(
                self.order_factory.market(
                    self._instrument_id,
                    self._entry_side,
                    self._quantity,
                )
            )
            return
        if quote.ts_event == _EXIT_DEC_NS:
            self.exit_decision_ns = clock_ns
            return
        if quote.ts_event == _EXIT_SUB_NS:
            require_submission_after_latency(
                decision_ns=self.exit_decision_ns,
                latency_ns=_COMP_LAT_NS,
                submission_ns=clock_ns,
            )
            self.submit_order(
                self.order_factory.market(
                    self._instrument_id,
                    self._exit_side,
                    self._quantity,
                    reduce_only=True,
                )
            )

    def on_order_submitted(self, event: OrderSubmitted) -> None:
        self.submitted.append(event)

    def on_order_filled(self, event: OrderFilled) -> None:
        self.filled.append(event)

    def on_position_opened(self, event: PositionOpened) -> None:
        self.open_account = self._account_snap()

    def on_position_closed(self, event: PositionClosed) -> None:
        self.close_account = self._account_snap()


def _instrument(instrument_id: InstrumentId, currency: Currency) -> CryptoPerpetual:
    return CryptoPerpetual(
        instrument_id,
        Symbol("BTCUSDT-PERP"),
        Currency.from_str("BTC"),
        currency,
        currency,
        False,
        1,
        0,
        Price.from_str("0.5"),
        Quantity.from_int(1),
        0,
        0,
        multiplier=Quantity.from_int(1),
        margin_init=Decimal("0.05"),
        margin_maint=Decimal("0.025"),
        maker_fee=Decimal("0"),
        taker_fee=_TAKER_FEE,
    )


def _market_data(instrument_id: InstrumentId) -> list[object]:
    return [
        _quote(instrument_id, _ENTRY_BID, _ENTRY_ASK, _T0),
        _quote(instrument_id, _ENTRY_BID, _ENTRY_ASK, _ENTRY_DEC_NS),
        _quote(instrument_id, _ENTRY_BID, _ENTRY_ASK, _ENTRY_SUB_NS),
        _quote(instrument_id, _ENTRY_BID, _ENTRY_ASK, _ENTRY_FILL_NS),
        MarkPriceUpdate(instrument_id, _price(_MARK_PX), _MARK_NS, _MARK_NS),
        FundingRateUpdate(
            instrument_id,
            _FUND_RATE,
            _FUND_PUB_NS,
            _FUND_PUB_NS,
            next_funding_ns=_FUND_EFF_NS,
        ),
        _quote(instrument_id, _ENTRY_BID, _ENTRY_ASK, _FUND_EFF_NS),
        _quote(instrument_id, _EXIT_BID, _EXIT_ASK, _EXIT_DEC_NS),
        _quote(instrument_id, _EXIT_BID, _EXIT_ASK, _EXIT_SUB_NS),
        _quote(instrument_id, _EXIT_BID, _EXIT_ASK, _EXIT_FILL_NS),
        FundingRateUpdate(
            instrument_id,
            _FUND_RATE,
            _FLAT_PUB_NS,
            _FLAT_PUB_NS,
            next_funding_ns=_FLAT_EFF_NS,
        ),
        _quote(instrument_id, _EXIT_BID, _EXIT_ASK, _FLAT_TICK_NS),
    ]


def _equity_decimal(mapping: dict, currency: Currency) -> Decimal:
    if currency in mapping:
        return mapping[currency].as_decimal()
    if currency.code in mapping:
        return mapping[currency.code].as_decimal()
    values = list(mapping.values())
    assert len(values) == 1
    return values[0].as_decimal()


def _native_fill(
    *,
    strategy: _RoundTripStrategy,
    index: int,
    decision_ns: int,
) -> _NativeFill:
    filled = strategy.filled[index]
    submitted = strategy.submitted[index]
    quote = strategy.quotes[filled.ts_event]
    side = FillSide.BUY if filled.order_side == OrderSide.BUY else FillSide.SELL
    assert filled.commission is not None
    native_commission = filled.commission.as_decimal()
    assert filled.commission.currency.code == "USDT"
    assert native_commission > 0
    return _NativeFill(
        side=side,
        quantity=filled.last_qty.as_decimal(),
        price=filled.last_px.as_decimal(),
        commission=native_commission,
        settlement_currency=filled.commission.currency.code,
        liquidity=filled.liquidity_side,
        decision_ns=decision_ns,
        submission_ns=submitted.ts_event,
        fill_ns=filled.ts_event,
        arrival_bid=quote.bid_price.as_decimal(),
        arrival_ask=quote.ask_price.as_decimal(),
        arrival_quote_ns=quote.ts_event,
        availability_ns=decision_ns,
        computation_latency_ns=_COMP_LAT_NS,
        venue_latency_ns=_VENUE_LAT_NS,
    )


@lru_cache(maxsize=2)
def _run_round_trip(side_name: str) -> _RoundTripTrace:
    entry_side = OrderSide.BUY if side_name == "long" else OrderSide.SELL
    fill_side = FillSide.BUY if side_name == "long" else FillSide.SELL
    currency = _usdt()
    venue = Venue("SIM")
    instrument_id = InstrumentId.from_str("BTCUSDT-PERP.SIM")
    instrument = _instrument(instrument_id, currency)
    strategy = _RoundTripStrategy(
        StrategyConfig(
            order_id_tag="001" if side_name == "long" else "002",
            use_uuid_client_order_ids=False,
        )
    )
    strategy.bind(
        instrument_id=instrument_id,
        venue=venue,
        currency=currency,
        quantity=_qty(_QTY),
        entry_side=entry_side,
    )
    engine = BacktestEngine(
        BacktestEngineConfig(
            trader_id=TraderId("HT-003-001" if side_name == "long" else "HT-003-002"),
            bypass_logging=True,
            run_analysis=False,
            logging=LoggerConfig(bypass_logging=True),
        )
    )
    try:
        engine.add_venue(
            venue,
            OmsType.NETTING,
            AccountType.MARGIN,
            [Money.from_decimal(_STARTING_CASH, currency)],
            base_currency=currency,
            default_leverage=Decimal("10"),
            fill_model=OneTickSlippageFillModel(1.0, 0.0, 1),
            fee_model=MakerTakerFeeModel(),
            latency_model=StaticLatencyModel(insert_latency_nanos=_VENUE_LAT_NS),
            book_type=BookType.L1_MBP,
            use_random_ids=False,
            liquidation_enabled=False,
        )
        engine.add_instrument(instrument)
        engine.add_strategy(strategy)
        engine.add_data(_market_data(instrument_id), sort=True)
        engine.run()
        assert strategy.entry_decision_ns is not None
        assert strategy.exit_decision_ns is not None
        assert len(strategy.submitted) == 2
        assert len(strategy.filled) == 2
        assert strategy.open_account is not None
        assert strategy.close_account is not None
        positions = list(engine.cache.positions_closed()) or list(engine.cache.positions())
        assert len(positions) == 1
        position = positions[0]
        assert position.is_closed
        assert position.realized_pnl is not None
        funding_adj = [
            adj
            for adj in position.adjustments()
            if adj.adjustment_type == PositionAdjustmentType.FUNDING
            and adj.pnl_change is not None
        ]
        for adj in funding_adj:
            assert adj.pnl_change is not None
            assert adj.pnl_change.currency.code == "USDT"
        funding = tuple(adj.pnl_change.as_decimal() for adj in funding_adj)
        account = engine.cache.account_for_venue(venue)
        assert account is not None
        final_balance = account.balance(currency)
        if final_balance is None:
            balances = list(account.balances().values())
            assert len(balances) == 1
            final_balance = balances[0]
        final_account = _AccountSnap(
            total=final_balance.total.as_decimal(),
            locked=final_balance.locked.as_decimal(),
            free=final_balance.free.as_decimal(),
        )
        return _RoundTripTrace(
            side=fill_side,
            fills=(
                _native_fill(
                    strategy=strategy,
                    index=0,
                    decision_ns=strategy.entry_decision_ns,
                ),
                _native_fill(
                    strategy=strategy,
                    index=1,
                    decision_ns=strategy.exit_decision_ns,
                ),
            ),
            funding_cashflows=funding,
            open_account=strategy.open_account,
            close_account=strategy.close_account,
            final_account=final_account,
            native_realized=position.realized_pnl.as_decimal(),
            native_equity=_equity_decimal(engine.portfolio.equity(venue), currency),
            mark_price=_MARK_PX,
            mark_ns=_MARK_NS,
            funding_pub_ns=_FUND_PUB_NS,
            funding_eff_ns=_FUND_EFF_NS,
            flat_funding_pub_ns=_FLAT_PUB_NS,
            flat_funding_eff_ns=_FLAT_EFF_NS,
        )
    finally:
        engine.dispose()


def _oracle_events(trace: _RoundTripTrace) -> tuple[object, ...]:
    fills = tuple(
        FillRecord(
            side=item.side,
            quantity=item.quantity,
            actual_fill_price=item.price,
            arrival_bid=item.arrival_bid,
            arrival_ask=item.arrival_ask,
            commission=item.commission,
            settlement_currency=item.settlement_currency,
            availability_ns=item.availability_ns,
            decision_ns=item.decision_ns,
            computation_latency_ns=item.computation_latency_ns,
            submission_ns=item.submission_ns,
            venue_latency_ns=item.venue_latency_ns,
            arrival_quote_ns=item.arrival_quote_ns,
            fill_ns=item.fill_ns,
        )
        for item in trace.fills
    )
    observed = trace.funding_cashflows[0] if trace.funding_cashflows else None
    return (
        fills[0],
        MarkRecord(timestamp_ns=trace.mark_ns, mark_price=trace.mark_price),
        FundingRecord(
            publication_ns=trace.funding_pub_ns,
            effective_ns=trace.funding_eff_ns,
            rate=_FUND_RATE,
            settlement_mark=trace.mark_price,
            settlement_currency="USDT",
            observed_cashflow=observed,
        ),
        fills[1],
        FundingRecord(
            publication_ns=trace.flat_funding_pub_ns,
            effective_ns=trace.flat_funding_eff_ns,
            rate=_FUND_RATE,
            settlement_mark=trace.mark_price,
            settlement_currency="USDT",
            observed_cashflow=None,
        ),
    )


def test_engine_long_and_short_clocks_obey_latencies() -> None:
    for side_name in ("long", "short"):
        trace = _run_round_trip(side_name)
        assert len(trace.fills) == 2
        for item in trace.fills:
            assert item.availability_ns <= item.decision_ns
            assert item.decision_ns + item.computation_latency_ns <= item.submission_ns
            assert item.submission_ns + item.venue_latency_ns <= item.fill_ns
            assert item.arrival_quote_ns == item.fill_ns
            assert item.decision_ns != item.submission_ns
            assert item.submission_ns != item.fill_ns
            assert item.computation_latency_ns == _COMP_LAT_NS
            assert item.venue_latency_ns == _VENUE_LAT_NS
        entry, exit_fill = trace.fills
        assert entry.decision_ns == _ENTRY_DEC_NS
        assert entry.submission_ns == _ENTRY_SUB_NS
        assert entry.fill_ns == _ENTRY_FILL_NS
        assert exit_fill.decision_ns == _EXIT_DEC_NS
        assert exit_fill.submission_ns == _EXIT_SUB_NS
        assert exit_fill.fill_ns == _EXIT_FILL_NS


def test_engine_fills_are_one_tick_adverse_and_taker() -> None:
    for side_name in ("long", "short"):
        trace = _run_round_trip(side_name)
        for item in trace.fills:
            slip = _INCREMENT * _SLIP_TICKS
            if item.side is FillSide.BUY:
                assert item.price == item.arrival_ask + slip
            else:
                assert item.price == item.arrival_bid - slip
            assert item.liquidity == LiquiditySide.TAKER
            assert item.quantity == _QTY


def test_engine_commissions_match_independent_notional_fee() -> None:
    for side_name in ("long", "short"):
        trace = _run_round_trip(side_name)
        for item in trace.fills:
            expected = _commission(item.quantity, item.price)
            assert item.commission == expected
            assert item.commission > 0
            assert item.settlement_currency == "USDT"


def test_engine_positive_funding_debits_long_and_credits_short() -> None:
    long_trace = _run_round_trip("long")
    short_trace = _run_round_trip("short")
    assert len(long_trace.funding_cashflows) == 1
    assert len(short_trace.funding_cashflows) == 1
    expected_long = -_QTY * _MARK_PX * _MULTIPLIER * _FUND_RATE
    expected_short = _QTY * _MARK_PX * _MULTIPLIER * _FUND_RATE
    assert long_trace.funding_cashflows[0] == expected_long
    assert short_trace.funding_cashflows[0] == expected_short
    assert expected_long < 0
    assert expected_short > 0


def test_engine_flat_funding_creates_no_adjustment_or_cash_change() -> None:
    for side_name in ("long", "short"):
        trace = _run_round_trip(side_name)
        assert len(trace.funding_cashflows) == 1
        assert trace.final_account.total == trace.close_account.total


def _assert_matches_hand(snapshot: LedgerSnapshot, expected: _ExpectedSnapshot) -> None:
    assert snapshot.signed_position == expected.signed_position
    assert snapshot.turnover == expected.turnover
    assert snapshot.spread_cost == expected.spread_cost
    assert snapshot.adverse_slippage_cost == expected.adverse_slippage_cost
    assert snapshot.commissions == expected.commissions
    assert snapshot.realized_actual_pnl == expected.realized_actual_pnl
    assert snapshot.realized_reference_pnl == expected.realized_reference_pnl
    assert snapshot.unrealized_actual_pnl == expected.unrealized_actual_pnl
    assert snapshot.unrealized_reference_pnl == expected.unrealized_reference_pnl
    assert snapshot.funding_cashflow == expected.funding_cashflow
    assert snapshot.settlement_cash == expected.settlement_cash
    assert snapshot.net_equity == expected.net_equity


def test_engine_identities_hold_at_valued_snapshots() -> None:
    config = _ledger_config()
    for side_name in ("long", "short"):
        report = reconcile_ledger(config, _oracle_events(_run_round_trip(side_name)))
        mark_expected, fund_expected, final_expected = _hand_round_trip(side_name)
        valued = 0
        for snapshot in report.snapshots:
            if snapshot.net_equity is None:
                assert snapshot.signed_position != 0
                assert snapshot.unrealized_actual_pnl is None
                continue
            _assert_valued(snapshot, config)
            valued += 1
        assert valued >= 3
        assert report.signed_position == 0
        assert report.net_equity is not None
        _assert_matches_hand(report.snapshots[1], mark_expected)
        _assert_matches_hand(report.snapshots[2], fund_expected)
        _assert_matches_hand(report.snapshots[-1], final_expected)
        _assert_valued(report.snapshots[-1], config)


def test_engine_final_oracle_matches_native_closed_results() -> None:
    config = _ledger_config()
    for side_name in ("long", "short"):
        trace = _run_round_trip(side_name)
        report = reconcile_ledger(config, _oracle_events(trace))
        assert report.net_pnl is not None
        assert report.net_equity is not None
        assert report.signed_position == 0
        assert report.net_pnl == trace.native_realized
        assert report.net_pnl == trace.final_account.total - _STARTING_CASH
        assert report.net_pnl == trace.native_equity - _STARTING_CASH
        assert report.net_equity == trace.final_account.total
        assert report.net_equity == trace.native_equity


def test_engine_account_total_equals_locked_plus_free() -> None:
    for side_name in ("long", "short"):
        trace = _run_round_trip(side_name)
        open_acc = trace.open_account
        close_acc = trace.close_account
        final_acc = trace.final_account
        assert open_acc.total == open_acc.locked + open_acc.free
        assert close_acc.total == close_acc.locked + close_acc.free
        assert close_acc.locked == 0
        assert close_acc.total == close_acc.free
        assert final_acc.total == final_acc.locked + final_acc.free
        assert final_acc.locked == 0
        assert final_acc.total == final_acc.free
        assert final_acc.total == close_acc.total


def test_ledger_addition_reduction_close_reversal_and_mtm() -> None:
    config = _ledger_config()
    long_events = (
        _fill(
            side=FillSide.BUY,
            quantity=Decimal("2"),
            fill_price=Decimal("101.0"),
            bid=Decimal("100.0"),
            ask=Decimal("100.5"),
            ts=10,
        ),
        _fill(
            side=FillSide.BUY,
            quantity=Decimal("2"),
            fill_price=Decimal("102.0"),
            bid=Decimal("101.0"),
            ask=Decimal("101.5"),
            ts=20,
        ),
        MarkRecord(timestamp_ns=25, mark_price=Decimal("103.0")),
        _fill(
            side=FillSide.SELL,
            quantity=Decimal("2"),
            fill_price=Decimal("109.5"),
            bid=Decimal("110.0"),
            ask=Decimal("110.5"),
            ts=30,
        ),
        _fill(
            side=FillSide.SELL,
            quantity=Decimal("4"),
            fill_price=Decimal("119.5"),
            bid=Decimal("120.0"),
            ask=Decimal("120.5"),
            ts=40,
        ),
        MarkRecord(timestamp_ns=45, mark_price=Decimal("118.0")),
        _fill(
            side=FillSide.BUY,
            quantity=Decimal("2"),
            fill_price=Decimal("111.0"),
            bid=Decimal("110.0"),
            ask=Decimal("110.5"),
            ts=50,
        ),
    )
    long_report = reconcile_ledger(config, long_events)
    assert long_report.snapshots[0].signed_position == Decimal("2")
    assert long_report.snapshots[0].average_actual_price == Decimal("101.0")
    assert long_report.snapshots[1].signed_position == Decimal("4")
    assert long_report.snapshots[1].average_actual_price == Decimal("101.5")
    assert long_report.snapshots[1].net_equity is None
    _assert_valued(long_report.snapshots[2], config)
    assert long_report.snapshots[3].signed_position == Decimal("2")
    assert long_report.snapshots[3].average_actual_price == Decimal("101.5")
    assert long_report.snapshots[4].signed_position == Decimal("-2")
    assert long_report.snapshots[4].average_actual_price == Decimal("119.5")
    _assert_valued(long_report.snapshots[5], config)
    assert long_report.snapshots[6].signed_position == 0
    assert long_report.snapshots[6].average_actual_price is None
    _assert_valued(long_report.snapshots[6], config)

    short_events = (
        _fill(
            side=FillSide.SELL,
            quantity=Decimal("2"),
            fill_price=Decimal("99.5"),
            bid=Decimal("100.0"),
            ask=Decimal("100.5"),
            ts=10,
        ),
        _fill(
            side=FillSide.SELL,
            quantity=Decimal("2"),
            fill_price=Decimal("98.5"),
            bid=Decimal("99.0"),
            ask=Decimal("99.5"),
            ts=20,
        ),
        MarkRecord(timestamp_ns=25, mark_price=Decimal("97.0")),
        _fill(
            side=FillSide.BUY,
            quantity=Decimal("2"),
            fill_price=Decimal("91.0"),
            bid=Decimal("90.0"),
            ask=Decimal("90.5"),
            ts=30,
        ),
        _fill(
            side=FillSide.BUY,
            quantity=Decimal("4"),
            fill_price=Decimal("81.0"),
            bid=Decimal("80.0"),
            ask=Decimal("80.5"),
            ts=40,
        ),
        MarkRecord(timestamp_ns=45, mark_price=Decimal("82.0")),
        _fill(
            side=FillSide.SELL,
            quantity=Decimal("2"),
            fill_price=Decimal("89.5"),
            bid=Decimal("90.0"),
            ask=Decimal("90.5"),
            ts=50,
        ),
    )
    short_report = reconcile_ledger(config, short_events)
    assert short_report.snapshots[0].signed_position == Decimal("-2")
    assert short_report.snapshots[1].signed_position == Decimal("-4")
    assert short_report.snapshots[1].average_actual_price == Decimal("99.0")
    _assert_valued(short_report.snapshots[2], config)
    assert short_report.snapshots[3].signed_position == Decimal("-2")
    assert short_report.snapshots[4].signed_position == Decimal("2")
    assert short_report.snapshots[4].average_actual_price == Decimal("81.0")
    _assert_valued(short_report.snapshots[5], config)
    assert short_report.snapshots[6].signed_position == 0
    _assert_valued(short_report.snapshots[6], config)


def test_open_position_without_mark_is_unvalued() -> None:
    config = _ledger_config()
    report = reconcile_ledger(
        config,
        (
            _fill(
                side=FillSide.BUY,
                quantity=Decimal("2"),
                fill_price=Decimal("101.0"),
                bid=Decimal("100.0"),
                ask=Decimal("100.5"),
                ts=10,
            ),
        ),
    )
    snapshot = report.snapshots[0]
    assert snapshot.signed_position == Decimal("2")
    assert snapshot.unrealized_actual_pnl is None
    assert snapshot.unrealized_reference_pnl is None
    assert snapshot.actual_gross_pnl is None
    assert snapshot.reference_gross_pnl is None
    assert snapshot.net_pnl is None
    assert snapshot.net_equity is None
    assert report.net_equity is None


def test_invalid_inputs_fail_closed() -> None:
    config = _ledger_config()
    valid = _fill(
        side=FillSide.BUY,
        quantity=Decimal("2"),
        fill_price=Decimal("101.0"),
        bid=Decimal("100.0"),
        ask=Decimal("100.5"),
        ts=10,
    )
    with pytest.raises(AccountingError, match="finite Decimal"):
        LedgerConfig(
            starting_cash=1.0,  # type: ignore[arg-type]
            multiplier=_MULTIPLIER,
            price_increment=_INCREMENT,
            taker_fee_rate=_TAKER_FEE,
            adverse_slippage_ticks=_SLIP_TICKS,
            is_inverse=False,
            settlement_currency="USDT",
            settlement_precision=_SETTLEMENT_PRECISION,
        )
    with pytest.raises(AccountingError, match="finite Decimal"):
        LedgerConfig(
            starting_cash=1,  # type: ignore[arg-type]
            multiplier=_MULTIPLIER,
            price_increment=_INCREMENT,
            taker_fee_rate=_TAKER_FEE,
            adverse_slippage_ticks=_SLIP_TICKS,
            is_inverse=False,
            settlement_currency="USDT",
            settlement_precision=_SETTLEMENT_PRECISION,
        )
    with pytest.raises(AccountingError, match="finite Decimal"):
        LedgerConfig(
            starting_cash=True,  # type: ignore[arg-type]
            multiplier=_MULTIPLIER,
            price_increment=_INCREMENT,
            taker_fee_rate=_TAKER_FEE,
            adverse_slippage_ticks=_SLIP_TICKS,
            is_inverse=False,
            settlement_currency="USDT",
            settlement_precision=_SETTLEMENT_PRECISION,
        )
    with pytest.raises(AccountingError, match="finite Decimal"):
        LedgerConfig(
            starting_cash=Decimal("NaN"),
            multiplier=_MULTIPLIER,
            price_increment=_INCREMENT,
            taker_fee_rate=_TAKER_FEE,
            adverse_slippage_ticks=_SLIP_TICKS,
            is_inverse=False,
            settlement_currency="USDT",
            settlement_precision=_SETTLEMENT_PRECISION,
        )
    with pytest.raises(AccountingError, match="finite Decimal"):
        LedgerConfig(
            starting_cash=Decimal("Infinity"),
            multiplier=_MULTIPLIER,
            price_increment=_INCREMENT,
            taker_fee_rate=_TAKER_FEE,
            adverse_slippage_ticks=_SLIP_TICKS,
            is_inverse=False,
            settlement_currency="USDT",
            settlement_precision=_SETTLEMENT_PRECISION,
        )
    with pytest.raises(AccountingError, match="inverse"):
        LedgerConfig(
            starting_cash=_STARTING_CASH,
            multiplier=_MULTIPLIER,
            price_increment=_INCREMENT,
            taker_fee_rate=_TAKER_FEE,
            adverse_slippage_ticks=_SLIP_TICKS,
            is_inverse=True,
            settlement_currency="USDT",
            settlement_precision=_SETTLEMENT_PRECISION,
        )
    with pytest.raises(AccountingError, match="uncrossed"):
        _fill(
            side=FillSide.BUY,
            quantity=Decimal("2"),
            fill_price=Decimal("101.0"),
            bid=Decimal("100.5"),
            ask=Decimal("100.5"),
            ts=10,
        )
    with pytest.raises(AccountingError, match="improving side"):
        _fill(
            side=FillSide.BUY,
            quantity=Decimal("2"),
            fill_price=Decimal("100.0"),
            bid=Decimal("100.0"),
            ask=Decimal("100.5"),
            ts=10,
        )
    with pytest.raises(AccountingError, match="adverse slippage"):
        reconcile_ledger(
            config,
            (
                _fill(
                    side=FillSide.BUY,
                    quantity=Decimal("2"),
                    fill_price=Decimal("102.0"),
                    bid=Decimal("100.0"),
                    ask=Decimal("100.5"),
                    ts=10,
                ),
            ),
        )
    with pytest.raises(AccountingError, match="fee identity"):
        reconcile_ledger(
            config,
            (
                _fill(
                    side=FillSide.BUY,
                    quantity=Decimal("2"),
                    fill_price=Decimal("101.0"),
                    bid=Decimal("100.0"),
                    ask=Decimal("100.5"),
                    ts=10,
                    commission=Decimal("0.01"),
                ),
            ),
        )
    with pytest.raises(AccountingError, match="observed funding"):
        reconcile_ledger(
            config,
            (
                valid,
                MarkRecord(timestamp_ns=15, mark_price=_MARK_PX),
                FundingRecord(
                    publication_ns=16,
                    effective_ns=20,
                    rate=_FUND_RATE,
                    settlement_mark=_MARK_PX,
                    settlement_currency="USDT",
                    observed_cashflow=Decimal("1"),
                ),
            ),
        )
    with pytest.raises(AccountingError, match="preceding mark"):
        reconcile_ledger(
            config,
            (
                FundingRecord(
                    publication_ns=1,
                    effective_ns=2,
                    rate=_FUND_RATE,
                    settlement_mark=_MARK_PX,
                    settlement_currency="USDT",
                    observed_cashflow=None,
                ),
            ),
        )
    with pytest.raises(AccountingError, match="latest declared mark"):
        reconcile_ledger(
            config,
            (
                valid,
                MarkRecord(timestamp_ns=15, mark_price=_MARK_PX),
                FundingRecord(
                    publication_ns=16,
                    effective_ns=20,
                    rate=_FUND_RATE,
                    settlement_mark=Decimal("103.0"),
                    settlement_currency="USDT",
                    observed_cashflow=None,
                ),
            ),
        )
    with pytest.raises(AccountingError, match="flat position"):
        reconcile_ledger(
            config,
            (
                MarkRecord(timestamp_ns=1, mark_price=_MARK_PX),
                FundingRecord(
                    publication_ns=2,
                    effective_ns=3,
                    rate=_FUND_RATE,
                    settlement_mark=_MARK_PX,
                    settlement_currency="USDT",
                    observed_cashflow=Decimal("0"),
                ),
            ),
        )
    with pytest.raises(AccountingError, match="flat position"):
        reconcile_ledger(
            config,
            (
                MarkRecord(timestamp_ns=1, mark_price=_MARK_PX),
                FundingRecord(
                    publication_ns=2,
                    effective_ns=3,
                    rate=_FUND_RATE,
                    settlement_mark=_MARK_PX,
                    settlement_currency="USDT",
                    observed_cashflow=Decimal("1"),
                ),
            ),
        )
    with pytest.raises(AccountingError, match="settlement currency"):
        reconcile_ledger(
            config,
            (
                FillRecord(
                    side=FillSide.BUY,
                    quantity=Decimal("2"),
                    actual_fill_price=Decimal("101.0"),
                    arrival_bid=Decimal("100.0"),
                    arrival_ask=Decimal("100.5"),
                    commission=_commission(Decimal("2"), Decimal("101.0")),
                    settlement_currency="USD",
                    availability_ns=8,
                    decision_ns=8,
                    computation_latency_ns=1,
                    submission_ns=9,
                    venue_latency_ns=1,
                    arrival_quote_ns=10,
                    fill_ns=10,
                ),
            ),
        )
    with pytest.raises(AccountingError, match="settlement currency"):
        reconcile_ledger(
            config,
            (
                MarkRecord(timestamp_ns=1, mark_price=_MARK_PX),
                FundingRecord(
                    publication_ns=2,
                    effective_ns=3,
                    rate=_FUND_RATE,
                    settlement_mark=_MARK_PX,
                    settlement_currency="USD",
                    observed_cashflow=None,
                ),
            ),
        )
    with pytest.raises(AccountingError, match="duplicate"):
        reconcile_ledger(
            config,
            (valid, MarkRecord(timestamp_ns=10, mark_price=_MARK_PX)),
        )
    with pytest.raises(AccountingError, match="strictly increase"):
        reconcile_ledger(
            config,
            (
                MarkRecord(timestamp_ns=20, mark_price=_MARK_PX),
                _fill(
                    side=FillSide.BUY,
                    quantity=Decimal("2"),
                    fill_price=Decimal("101.0"),
                    bid=Decimal("100.0"),
                    ask=Decimal("100.5"),
                    ts=10,
                ),
            ),
        )
    with pytest.raises(AccountingError, match="strictly positive"):
        _fill(
            side=FillSide.BUY,
            quantity=Decimal("2"),
            fill_price=Decimal("101.0"),
            bid=Decimal("100.0"),
            ask=Decimal("100.5"),
            ts=10,
            computation_latency_ns=0,
        )
    with pytest.raises(AccountingError, match="unsigned-64-bit"):
        _fill(
            side=FillSide.BUY,
            quantity=Decimal("2"),
            fill_price=Decimal("101.0"),
            bid=Decimal("100.0"),
            ask=Decimal("100.5"),
            ts=10,
            venue_latency_ns=-1,
        )
    with pytest.raises(AccountingError, match="overflows"):
        FillRecord(
            side=FillSide.BUY,
            quantity=Decimal("2"),
            actual_fill_price=Decimal("101.0"),
            arrival_bid=Decimal("100.0"),
            arrival_ask=Decimal("100.5"),
            commission=_commission(Decimal("2"), Decimal("101.0")),
            settlement_currency="USDT",
            availability_ns=(1 << 64) - 2,
            decision_ns=(1 << 64) - 2,
            computation_latency_ns=1,
            submission_ns=(1 << 64) - 1,
            venue_latency_ns=1,
            arrival_quote_ns=(1 << 64) - 1,
            fill_ns=(1 << 64) - 1,
        )
    with pytest.raises(AccountingError, match="FillSide"):
        FillRecord(
            side="buy",  # type: ignore[arg-type]
            quantity=Decimal("2"),
            actual_fill_price=Decimal("101.0"),
            arrival_bid=Decimal("100.0"),
            arrival_ask=Decimal("100.5"),
            commission=_commission(Decimal("2"), Decimal("101.0")),
            settlement_currency="USDT",
            availability_ns=8,
            decision_ns=8,
            computation_latency_ns=1,
            submission_ns=9,
            venue_latency_ns=1,
            arrival_quote_ns=10,
            fill_ns=10,
        )
    with pytest.raises(FrozenInstanceError):
        config.starting_cash = Decimal("1")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        valid.quantity = Decimal("9")  # type: ignore[misc]
    module = ast.parse(
        Path("src/harmonic_trader/integration/accounting.py").read_text(encoding="utf-8")
    )
    imported: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module.split(".", 1)[0])
    assert "nautilus_trader" not in imported


def test_repeated_reconciliation_is_immutable_and_repeatable() -> None:
    config = _ledger_config()
    events = (
        _fill(
            side=FillSide.BUY,
            quantity=Decimal("2"),
            fill_price=Decimal("101.0"),
            bid=Decimal("100.0"),
            ask=Decimal("100.5"),
            ts=10,
        ),
        MarkRecord(timestamp_ns=15, mark_price=_MARK_PX),
        FundingRecord(
            publication_ns=16,
            effective_ns=20,
            rate=_FUND_RATE,
            settlement_mark=_MARK_PX,
            settlement_currency="USDT",
        ),
        _fill(
            side=FillSide.SELL,
            quantity=Decimal("2"),
            fill_price=Decimal("109.5"),
            bid=Decimal("110.0"),
            ask=Decimal("110.5"),
            ts=30,
        ),
    )
    original_quantity = events[0].quantity
    first = reconcile_ledger(config, events)
    first_snapshots = first.snapshots
    second = reconcile_ledger(config, events)
    assert first == second
    assert first.snapshots == second.snapshots
    assert first.snapshots is first_snapshots
    assert first.snapshots is not second.snapshots
    assert events[0].quantity == original_quantity
    with pytest.raises((TypeError, AttributeError)):
        first.snapshots[0] = first.snapshots[-1]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        events[0].quantity = Decimal("3")  # type: ignore[misc]
    third = reconcile_ledger(config, events)
    assert third == first
    assert events[0].quantity == original_quantity
