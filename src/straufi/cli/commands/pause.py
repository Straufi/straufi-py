from pathlib import Path

from .. import ui
from ..api.client import StraufiClient
from ..local import project


def run(path: Path) -> None:
    found = project.find_project(path)
    StraufiClient().set_active(found.strategy_id, False)
    ui.success("Paused the strategy.")
