"""Technical indicators you can declare in `Config(indicators=...)`.

Indicators are computed by Straufi and show up as columns in `self.get_df(...)`:
- for indicators with a single value, the column is its key:
  `"rsi14": RSI(period=14)` -> `df["rsi14"]`
- For indicators with several values, the columns are named `<key>_<value>`:
  `"bb": BollingerBands(period=20)` -> `df["bb_upper"]`, `df["bb_middle"]`, `df["bb_lower"]`
"""

from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, ClassVar

from .enums import PriceType
from .lib import checks
from .lib.errors import ValidationError


@dataclass(frozen=True)
class Indicator:
    name: ClassVar[str]
    """The indicator's name in Straufi."""

    outputs: ClassVar[tuple[str, ...]]
    """Names of the values this indicator produces."""

    def __post_init__(self) -> None:
        name = type(self).__name__
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == "price_type":
                object.__setattr__(self, f.name, PriceType.parse(value, f"{name} price_type"))
            elif f.type is int:
                object.__setattr__(self, f.name, checks.positive_int(value, f"{name} {f.name}"))

    def parameters(self) -> dict[str, Any]:
        return {
            _camel_case(f.name): (
                getattr(self, f.name).value if isinstance(getattr(self, f.name), Enum) else getattr(self, f.name)
            )
            for f in fields(self)
        }

    def columns(self, key: str) -> dict[str, str]:
        """Maps each output of this indicator to its column name in the data, for the given key."""
        if len(self.outputs) == 1:
            return {self.outputs[0]: key}
        return {output: f"{key}_{output}" for output in self.outputs}

    def to_dict(self, key: str) -> dict[str, Any]:
        return {"indicatorName": self.name, "parameters": self.parameters(), "columns": self.columns(key)}


def _camel_case(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(word.capitalize() for word in rest)


@dataclass(frozen=True)
class SMA(Indicator):
    """Simple moving average of the last `period` candles."""

    name: ClassVar[str] = "sma"
    outputs: ClassVar[tuple[str, ...]] = ("sma",)

    period: int
    price_type: PriceType | str = PriceType.CLOSE


@dataclass(frozen=True)
class EMA(Indicator):
    """Exponential moving average: like SMA, but recent candles weigh more."""

    name: ClassVar[str] = "ema"
    outputs: ClassVar[tuple[str, ...]] = ("ema",)

    period: int
    price_type: PriceType | str = PriceType.CLOSE


@dataclass(frozen=True)
class RSI(Indicator):
    """Relative strength index, between 0 and 100. Usually < 30 is "oversold" and > 70 is "overbought"."""

    name: ClassVar[str] = "rsi"
    outputs: ClassVar[tuple[str, ...]] = ("rsi",)

    period: int = 14
    price_type: PriceType | str = PriceType.CLOSE


@dataclass(frozen=True)
class ATR(Indicator):
    """Average true range: how much the price moves per candle, on average (volatility)."""

    name: ClassVar[str] = "atr"
    outputs: ClassVar[tuple[str, ...]] = ("atr",)

    period: int = 14


@dataclass(frozen=True)
class BollingerBands(Indicator):
    """Bollinger bands: a moving average (`middle`) with bands 2 standard deviations above and below."""

    name: ClassVar[str] = "bollinger-bands"
    outputs: ClassVar[tuple[str, ...]] = ("upper", "middle", "lower")

    period: int = 20
    price_type: PriceType | str = PriceType.CLOSE


@dataclass(frozen=True)
class MACD(Indicator):
    """Moving average convergence divergence: `macd` = EMA(short_period) - EMA(long_period), and `signal` =
    EMA(signal_period) of `macd`."""

    name: ClassVar[str] = "macd"
    outputs: ClassVar[tuple[str, ...]] = ("macd", "signal")

    short_period: int = 12
    long_period: int = 26
    signal_period: int = 9
    price_type: PriceType | str = PriceType.CLOSE

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.short_period >= self.long_period:
            raise ValidationError(
                f"MACD short_period ({self.short_period}) must be smaller than long_period ({self.long_period})"
            )
