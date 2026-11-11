from pathlib import Path
from typing import Annotated

import typer
from typer.core import TyperGroup

from ..lib.errors import StraufiError
from . import commands, ui
from .api.client import StrategyMode


class RootGroup(TyperGroup):
    def invoke(self, ctx):
        """Shows our errors as a clean message instead of a Python traceback."""
        try:
            return super().invoke(ctx)
        except StraufiError as e:
            ui.error(str(e))
            raise typer.Exit(1) from None


app = typer.Typer(
    cls=RootGroup,
    help="Create, backtest and deploy Straufi trading strategies.",
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

ProjectOption = Annotated[Path, typer.Option("--project", "-p", help="The strategy project directory.")]


def main() -> None:
    app()


def _version_cb(value: bool) -> None:
    if value:
        from .. import __version__

        ui.info(f"straufi {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool, typer.Option("--version", "-v", callback=_version_cb, is_eager=True, help="Show the version and exit.")
    ] = False,
) -> None:
    pass


@app.command()
def login(
    browser: Annotated[
        bool, typer.Option(help="Open the login page in your browser. With --no-browser, only print its URL.")
    ] = True,
) -> None:
    """Log in to Straufi.

    In CI, set the STRAUFI_TOKEN environment variable instead.
    """
    commands.login.run(browser)


@app.command()
def logout() -> None:
    """Log out of Straufi."""
    commands.logout.run()


@app.command()
def init(
    path: Annotated[Path, typer.Argument(help="Directory of the new project, e.g. my-strategy.")],
    name: Annotated[str | None, typer.Option(help="Name of the strategy. Defaults to the directory's.")] = None,
    mode: Annotated[StrategyMode, typer.Option(help="Trade with fake money (paper) or real money (live).")] = (
        StrategyMode.PAPER
    ),
    install: Annotated[
        bool, typer.Option(help="Create a virtual environment and install the dependencies (uv, Poetry or pip).")
    ] = True,
) -> None:
    """Create a new strategy on Straufi."""
    commands.init.run(path, name, mode, install)


@app.command()
def build(
    path: ProjectOption = Path("."),
    dry_run: Annotated[bool, typer.Option(help="Only perform the pre-checks without creating a build.")] = False,
) -> None:
    """Package and build your project to be used on Straufi by backtests or live run."""
    commands.build.run(path, dry_run)


@app.command()
def backtest(path: ProjectOption = Path(".")) -> None:
    """Open the page to test a build of the strategy on past data, in your browser."""
    commands.backtest.run(path)


@app.command()
def deploy(path: ProjectOption = Path(".")) -> None:
    """Open the page to deploy a build of the strategy, in your browser."""
    commands.deploy.run(path)


@app.command()
def pause(path: ProjectOption = Path(".")) -> None:
    """Stop running the strategy. Its open orders stay open."""
    commands.pause.run(path)


@app.command()
def resume(path: ProjectOption = Path(".")) -> None:
    """Start running the strategy again."""
    commands.resume.run(path)


@app.command()
def status(path: ProjectOption = Path(".")) -> None:
    """Show the current informations of the strategy."""
    commands.status.run(path)
