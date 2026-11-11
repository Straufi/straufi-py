from dataclasses import dataclass, fields
from datetime import datetime
from typing import TYPE_CHECKING, Any, SupportsFloat

from .enums import OrderSide, OrderStatus, OrderTimeInForce, OrderType
from .instrument import Instrument
from .lib import checks
from .lib.errors import ValidationError

_LIMIT_TYPES = {
    OrderType.LIMIT,
    OrderType.ICEBERG,
    OrderType.STOP_LOSS_LIMIT,
    OrderType.TAKE_PROFIT_LIMIT,
    OrderType.LIMIT_MAKER,
}
_TRIGGERED_TYPES = {
    OrderType.STOP_LOSS,
    OrderType.TAKE_PROFIT,
    OrderType.STOP_LOSS_LIMIT,
    OrderType.TAKE_PROFIT_LIMIT,
}
_TIME_IN_FORCE_TYPES = {
    OrderType.LIMIT,
    OrderType.ICEBERG,
    OrderType.STOP_LOSS_LIMIT,
    OrderType.TAKE_PROFIT_LIMIT,
}
_DATETIME_FIELDS = ("submitted_at", "new_at", "triggered_at", "last_partially_filled_at")


@dataclass(kw_only=True, repr=False)
class Order:
    """An order to buy or sell an instrument.

    Create one and pass it to `self.place_order(...)`:

    >>> Order(
    ...     instrument=Instrument("BTC", "USDT", "binance"),
    ...     type=OrderType.LIMIT,
    ...     side=OrderSide.BUY,
    ...     volume=100,  # ! For Market Buy, use `quote_volume` instead
    ...     limit_price=0.25,
    ... )

    `volume` is an amount of the base asset (e.g. 100 PEPE). Market orders can use
    `quote_volume` instead, an amount of the quote asset (e.g. spend 50 USDT).
    """

    instrument: Instrument

    type: OrderType
    side: OrderSide
    volume: float | None = None
    quote_volume: float | None = None
    display_volume: float | None = None
    time_in_force: OrderTimeInForce | None = None
    limit_price: float | None = None
    trigger_price: float | None = None
    trailing_delta: float | None = None

    # Set by Straufi on existing orders (positions). Leave these empty on new orders.
    id: str | None = None
    order_id: str | None = None
    status: OrderStatus | None = None
    in_order_book: bool | None = None
    volume_traded: float | None = None
    quote_volume_traded: float | None = None
    submitted_at: datetime | None = None
    new_at: datetime | None = None
    triggered_at: datetime | None = None
    last_partially_filled_at: datetime | None = None

    if TYPE_CHECKING:
        # The constructor also accepts enums as text ("buy"), dates as ISO 8601 text and any kind of number.
        def __init__(
            self,
            *,
            instrument: Instrument,
            type: OrderType | str,
            side: OrderSide | str,
            volume: SupportsFloat | None = None,
            quote_volume: SupportsFloat | None = None,
            display_volume: SupportsFloat | None = None,
            time_in_force: OrderTimeInForce | str | None = None,
            limit_price: SupportsFloat | None = None,
            trigger_price: SupportsFloat | None = None,
            trailing_delta: SupportsFloat | None = None,
            id: str | None = None,
            order_id: str | None = None,
            status: OrderStatus | str | None = None,
            in_order_book: bool | None = None,
            volume_traded: SupportsFloat | None = None,
            quote_volume_traded: SupportsFloat | None = None,
            submitted_at: datetime | str | None = None,
            new_at: datetime | str | None = None,
            triggered_at: datetime | str | None = None,
            last_partially_filled_at: datetime | str | None = None,
        ) -> None: ...

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise ValidationError(
                f"Order instrument must be an Instrument(...), got {self.instrument!r}. "
                "Use the ones of your Config, e.g. from self.instruments()"
            )
        self.type = OrderType.parse(self.type, "Order type")
        self.side = OrderSide.parse(self.side, "Order side")
        if self.time_in_force is not None:
            self.time_in_force = OrderTimeInForce.parse(self.time_in_force, "Order time_in_force")
        if self.status is not None:
            self.status = OrderStatus.parse(self.status, "Order status")

        for name in (
            "volume", "quote_volume", "display_volume", "limit_price", "trigger_price",
            "trailing_delta", "volume_traded", "quote_volume_traded",
        ):  # fmt: skip
            setattr(self, name, checks.optional_number(getattr(self, name), f"Order {name}"))

        for name in _DATETIME_FIELDS:
            setattr(self, name, checks.optional_datetime(getattr(self, name), f"Order {name}"))

        if self.is_new:
            if self.time_in_force is None and self.type in _TIME_IN_FORCE_TYPES:
                self.time_in_force = OrderTimeInForce.GTC
            self.validate()

    @property
    def is_new(self) -> bool:
        """True for an order you are creating, False for an order that already exists at the broker."""
        return self.status is None

    @property
    def base(self) -> str:
        return self.instrument.base

    @property
    def quote(self) -> str:
        return self.instrument.quote

    @property
    def broker(self) -> str:
        return self.instrument.broker

    def validate(self) -> None:
        """Check that this order makes sense before sending it. Raises `ValidationError` if not."""

        def _fail_validation(message: str) -> None:
            raise ValidationError(f"Invalid {self.type.name} order: {message}")

        def _forbid_setter(*names: str, reason: str) -> None:
            for name in names:
                if getattr(self, name) is not None:
                    _fail_validation(f"{name} can't be set ({reason}).")

        volume, limit_price, display_volume = self.volume, self.limit_price, self.display_volume

        # How much to trade.
        if volume is not None and volume <= 0:
            _fail_validation(f"volume must be greater than 0, got {volume}.")
        if self.quote_volume is not None and self.quote_volume <= 0:
            _fail_validation(f"quote_volume must be greater than 0, got {self.quote_volume}.")
        if self.type is OrderType.MARKET:
            if (self.volume is None) == (self.quote_volume is None):
                _fail_validation(
                    "set either volume (amount of base asset) or quote_volume (amount of quote asset), not both."
                )
        else:
            if volume is None:
                _fail_validation("volume is required.")
            _forbid_setter("quote_volume", reason="only MARKET orders can use quote_volume")

        # Prices.
        if self.type in _LIMIT_TYPES:
            if limit_price is None:
                _fail_validation("limit_price is required.")
            elif limit_price <= 0:
                _fail_validation(f"limit_price must be greater than 0, got {limit_price}.")
        else:
            _forbid_setter("limit_price", reason="use a LIMIT order type to set a limit price")

        if self.type in _TRIGGERED_TYPES:
            if self.trigger_price is None and self.trailing_delta is None:
                _fail_validation("set a trigger_price, a trailing_delta, or both.")
            if self.trigger_price is not None and self.trigger_price <= 0:
                _fail_validation(f"trigger_price must be greater than 0, got {self.trigger_price}.")
            if self.trailing_delta is not None and self.trailing_delta <= 0:
                _fail_validation(f"trailing_delta must be greater than 0, got {self.trailing_delta}.")
        else:
            _forbid_setter(
                "trigger_price", "trailing_delta", reason="only STOP_LOSS and TAKE_PROFIT orders are triggered"
            )

        if self.type is OrderType.ICEBERG:
            if display_volume is None:
                _fail_validation("display_volume is required (the visible part of volume).")
            elif volume is not None and not 0 < display_volume < volume:
                _fail_validation(f"display_volume must be between 0 and volume ({volume}), got {display_volume}.")
        else:
            _forbid_setter("display_volume", reason="only ICEBERG orders have a display_volume")

        if self.type not in _TIME_IN_FORCE_TYPES:
            _forbid_setter("time_in_force", reason=f"{self.type.name} orders don't stay in the order book")

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible dict containing every field that has a value.
        The instrument is flattened into `base`, `quote` and `broker` keys."""
        result: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None:
                continue

            if isinstance(value, Instrument):
                result.update(value.to_dict())
                continue
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, OrderType | OrderSide | OrderStatus | OrderTimeInForce):
                value = value.value
            result[f.name] = value
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Order":
        """Build an Order from a dict such as the ones produced by `to_dict`. Unknown keys are ignored."""
        if not isinstance(data, dict):
            raise ValidationError(f"An order must be an object, got {data!r}")

        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        # The instrument is either flattened (as produced by `to_dict`), or a nested object.
        instrument = values.get("instrument", data)
        if isinstance(instrument, dict):
            values["instrument"] = Instrument.from_dict(instrument)
        return cls(**values)

    def __repr__(self) -> str:
        # Only show what's set instead of every nullable field.
        parts = []
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None:
                continue
            if isinstance(value, OrderType | OrderSide | OrderStatus | OrderTimeInForce):
                parts.append(f"{f.name}={value.name}")
            elif isinstance(value, datetime):
                parts.append(f"{f.name}={value.isoformat()}")
            elif isinstance(value, Instrument):
                parts.append(f"{f.name}={value}")
            else:
                parts.append(f"{f.name}={value!r}")
        return f"Order({', '.join(parts)})"
