import dataclasses
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import TYPE_CHECKING

from .config import Config
from .instrument import Instrument
from .lib.errors import NotRunningError, ValidationError
from .order import Order

if TYPE_CHECKING:
    import pandas as pd

    from .lib.runtime import RunContext

type Orders = Order | Iterable[Orders]


def _flatten(items: Iterable[object], method: str) -> Iterable[Order]:
    for item in items:
        if isinstance(item, Order):
            yield item
        elif isinstance(item, Iterable) and not isinstance(item, str | bytes | dict):
            yield from _flatten(item, method)
        else:
            raise ValidationError(f"{method}() expects Order(...)s, got {item!r}")


class Strategy:
    """Base class of every Straufi strategy.

    Subclass it and define two methods:
    - `config()` returns a `straufi.Config`: the instruments and indicators you need
    - `run(self)` is called when your strategy is triggered. Use `get_df`, `get_budget`
      and `get_positions` to look at the market and your account, and `place_order` and
      `cancel_order` to trade.
    """

    _context: "RunContext | None" = None

    @staticmethod
    def config() -> Config:
        raise NotImplementedError("Your strategy must define a @staticmethod config() method")

    def run(self) -> None:
        raise NotImplementedError("Your strategy must define a run() method")

    def get_df(self, instrument_or_alias: str | Instrument | None = None) -> "pd.DataFrame":
        """Returns a DataFrame of candles and indicators with all your instruments or the one you specify.

        >>> self.get_df("pepe")  # One of your instruments, by its alias
        >>> self.get_df(Instrument("DOGE", "USDT", "binance"))  # The same, by its Instrument
        >>> self.get_df()  # All your instruments, sorted by instrument then timestamp
        >>> self.get_df().groupby("instrument")  # ... for example to work on each instrument

        Index columns: timestamp, instrument
        Columns: open, high, low, close, volume, plus one column per indicator value (see `straufi.indicators`).

        By default the dataframe is already sorted:
        1. By instrument (alphanumerically with base + quote + broker)
        2. By timestamp (oldest to newest)
        """
        context = self._require_context("get_df")
        if instrument_or_alias is None:
            return context.data.copy()

        instrument = context.config.resolve_instrument(instrument_or_alias)
        rows = context.data[context.data["instrument"] == instrument]
        return rows.copy()  # pyright: ignore[reportReturnType]

    def now(self) -> datetime:
        """The time this run was triggered, in UTC. In a backtest, the simulated time.

        Your data ends with the last candle closed at that time. Prefer it over `datetime.now()`, so that your
        strategy behaves the same in backtests and live.
        """
        return self._require_context("now").execution_time

    def get_budget(self) -> dict[str, dict[str, float]]:
        """How much of each asset you have, by broker then by symbol.

        It only includes the brokers of the instruments in your Config.

        >>> self.get_budget()  # {"binance": {"USDT": 100.0, "PEPE": 5000.0}, "coinbase": {"BTC": 0.5}}
        >>> self.get_budget()["binance"].get("USDT", 0)  # How much USDT you can spend on Binance
        """
        context = self._require_context("get_budget")
        brokers = {instrument.broker for instrument in context.config.instruments.values()}

        result: dict[str, dict[str, float]] = defaultdict(dict)
        for budget in context.budgets:
            if budget.broker in brokers:
                result[budget.broker][budget.symbol] = budget.amount

        return dict(result)

    def get_positions(self) -> list[Order]:
        """Your open orders: submitted, waiting in the order book, or partially filled.

        >>> self.get_positions()  # All of them
        """
        context = self._require_context("get_positions")
        return list(context.positions)

    def place_order(self, *orders: Orders) -> list[Order]:
        """Place one or more orders. Returns the orders placed."""
        context = self._require_context("place_order")

        flat = list(_flatten(orders, "place_order"))
        if not flat:
            raise ValidationError("place_order() needs at least one Order")

        placed = []
        for order in flat:
            if not order.is_new:
                raise ValidationError(
                    f"This order already exists (status {order.status}). Create a new one, or use cancel_order()"
                )

            if order.instrument not in context.config.instruments.values():
                raise ValidationError(f"Cannot place an order on {order.instrument}: it is not in your Config")

            # Copy instead of modifying the user's object so they can reuse it.
            placed.append(dataclasses.replace(order))

        context.orders.extend(placed)
        return placed

    def cancel_order(self, *orders: Orders) -> list[Order]:
        """Cancel one or more of your open orders, as returned by `get_positions()`. Returns the orders to cancel.

        >>> for order in self.get_positions():
        ...     if order.side == OrderSide.BUY:
        ...         self.cancel_order(order)

        Canceling the same order twice is harmless. Like `place_order`, it accepts several orders or lists.
        """
        context = self._require_context("cancel_order")

        flat = list(_flatten(orders, "cancel_order"))
        if not flat:
            raise ValidationError("cancel_order() needs at least one Order")

        open_ids = {position.id for position in context.positions if position.id is not None}
        canceled_ids = {order.id for order in context.cancellations}
        canceled = []
        for order in flat:
            if order.is_new:
                raise ValidationError(
                    "This order was never placed, so it can't be canceled. Only orders from get_positions() can be"
                )
            if order.id not in open_ids:
                raise ValidationError(f"{order} is not one of your open orders (see get_positions())")
            if order.id in canceled_ids:
                continue

            canceled_ids.add(order.id)
            canceled.append(order)

        context.cancellations.extend(canceled)
        return canceled

    def instruments(self) -> Iterator[tuple[str, Instrument]]:
        """Iterate over the instruments in your Config.

        >>> for alias, instrument in self.instruments():
        ...     print(alias, instrument)
        """
        context = self._require_context("instruments")
        yield from context.config.instruments.items()

    def _require_context(self, method: str) -> "RunContext":
        if self._context is None:
            raise NotRunningError(f"{method}() only works while your strategy is running on Straufi")
        return self._context
