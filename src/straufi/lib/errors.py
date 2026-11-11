class StraufiError(Exception):
    """Base class for every error raised by straufi."""


class ValidationError(StraufiError, ValueError):
    """Something you built (a Config, an Order, an Instrument, an indicator...) is invalid."""


class NotRunningError(StraufiError, RuntimeError):
    """A method that needs live data was called outside of a strategy run."""
