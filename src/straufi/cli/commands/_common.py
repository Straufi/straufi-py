import webbrowser
from datetime import UTC, datetime

from .. import ui
from ..api import get_webapp_url
from ..local import project
from ..models import Strategy


def open_webapp(found: project.Project, page: str) -> None:
    """Opens a page of the strategy on the webapp, or shows its URL when no browser could open it."""
    url = f"{get_webapp_url()}/strategies/{found.strategy_id}/{page}"
    if webbrowser.open(url):
        ui.success(f"Opened {url}")
    else:
        ui.info(f"Open this page in your browser: {url}")


def get_next_run(strategy: Strategy) -> str:
    now = datetime.now(UTC)
    dates = [date for date in strategy["recurrenceDates"] if datetime.fromisoformat(date) > now]
    return ui.format_time(min(dates, default=None))
