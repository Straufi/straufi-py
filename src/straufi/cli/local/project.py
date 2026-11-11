import importlib
import re
import subprocess
import sys
import tomllib
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...config import Config
from ...lib import runtime
from ...lib.errors import StraufiError
from ...strategy import Strategy

_ENTRYPOINT = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")
_STRAUFI_DEPENDENCY = re.compile(r"\s*straufi(?![\w.-])", re.IGNORECASE)
LOCKFILES = ("uv.lock", "poetry.lock", "pylock.toml", "requirements.txt")
"""In the order the builder looks for them."""
SUPPORTED_PYTHON_VERSIONS = ("3.12", "3.13", "3.14")


class ProjectError(StraufiError):
    pass


@dataclass
class Project:
    path: Path
    entrypoint: str
    strategy_id: str
    pyproject: dict[str, Any]

    @property
    def lockfile(self) -> str | None:
        return next((name for name in LOCKFILES if (self.path / name).is_file()), None)


@dataclass
class LoadedStrategy:
    strategy_class: type[Strategy]
    config: Config


def _user_traceback(error: BaseException) -> str:
    """The traceback without the frames of straufi and importlib, which are noise to the user."""
    noise = ("<frozen importlib", str(Path(__file__).resolve().parents[1]), str(Path(importlib.__file__).parent))
    frames = [frame for frame in traceback.extract_tb(error.__traceback__) if not frame.filename.startswith(noise)]
    lines = traceback.format_list(frames) + traceback.format_exception_only(error)
    return "".join(lines).rstrip()


def find_project(path: Path) -> Project:
    """Find the project containing `path` (looking at parent directories too)."""
    path = path.resolve()
    for directory in [path, *path.parents]:
        if (directory / "pyproject.toml").is_file():
            break
    else:
        raise ProjectError(f"No pyproject.toml found in {path} or its parents. Create a project with `straufi init`.")

    # Load and validate pyproject.toml
    try:
        pyproject = tomllib.loads((directory / "pyproject.toml").read_text())
    except tomllib.TOMLDecodeError as e:
        raise ProjectError(f"{directory / 'pyproject.toml'} is not valid TOML: {e}") from None

    # Load [tool.straufi] section
    settings = pyproject.get("tool", {}).get("straufi")
    if not isinstance(settings, dict):
        raise ProjectError(f"{directory / 'pyproject.toml'} has no [tool.straufi] section")

    # Validate [tool.straufi].entrypoint
    entrypoint = settings.get("entrypoint")
    if not isinstance(entrypoint, str) or not _ENTRYPOINT.match(entrypoint):
        raise ProjectError(
            f'[tool.straufi] entrypoint must look like "strategy:MyStrategy" (file:class), got {entrypoint!r}'
        )

    strategy_id = settings.get("id")
    if not isinstance(strategy_id, str) or not strategy_id:
        raise ProjectError(
            f"[tool.straufi] in {directory / 'pyproject.toml'} has no id, so this project has no strategy on Straufi. "
            "Create a project with `straufi init`."
        )

    return Project(path=directory, entrypoint=entrypoint, strategy_id=strategy_id, pyproject=pyproject)


def python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def check_project(project: Project) -> list[str]:
    """Raises what would fail the build, and returns warnings. The strategy itself is checked by `load_strategy`."""
    if python_version() not in SUPPORTED_PYTHON_VERSIONS:
        raise ProjectError(
            f"Straufi runs Python {', '.join(SUPPORTED_PYTHON_VERSIONS)}, but this project uses {python_version()}."
        )

    if not _declares_straufi(project):
        raise ProjectError("straufi is not in the dependencies of your project: add it to pyproject.toml.")

    if project.lockfile is None:
        return [
            f"No lockfile ({', '.join(LOCKFILES)}): each build may install different versions of your dependencies."
        ]
    return []


def _declares_straufi(project: Project) -> bool:
    dependencies = [
        *project.pyproject.get("project", {}).get("dependencies", []),
        *project.pyproject.get("tool", {}).get("poetry", {}).get("dependencies", {}),
    ]
    requirements = project.path / "requirements.txt"
    if requirements.is_file():
        dependencies += requirements.read_text().splitlines()
    return any(_STRAUFI_DEPENDENCY.match(dependency) for dependency in dependencies)


def load_strategy(project: Project) -> LoadedStrategy:
    """Import the strategy and check its config, like Straufi will."""
    module_name, class_name = project.entrypoint.split(":")

    # Try to resolve the module from the entrypoint, in the directories the runner looks in
    directories = [str(project.path), str(project.path / "src")]
    try:
        sys.path[:0] = directories
        for name in [m for m in sys.modules if m == module_name or m.startswith(module_name + ".")]:
            del sys.modules[name]
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        if e.name == module_name.split(".")[0]:
            raise ProjectError(f"Can't find {module_name.replace('.', '/')}.py in {project.path}") from None
        raise ProjectError(f"Error while loading {module_name}:\n{_user_traceback(e)}") from None
    except Exception as e:
        raise ProjectError(f"Error while loading {module_name}:\n{_user_traceback(e)}") from None
    finally:
        for directory in directories:
            sys.path.remove(directory)

    # Try to resolve the class within the module
    strategy_class = getattr(module, class_name, None)
    if strategy_class is None:
        raise ProjectError(f"There is no class {class_name} in {module_name}")
    if not (isinstance(strategy_class, type) and issubclass(strategy_class, Strategy)):
        raise ProjectError(f"{class_name} must be a subclass of straufi.Strategy")

    try:
        config = runtime.load_config(strategy_class())
    except StraufiError:
        raise
    except Exception as e:
        raise ProjectError(f"Error while loading the config of {class_name}:\n{_user_traceback(e)}") from None

    return LoadedStrategy(strategy_class=strategy_class, config=config)


def _run_git(project: Project, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=project.path, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def manifest(project: Project) -> dict[str, Any]:
    """What we tell Straufi about the build, to show it later. The build's real manifest comes from its image."""
    from ... import __version__

    result: dict[str, Any] = {"entrypoint": project.entrypoint, "straufi_version": __version__}
    if project.lockfile:
        result["lockfile"] = project.lockfile

    if commit := _run_git(project, "rev-parse", "HEAD"):
        result["git_commit"] = commit
        result["git_dirty"] = bool(_run_git(project, "status", "--porcelain"))
    return result
