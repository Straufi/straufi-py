from collections.abc import Callable, Generator, Iterable, Mapping
from contextlib import contextmanager
from datetime import datetime

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

console = Console(highlight=False)
errors = Console(stderr=True, highlight=False)
_ID_WIDTH = 36


def success(message: str) -> None:
    console.print(f"[green]✓[/green] {escape(message)}", soft_wrap=True)


def info(message: str) -> None:
    console.print(escape(message), soft_wrap=True)


def warning(message: str) -> None:
    errors.print(f"[yellow]![/yellow] {escape(message)}", soft_wrap=True)


def error(message: str) -> None:
    errors.print(f"[red]✗[/red] {escape(message)}", soft_wrap=True)


@contextmanager
def spinner(message: str) -> Generator[Callable[[str], None]]:
    """Shows a spinner until the block ends. It gets a function to change the message."""
    with console.status(escape(message)) as status:
        yield lambda text: status.update(escape(text))


def details(rows: Mapping[str, str]) -> None:
    """Shows labelled values, one per line."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim")
    grid.add_column()
    for label, value in rows.items():
        grid.add_row(label, escape(value))
    console.print(grid)


def table(columns: Iterable[str], rows: Iterable[Iterable[str]]) -> None:
    """Shows a table whose first column holds IDs, which must stay whole to be copied."""
    result = Table(box=box.SIMPLE_HEAD, pad_edge=False)
    first, *others = columns
    result.add_column(first, no_wrap=True, min_width=_ID_WIDTH)
    for column in others:
        result.add_column(column, overflow="fold")
    for row in rows:
        result.add_row(*(escape(cell) for cell in row))
    console.print(result)


def format_time(value: str | None) -> str:
    """An ISO 8601 date from the API, in the local timezone."""
    if not value:
        return "-"
    return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")


def format_duration(seconds: float) -> str:
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes}m {seconds}s" if minutes else f"{seconds}s"


def format_size(size: int) -> str:
    return f"{size / 1024 / 1024:.1f} MB" if size >= 1024 * 1024 else f"{max(1, size // 1024)} KB"


def format_budget(budget: Mapping[str, Mapping[str, float]]) -> str:
    brokers = [
        f"{broker}: " + ", ".join(f"{amount:g} {asset}" for asset, amount in assets.items())
        for broker, assets in budget.items()
    ]
    return "; ".join(brokers) or "none"
