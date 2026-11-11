from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .lib import checks, durations
from .lib.errors import ValidationError


@dataclass(frozen=True)
class Frequency:
    """Base class of every frequency. Use one of its subclasses, like `Every("15min")`."""

    @staticmethod
    def parse(value: object) -> "Frequency":
        """Accepts a Frequency, or a text like "15min" as a shorthand for `Every("15min")`."""
        if isinstance(value, Frequency):
            return value
        if isinstance(value, str):
            return Every(value)
        if isinstance(value, type) and issubclass(value, Frequency):
            raise ValidationError(
                f'frequency should be instantiated. Did you forget the parentheses? e.g. {value.__name__}("15min")'
            )
        raise ValidationError(f'frequency must be like Every("15min") or Every(hours=1), got {value!r}')

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, init=False, repr=False)
class Every(Frequency):
    """Runs your strategy at a recurring schedule, like `Every("15min")` or `Every(hours=1)`.

    The schedule is a text like "15min" or "1h", a timedelta, or keyword arguments like `Every(hours=1)`. It is 5,
    10, 15, 20 or 30 minutes, or 1, 2, 3, 4, 6, 12 or 24 hours.

    >>> Every("15min") == Every(minutes=15)
    True
    >>> Every("2h").minutes
    120
    """

    minutes: int
    """The interval, in minutes."""

    def __init__(self, interval: str | timedelta | None = None, /, *, hours: int = 0, minutes: int = 0) -> None:
        if interval is not None:
            if hours or minutes:
                raise ValidationError('Every takes either an interval or hours/minutes, not both: Every("1h")')
            total = durations.to_minutes(interval, "Every")
        else:
            total = durations.from_parts(
                checks.non_negative_int(hours, "Every hours"),
                checks.non_negative_int(minutes, "Every minutes"),
                "Every",
            )

        object.__setattr__(self, "minutes", total)

    def __repr__(self) -> str:
        return f"Every({durations.format_minutes(self.minutes)!r})"

    def to_dict(self) -> dict[str, Any]:
        return {"type": "every", "minutes": self.minutes}
