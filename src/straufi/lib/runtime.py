"""Internal module used by the Straufi runner to run strategies.

It must stay small and backward compatible so it works with all versions of straufi that the user may have.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from ..config import Config
from ..instrument import Budget
from ..order import Order
from ..strategy import Strategy
from .errors import ValidationError

if TYPE_CHECKING:
    import pandas as pd


API_VERSION = 1


class RunMode(StrEnum):
    LIVE = "live"
    PAPER = "paper"
    BACKTEST = "backtest"


@dataclass
class RunContext:
    config: Config
    data: "pd.DataFrame"
    budgets: Sequence[Budget]
    positions: Sequence[Order]
    execution_time: datetime
    mode: RunMode
    orders: list[Order] = field(default_factory=list)
    cancellations: list[Order] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.execution_time, datetime) or self.execution_time.tzinfo is None:
            raise ValidationError(f"execution_time must be a datetime with a timezone, got {self.execution_time!r}")
        self.execution_time = self.execution_time.astimezone(UTC)

        try:
            self.mode = RunMode(self.mode)
        except ValueError:
            raise ValidationError(f"mode must be one of {', '.join(RunMode)}, got {self.mode!r}") from None


def load_config(strategy: Strategy) -> Config:
    """Check that a strategy is complete, then return its config."""
    name = type(strategy).__name__
    if type(strategy).run is Strategy.run:
        raise ValidationError(f"{name} must define a run() method")
    if type(strategy).config is Strategy.config:
        raise ValidationError(f"{name} must define a @staticmethod config() method")

    config = strategy.config
    if callable(config):
        config = config()
    if not isinstance(config, Config):
        raise ValidationError(f"{name}.config() must return a Config(...), got {config!r}")
    return config


def bind(strategy: Strategy, context: RunContext) -> None:
    strategy._context = context


def run_strategy(strategy: Strategy, context: RunContext) -> None:
    """Run a strategy. The results are then in `context.orders` and `context.cancellations`."""
    context.orders = []
    context.cancellations = []
    strategy.run()
