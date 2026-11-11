from enum import StrEnum

from .lib.errors import ValidationError


class LooseEnum(StrEnum):
    """An enum that also accepts its members' names as text, in any case: "buy", "Stop-Loss"..."""

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            key = value.strip().upper().replace("-", "_").replace(" ", "_")
            return cls.__members__.get(key)
        return None

    @classmethod
    def parse(cls, value: object, field: str):
        try:
            return cls(value)
        except ValueError:
            choices = ", ".join(f"{cls.__name__}.{name}" for name in cls.__members__)
            raise ValidationError(f"{field} must be one of {choices}, got {value!r}") from None


class OrderType(LooseEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    ICEBERG = "ICEBERG"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS_LIMIT = "STOP_LOSS_LIMIT"
    TAKE_PROFIT_LIMIT = "TAKE_PROFIT_LIMIT"
    LIMIT_MAKER = "LIMIT_MAKER"


class OrderSide(LooseEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderTimeInForce(LooseEnum):
    GTC = "GTC"
    """Good 'til canceled: the order stays in the order book until it's filled or canceled."""
    IOC = "IOC"
    """Immediate or cancel: whatever can't be filled right away is canceled."""


class OrderStatus(LooseEnum):
    SUBMITTED = "SUBMITTED"
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PriceType(LooseEnum):
    """Which price of each candle an indicator is computed on."""

    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
