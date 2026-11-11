import math
import numbers
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import pandas as pd


def _last_two(value: "pd.Series | float") -> tuple[float, float]:
    if isinstance(value, numbers.Real):
        return float(value), float(value)

    series = cast("pd.Series", value)
    if len(series) < 2:
        return math.nan, math.nan

    return float(series.iloc[-2]), float(series.iloc[-1])


def crossed_above(series: "pd.Series", other: "pd.Series | float") -> bool:
    """True if `series` went from below (or equal to) `other` to above it on the last candle.

    >>> crossed_above(df["ema_fast"], df["ema_slow"])
    >>> crossed_above(df["rsi14"], 30)
    """
    (a_prev, a_last), (b_prev, b_last) = _last_two(series), _last_two(other)
    return a_prev <= b_prev and a_last > b_last


def crossed_below(series: "pd.Series", other: "pd.Series | float") -> bool:
    """True if `series` went from above (or equal to) `other` to below it on the last candle.

    >>> crossed_below(df["ema_fast"], df["ema_slow"])
    >>> crossed_below(df["rsi14"], 30)
    """
    (a_prev, a_last), (b_prev, b_last) = _last_two(series), _last_two(other)
    return a_prev >= b_prev and a_last < b_last
