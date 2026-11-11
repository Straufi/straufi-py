from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from .lib import checks


@dataclass(frozen=True, order=True)
class Instrument:
    """A tradeable instrument, with a `base` asset priced in a `quote` asset, on a `broker`.

    >>> Instrument("PEPE", "USDT", "binance")
    """

    base: str
    quote: str
    broker: str

    def __post_init__(self) -> None:
        # Put symbols as upper case and brokers lower case.
        object.__setattr__(self, "base", checks.text(self.base, "Instrument base").upper())
        object.__setattr__(self, "quote", checks.text(self.quote, "Instrument quote").upper())
        object.__setattr__(self, "broker", checks.text(self.broker, "Instrument broker").lower())

    def __str__(self) -> str:
        return f"{self.base}/{self.quote} on {self.broker}"

    def __iter__(self) -> Iterator[str]:
        yield self.base
        yield self.quote
        yield self.broker

    def matches(self, broker: str | None, base: str | None, quote: str | None) -> bool:
        return (
            (broker or "").lower() == self.broker
            and (base or "").upper() == self.base
            and (quote or "").upper() == self.quote
        )

    def to_dict(self) -> dict[str, str]:
        return {"base": self.base, "quote": self.quote, "broker": self.broker}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Instrument":
        values: dict[str, Any] = {key: data.get(key) for key in ("base", "quote", "broker")}
        return cls(**values)


@dataclass(frozen=True)
class Budget:
    """How much of an asset (`symbol`) is available on a broker."""

    broker: str
    symbol: str
    amount: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "broker", checks.text(self.broker, "Budget broker").lower())
        object.__setattr__(self, "symbol", checks.text(self.symbol, "Budget symbol").upper())
        object.__setattr__(self, "amount", checks.number(self.amount, "Budget amount"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Budget":
        values: dict[str, Any] = {key: data.get(key) for key in ("broker", "symbol", "amount")}
        return cls(**values)
