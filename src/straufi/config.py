from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from .frequency import Every, Frequency
from .indicators import Indicator
from .instrument import Instrument
from .lib import checks, durations
from .lib.errors import ValidationError

RESERVED_COLUMNS = ("timestamp", "instrument", "open", "high", "low", "close", "volume")

MANIFEST_VERSION = 1
"""The version of the shape of `Config.to_dict()`. Needs to be bumped when making breaking
changes to the config's shape."""


@dataclass(kw_only=True)
class Config:
    """What your strategy needs: the instruments it trades, the indicators it uses and how much history.

    >>> Config(
    ...     instruments={"pepe": Instrument("PEPE", "USDT", "binance")},
    ...     indicators={"rsi14": RSI(period=14)},
    ...     lookback=500,
    ...     interval="15min",
    ...     frequency=Every("1h"),
    ... )
    """

    instruments: Mapping[str, Instrument]
    """The instruments your strategy needs to trade or needs the data of. This should be a dictionary where the keys
    are a short alias you give to the instruments to identify them easily in your code."""

    indicators: Mapping[str, Indicator] = field(default_factory=dict)
    """The indicators computed on each instrument's data. The dictionary keys are a short alias you give to the
    indicators that will be used for the names of the columns in the resulting DataFrame."""

    lookback: int
    """How many candles of history your strategy receives, per instrument. Each candle spans `interval`."""

    interval: timedelta
    """The size of the candles, like `"15min"`, `"1h"` or `timedelta(hours=4)`: 5, 10, 15, 20 or 30 minutes, or 1,
    2, 3, 4, 6, 12 or 24 hours."""

    frequency: Frequency
    """When your strategy runs, like `Every("15min")` or `Every(hours=1)`. It must be a multiple of `interval`. A
    text like `"15min"` is a shorthand for `Every("15min")`."""

    if TYPE_CHECKING:

        def __init__(
            self,
            *,
            instruments: Mapping[str, Instrument],
            lookback: int,
            interval: str | timedelta,
            frequency: Frequency | str,
            indicators: Mapping[str, Indicator] | None = None,
        ) -> None: ...

    def __post_init__(self) -> None:
        self.lookback = checks.positive_int(self.lookback, "Config lookback")
        self.interval = timedelta(minutes=durations.to_minutes(self.interval, "interval"))
        self.frequency = Frequency.parse(self.frequency)
        if isinstance(self.frequency, Every) and timedelta(minutes=self.frequency.minutes) % self.interval:
            raise ValidationError(
                f"frequency must be a multiple of interval: {self.frequency!r} can't run on"
                f" {durations.format_minutes(self.interval // timedelta(minutes=1))} candles"
            )
        self.instruments = self._check_instruments(self.instruments)
        self.indicators = self._check_indicators({} if self.indicators is None else self.indicators)

    @staticmethod
    def _check_instruments(value: object) -> dict[str, Instrument]:
        if not isinstance(value, Mapping):
            raise ValidationError('instruments must be a dict like {"pepe": Instrument("PEPE", "USDT", "binance")}')

        result: dict[str, Instrument] = {}
        for name, instrument in value.items():
            name = checks.text(name, "Instrument name")

            if not isinstance(instrument, Instrument):
                raise ValidationError(f"instruments[{name!r}] must be an Instrument(...), got {instrument!r}")

            for other_name, other in result.items():
                if other == instrument:
                    raise ValidationError(f"{instrument} appears twice: as {other_name!r} and as {name!r}")

            result[name] = instrument

        if not result:
            raise ValidationError("instruments can't be empty: your strategy must need data or trade something")

        return result

    @staticmethod
    def _check_indicators(value: object) -> dict[str, Indicator]:
        if not isinstance(value, Mapping):
            raise ValidationError('indicators must be a dict like {"rsi14": RSI(period=14)}')

        result: dict[str, Indicator] = {}
        column_owners: dict[str, str] = {}
        for key, indicator in value.items():
            key = checks.text(key, "Indicator name")
            if isinstance(indicator, type) and issubclass(indicator, Indicator):
                raise ValidationError(
                    f"indicators[{key!r}] should be instantiated. Did you forget the parentheses?"
                    f" e.g. {indicator.__name__}(period=14)"
                )

            if not isinstance(indicator, Indicator):
                raise ValidationError(
                    f"indicators[{key!r}] must be an indicator like RSI(period=14), got {indicator!r}"
                )

            for column in indicator.columns(key).values():
                if column in RESERVED_COLUMNS:
                    raise ValidationError(f"Indicator name {column!r} is reserved: please choose another one")
                if column in column_owners:
                    raise ValidationError(
                        f"Indicators {column_owners[column]!r} and {key!r} have the same name, they would"
                        f" both create a column named {column!r}. Please rename one of them"
                    )
                column_owners[column] = key

            result[key] = indicator

        return result

    def resolve_instrument_alias(self, instrument: "str | Instrument") -> str:
        """Returns the alias of an instrument, given an Instrument instance."""
        if isinstance(instrument, Instrument):
            for alias, candidate in self.instruments.items():
                if candidate == instrument:
                    return alias

            raise ValidationError(f"{instrument} is not in your instruments")

        if instrument in self.instruments:
            return instrument

        known = ", ".join(repr(alias) for alias in self.instruments)
        raise ValidationError(f"Unknown instrument {instrument!r}. Your instruments are: {known}")

    def resolve_instrument(self, instrument_alias: "str | Instrument") -> Instrument:
        """Returns the Instrument matching a given instrument alias."""
        if isinstance(instrument_alias, Instrument):
            instrument = instrument_alias
            if instrument in self.instruments.values():
                return instrument

            raise ValidationError(f"{instrument} is not in your instruments")

        if instrument_alias in self.instruments:
            return self.instruments[instrument_alias]

        known = ", ".join(repr(alias) for alias in self.instruments)
        raise ValidationError(f"Unknown instrument {instrument_alias!r}. Your instruments are: {known}")

    def indicator_columns(self) -> dict[str, dict[str, str]]:
        """{indicator key: {output: column name}} for every indicator."""
        return {key: indicator.columns(key) for key, indicator in self.indicators.items()}

    def to_dict(self) -> dict[str, Any]:
        """The manifest sent to Straufi: what data to prepare for this strategy."""
        return {
            "version": MANIFEST_VERSION,
            "lookback": self.lookback,
            "interval": {"minutes": self.interval // timedelta(minutes=1)},
            "frequency": self.frequency.to_dict(),
            "instruments": {name: i.to_dict() for name, i in self.instruments.items()},
            "indicators": {key: indicator.to_dict(key) for key, indicator in self.indicators.items()},
        }
