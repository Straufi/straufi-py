import re
from importlib import resources
from pathlib import Path
from string import Template

import typer

from ... import __version__
from ...lib.errors import StraufiError
from .. import ui
from ..api.client import StrategyMode, StraufiClient
from ..local import environment


def _get_project_name(directory: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", directory.lower()).strip("-") or "strategy"


def _get_class_name(directory: str) -> str:
    name = "".join(word.capitalize() for word in re.split(r"[^A-Za-z0-9]+", directory) if word)
    if not name or name[0].isdigit():
        name = "Strategy" + name
    return name


def run(
    path: Path,
    name: str | None = None,
    mode: StrategyMode = StrategyMode.PAPER,
    install: bool = True,
) -> None:
    path = path.resolve()
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise StraufiError(f"{path} already exists and is not empty")

    with ui.spinner("Creating the strategy"):
        strategy = StraufiClient().create_strategy(name or path.name, mode)

    variables = {
        "project_name": _get_project_name(path.name),
        "class_name": _get_class_name(path.name),
        "strategy_id": strategy["id"],
        "straufi_version": __version__,
    }
    templates = resources.files(__package__) / ".." / "templates"
    path.mkdir(parents=True, exist_ok=True)
    for template, target in [
        ("pyproject.toml.tmpl", "pyproject.toml"),
        ("README.md.tmpl", "README.md"),
        ("strategy.py.tmpl", "strategy.py"),
        ("gitignore.tmpl", ".gitignore"),
    ]:
        content = Template((templates / template).read_text()).substitute(variables)
        (path / target).write_text(content)

    ui.success(f"Created strategy {strategy['displayName']} ({mode}) in {path}")

    run = "straufi"
    if install:
        manager = environment.detect_manager()
        try:
            with ui.spinner(f"Installing the dependencies with {manager}"):
                environment.create(path, manager)
        except environment.SetupError as e:
            ui.error(str(e))
            ui.info("The project was created, but you need to install its dependencies yourself.")
            raise typer.Exit(1) from None

        ui.success("Created the virtual environment in .venv")
        run = environment.run_hint(manager)

    ui.info("\nNext steps:")
    ui.info(f"  cd {path.name}")
    ui.info("  Edit strategy.py")
    ui.info(f"  {run} build")
    ui.info(f"  {run} backtest")
