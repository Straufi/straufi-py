import math
import numbers
from datetime import UTC, datetime

from .errors import ValidationError


def text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty text, got {value!r}")
    return value.strip()


def positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral) or value <= 0:
        raise ValidationError(f"{field} must be a whole number greater than 0, got {value!r}")
    return int(value)


def non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral) or value < 0:
        raise ValidationError(f"{field} must be a whole number greater than or equal to 0, got {value!r}")
    return int(value)


def number(value: object, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValidationError(f"{field} must be a number, got {value!r}")

    result = float(value)
    if math.isnan(result):
        raise ValidationError(
            f"{field} is NaN (not a number). This often happens when an indicator "
            "doesn't have enough data yet: check your values before using them."
        )
    if math.isinf(result):
        raise ValidationError(f"{field} must be a finite number, got {result}")
    if positive and result <= 0:
        raise ValidationError(f"{field} must be greater than 0, got {result}")

    return result


def optional_number(value: object, field: str, *, positive: bool = False) -> float | None:
    return None if value is None else number(value, field, positive=positive)


def optional_datetime(value: object, field: str) -> datetime | None:
    """Accepts a datetime or an ISO 8601 string. Always returns UTC."""
    if value is None:
        return None

    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value)
        except ValueError:
            raise ValidationError(f"{field} must be an ISO 8601 date, got {value!r}") from None
    else:
        raise ValidationError(f"{field} must be an ISO 8601 date, got {value!r}")

    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)
