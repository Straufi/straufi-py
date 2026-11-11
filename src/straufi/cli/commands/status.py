from pathlib import Path

from .. import ui
from ..api.client import StraufiClient
from ..local import project
from ._common import get_next_run


def run(path: Path) -> None:
    """Show the strategy: what it runs, when, and how it went."""
    client = StraufiClient()
    found = project.find_project(path)
    strategy = client.get_strategy(found.strategy_id)
    instruments = [f"{i['base']}/{i['quote']} on {i['broker']}" for i in strategy["instruments"]]

    ui.details(
        {
            "Strategy": f"{strategy['displayName']} ({strategy['mode']})",
            "ID": strategy["id"],
            "State": "active" if strategy["isActive"] else "paused",
            "Build": strategy.get("activeBuildId", "none, run `straufi deploy`"),
            "Instruments": ", ".join(instruments) or "-",
            "Budget": ui.format_budget(strategy["baseBudget"]),
            "Next run": get_next_run(strategy) if strategy["isActive"] else "-",
        }
    )

    executions = client.list_executions(found.strategy_id)
    if executions:
        ui.info("")
        ui.table(
            ["Execution", "Time", "Status", "Reason"],
            [
                [item["id"], ui.format_time(item["executionTime"]), item["status"], item.get("failureReason", "")]
                for item in executions
            ],
        )
