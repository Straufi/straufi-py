import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import tomlkit

from ...lib.errors import StraufiError

MANAGERS = ("uv", "poetry", "pip")


class SetupError(StraufiError):
    pass


@dataclass(frozen=True)
class Step:
    description: str
    command: Sequence[str]


def _get_env_vars() -> dict[str, str]:
    # If straufi runs from an activated virtual environment, Poetry would install into it
    # instead of creating the project's own, and uv would warn about it.
    return {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "CONDA_PREFIX")}


def detect_manager() -> str:
    """Finds the first package manager available (runs --version) in order of preference: uv, poetry, pip."""
    for manager in ("uv", "poetry"):
        if executable := shutil.which(manager):
            try:
                result = subprocess.run([executable, "--version"], env=_get_env_vars(), capture_output=True, timeout=30)
                if result.returncode == 0:
                    return manager
            except (OSError, subprocess.TimeoutExpired):
                pass

    return "pip"


def run_hint(manager: str) -> str:
    """How to run the `straufi` command of the project in the venv."""
    if manager == "pip":
        activate = r".venv\Scripts\activate" if sys.platform == "win32" else "source .venv/bin/activate"
        return f"{activate} && straufi"
    return f"{manager} run straufi"


def _get_steps_for_project(project: Path, manager: str) -> list[Step]:
    if manager == "uv":
        return [Step("install the dependencies with uv", ["uv", "sync"])]

    if manager == "poetry":
        return [
            Step("configure Poetry", ["poetry", "config", "virtualenvs.in-project", "true", "--local"]),
            Step("install the dependencies with Poetry", ["poetry", "install", "--with", "dev"]),
        ]

    if manager == "pip":
        python = project / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

        pyproject = tomllib.loads((project / "pyproject.toml").read_text())
        requirements = [*pyproject["project"]["dependencies"], *pyproject.get("dependency-groups", {}).get("dev", [])]

        return [
            Step("create the virtual environment", [sys.executable, "-m", "venv", ".venv"]),
            Step("install the dependencies with pip", [str(python), "-m", "pip", "install", *requirements]),
        ]

    raise ValueError(f"Unknown package manager {manager!r}")


def _prepare_for_poetry(project: Path) -> None:
    """A strategy isn't an installable package: tell Poetry to only install its dependencies."""
    path = project / "pyproject.toml"
    document = tomlkit.parse(path.read_text())
    tool = document["tool"]
    poetry = tomlkit.table()
    poetry["package-mode"] = False
    tool["poetry"] = poetry  # pyright: ignore[index]
    path.write_text(tomlkit.dumps(document))


def create(project: Path, manager: str) -> None:
    """Create venv and install the dependencies."""
    project = project.resolve()
    if manager == "poetry":
        _prepare_for_poetry(project)

    for step in _get_steps_for_project(project, manager):
        try:
            result = subprocess.run(step.command, cwd=project, env=_get_env_vars(), capture_output=True, text=True)
        except OSError as e:
            raise SetupError(f"Could not {step.description}: {e}") from None

        if result.returncode != 0:
            output = (result.stderr or result.stdout).strip()
            raise SetupError(f"Could not {step.description} ({' '.join(step.command)}):\n{output}")
