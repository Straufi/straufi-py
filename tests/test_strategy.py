from datetime import UTC, datetime, timedelta, timezone

import pandas as pd
import pytest

from straufi import (
    Budget,
    Config,
    Instrument,
    NotRunningError,
    Order,
    Strategy,
    ValidationError,
    crossed_above,
    crossed_below,
)
from straufi.lib import runtime

PEPE = Instrument("PEPE", "USDT", "binance")
DOGE = Instrument("DOGE", "USDT", "binance")
BTC = Instrument("BTC", "EUR", "kraken")


class Sample(Strategy):
    @staticmethod
    def config():
        return Config(instruments={"pepe": PEPE, "doge": DOGE, "btc": BTC}, lookback=10, interval="1h", frequency="1h")

    def run(self):
        for _, instrument in self.instruments():
            self.place_order(Order(instrument=instrument, type="MARKET", side="BUY", quote_volume=10))


def position(id, instrument, **kwargs):
    return Order(id=id, instrument=instrument, type="LIMIT", side="BUY", volume=1, limit_price=1, status="NEW",
                 **kwargs)  # fmt: skip


def make_context(strategy):
    timestamps = pd.to_datetime([1697040000, 1697043600] * 3, unit="s", utc=True)
    data = pd.DataFrame(
        {"instrument": [BTC, BTC, DOGE, DOGE, PEPE, PEPE], "close": [1.0, 2.0, 10.0, 20.0, 100.0, 200.0]},
        index=pd.Index(timestamps, name="timestamp"),
    )
    context = runtime.RunContext(
        config=runtime.load_config(strategy),
        data=data,
        budgets=[
            Budget("binance", "USDT", 100),
            Budget("binance", "PEPE", 1e6),
            Budget("kraken", "EUR", 5),
            Budget("coinbase", "USDC", 50),  # No instrument on this broker
        ],
        positions=[position("p1", PEPE), position("p2", BTC)],
        execution_time=datetime(2023, 10, 11, 18, tzinfo=UTC),
        mode=runtime.RunMode.LIVE,
    )
    runtime.bind(strategy, context)
    return context


def test_get_df():
    strategy = Sample()
    make_context(strategy)

    pepe = strategy.get_df("pepe")
    assert pepe["close"].tolist() == [100.0, 200.0]
    assert pepe.index.name == "timestamp"
    assert set(pepe["instrument"]) == {PEPE}
    assert strategy.get_df(DOGE)["close"].tolist() == [10.0, 20.0]

    everything = strategy.get_df()
    assert len(everything) == 6
    # Instruments are hashable and ordered, so the usual pandas tools work on them
    last_closes = everything.groupby("instrument")["close"].last()
    assert last_closes.to_dict() == {BTC: 2.0, DOGE: 20.0, PEPE: 200.0}
    assert list(everything.sort_values("instrument")["instrument"].unique()) == [BTC, DOGE, PEPE]

    pepe["close"] = 0  # Copies: changing them doesn't change the data
    assert strategy.get_df("pepe")["close"].tolist() == [100.0, 200.0]
    with pytest.raises(ValidationError, match=r"Unknown instrument 'eth'\. Your instruments are: 'pepe'"):
        strategy.get_df("eth")


def test_get_budget_and_positions():
    strategy = Sample()
    make_context(strategy)
    assert strategy.get_budget() == {"binance": {"USDT": 100, "PEPE": 1e6}, "kraken": {"EUR": 5}}
    assert [o.id for o in strategy.get_positions()] == ["p1", "p2"]


def test_run_strategy():
    strategy = Sample()
    context = make_context(strategy)
    runtime.run_strategy(strategy, context)
    assert [o.instrument for o in context.orders] == [PEPE, DOGE, BTC]
    assert context.cancellations == []


def test_place_order_accepts_any_shape():
    strategy = Sample()
    context = make_context(strategy)
    a = Order(instrument=PEPE, type="MARKET", side="BUY", volume=1)
    b = Order(instrument=DOGE, type="MARKET", side="SELL", volume=2)
    c = Order(instrument=BTC, type="MARKET", side="SELL", volume=3)
    placed = strategy.place_order(a, [b, (c,)])
    assert [o.volume for o in placed] == [1, 2, 3]
    assert placed[0] is not a  # A copy, so the user can reuse theirs
    assert context.orders == placed


def test_place_order_errors():
    strategy = Sample()
    context = make_context(strategy)
    with pytest.raises(ValidationError, match="at least one"):
        strategy.place_order()
    with pytest.raises(ValidationError, match="place_order\\(\\) expects Order"):
        strategy.place_order("buy")  # pyright: ignore[reportArgumentType]
    with pytest.raises(ValidationError, match="already exists"):
        strategy.place_order(strategy.get_positions()[0])
    with pytest.raises(ValidationError, match="not in your Config"):
        strategy.place_order(
            Order(instrument=Instrument("ETH", "USDT", "binance"), type="MARKET", side="BUY", volume=1)
        )
    order = Order(instrument=PEPE, type="LIMIT", side="BUY", volume=1, limit_price=1)
    order.limit_price = None  # Modified after creation
    with pytest.raises(ValidationError, match="limit_price is required"):
        strategy.place_order(order)
    assert context.orders == []


def test_cancel_order():
    strategy = Sample()
    context = make_context(strategy)
    p1, p2 = strategy.get_positions()
    assert strategy.cancel_order(p1) == [p1]
    assert strategy.cancel_order([p1, p2]) == [p2]  # p1 is already canceled
    assert context.cancellations == [p1, p2]

    with pytest.raises(ValidationError, match="at least one"):
        strategy.cancel_order()
    with pytest.raises(ValidationError, match="never placed"):
        strategy.cancel_order(Order(instrument=PEPE, type="MARKET", side="BUY", volume=1))
    with pytest.raises(ValidationError, match="not one of your open orders"):
        strategy.cancel_order(position("unknown", PEPE))
    with pytest.raises(ValidationError, match="cancel_order\\(\\) expects Order"):
        strategy.cancel_order("p1")  # pyright: ignore[reportArgumentType]


def test_run_strategy_resets_the_actions():
    class CancelAll(Sample):
        def run(self):
            self.cancel_order(self.get_positions())

    strategy = CancelAll()
    context = make_context(strategy)
    context.orders.append(Order(instrument=PEPE, type="MARKET", side="BUY", volume=1))
    runtime.run_strategy(strategy, context)
    assert context.orders == []
    assert [o.id for o in context.cancellations] == ["p1", "p2"]


def test_instruments():
    strategy = Sample()
    make_context(strategy)
    assert list(strategy.instruments()) == [("pepe", PEPE), ("doge", DOGE), ("btc", BTC)]


def test_not_running():
    with pytest.raises(NotRunningError):
        Sample().get_df("pepe")
    with pytest.raises(NotRunningError):
        Sample().cancel_order()


def test_load_config_variants():
    class AsAttribute(Strategy):
        config = Config(instruments={"pepe": PEPE}, lookback=1, interval="1h", frequency="1h")  # pyright: ignore[reportAssignmentType]

        def run(self): ...

    class AsMethod(Strategy):
        def config(self):  # pyright: ignore[reportIncompatibleMethodOverride]
            return Config(instruments={"pepe": PEPE}, lookback=1, interval="1h", frequency="1h")

        def run(self): ...

    class NoRun(Strategy):
        @staticmethod
        def config():
            return Config(instruments={"pepe": PEPE}, lookback=1, interval="1h", frequency="1h")

    class BadConfig(Strategy):
        @staticmethod
        def config():  # pyright: ignore[reportIncompatibleMethodOverride]
            return {"lookback": 1}

        def run(self): ...

    assert runtime.load_config(AsAttribute()).lookback == 1
    assert runtime.load_config(AsMethod()).lookback == 1
    with pytest.raises(ValidationError, match="run"):
        runtime.load_config(NoRun())
    with pytest.raises(ValidationError, match=r"must return a Config"):
        runtime.load_config(BadConfig())


def test_crossovers():
    fast, slow = pd.Series([1, 2, 4]), pd.Series([3, 3, 3])
    assert crossed_above(fast, slow)
    assert not crossed_below(fast, slow)
    assert crossed_below(pd.Series([50, 20]), 30)
    assert not crossed_above(pd.Series([float("nan"), 50]), 30)
    assert not crossed_above(pd.Series([50]), 30)


def test_now():
    strategy = Sample()
    context = make_context(strategy)
    assert strategy.now() == datetime(2023, 10, 11, 18, tzinfo=UTC)
    assert context.mode == runtime.RunMode.LIVE

    with pytest.raises(NotRunningError):
        Sample().now()


def test_run_context_execution_time_and_mode():
    context = make_context(Sample())
    paris = timezone(timedelta(hours=2))
    other = runtime.RunContext(
        config=context.config, data=context.data, budgets=[], positions=[],
        execution_time=datetime(2023, 10, 11, 20, tzinfo=paris), mode=runtime.RunMode.BACKTEST,
    )  # fmt: skip
    assert other.execution_time == datetime(2023, 10, 11, 18, tzinfo=UTC)
    assert other.execution_time.tzinfo is UTC
    assert other.mode == runtime.RunMode.BACKTEST

    with pytest.raises(ValidationError, match="timezone"):
        runtime.RunContext(config=context.config, data=context.data, budgets=[], positions=[],
                           execution_time=datetime(2023, 10, 11, 18), mode=runtime.RunMode.LIVE)  # fmt: skip
    with pytest.raises(ValidationError, match="mode must be one of live, paper, backtest"):
        runtime.RunContext(config=context.config, data=context.data, budgets=[], positions=[],
                           execution_time=context.execution_time, mode="replay")  # pyright: ignore[reportArgumentType]  # fmt: skip
