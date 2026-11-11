from pathlib import Path

from ..local import project
from ._common import open_webapp


def run(path: Path) -> None:
    open_webapp(project.find_project(path), "builds/deploy")
