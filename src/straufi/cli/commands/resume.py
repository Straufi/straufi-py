from pathlib import Path

from .. import ui
from ..api.client import StraufiClient
from ..local import project
from ._common import get_next_run


def run(path: Path) -> None:
    found = project.find_project(path)
    strategy = StraufiClient().set_active(found.strategy_id, True)
    ui.success(f"Resumed the strategy, next run at {get_next_run(strategy)}")
