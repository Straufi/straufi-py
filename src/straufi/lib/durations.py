import re
from datetime import timedelta

from .errors import ValidationError

MINUTES = (5, 10, 15, 20, 30)
HOURS = (1, 2, 3, 4, 6, 12, 24)

ALLOWED_MINUTES = {*MINUTES, *(hours * 60 for hours in HOURS)}
ALLOWED_HELP_STRING = f"{', '.join(map(str, MINUTES))} minutes or {', '.join(map(str, HOURS))} hours"
DURATION_REGEX = re.compile(r"(?P<amount>\d+)\s*(?:(?P<hours>h|hr|hrs|hour|hours)|m|min|mins|minute|minutes)")


def to_minutes(value: object, field: str) -> int:
    """A text like "15min" or "1h", or a timedelta, in minutes."""
    if isinstance(value, timedelta):
        minutes, rest = divmod(value, timedelta(minutes=1))
        if rest or minutes not in ALLOWED_MINUTES:
            raise ValidationError(f"{field} must be one of {ALLOWED_HELP_STRING}, got {value}")
        return minutes

    if not isinstance(value, str):
        raise ValidationError(f'{field} must be a text like "15min" or "1h", or a timedelta, got {value!r}')

    match = DURATION_REGEX.fullmatch(value.strip().lower())
    if match is None:
        raise ValidationError(f'{field} must be like "15min" or "1h", got {value!r}')

    amount = int(match["amount"])
    return from_parts(amount, 0, field) if match["hours"] else from_parts(0, amount, field)


def from_parts(hours: int, minutes: int, field: str) -> int:
    """Either a number of hours or a number of minutes, in minutes."""
    if hours and minutes:
        raise ValidationError(f"{field} takes hours or minutes, not both")
    if hours in HOURS:
        return hours * 60
    if minutes in MINUTES:
        return minutes
    raise ValidationError(
        f"{field} must be one of {ALLOWED_HELP_STRING}, got {f'{hours}h' if hours else f'{minutes}min'}"
    )


def format_minutes(minutes: int) -> str:
    return f"{minutes // 60}h" if minutes % 60 == 0 else f"{minutes}min"
