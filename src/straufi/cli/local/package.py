"""Packaging a project: which files go to Straufi, in a reproducible tarball."""

import gzip
import hashlib
import io
import os
import tarfile
from collections.abc import Iterator
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from pathspec import GitIgnoreSpec

from .project import Project, ProjectError

EXCLUDED_DIRS = {
    ".git", ".hg", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".idea", ".vscode", "node_modules", "dist", "build", ".ipynb_checkpoints",
}  # fmt: skip
EXCLUDED_FILES = {".DS_Store"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".pyd"}
SECRET_PATTERNS = ("*.pem", "*.key", "credentials*", "id_rsa*", "*.p12")

MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_SOURCE_BYTES = 200 * 1024 * 1024
MAX_SOURCE_FILES = 5000

Ignores = tuple[tuple[Path, GitIgnoreSpec], ...]


@dataclass
class Package:
    files: list[str]
    data: bytes
    sha256: str


def _is_ignored(path: Path, ignores: Ignores) -> bool:
    suffix = "/" if path.is_dir() else ""
    return any(spec.match_file(path.relative_to(root).as_posix() + suffix) for root, spec in ignores)


def _is_excluded(path: Path) -> bool:
    if path.is_dir():
        return path.name in EXCLUDED_DIRS or (path / "pyvenv.cfg").exists()
    return path.name in EXCLUDED_FILES or path.suffix in EXCLUDED_SUFFIXES or path.name.startswith(".env")


def _traverse_directory(directory: Path, root: Path, ignores: Ignores) -> Iterator[Path]:
    if (gitignore := directory / ".gitignore").is_file():
        ignores = (*ignores, (directory, GitIgnoreSpec.from_lines(gitignore.read_text().splitlines())))

    for path in sorted(directory.iterdir()):
        if _is_excluded(path) or _is_ignored(path, ignores):
            continue
        if path.is_symlink():
            raise ProjectError(f"{path.relative_to(root)} is a symbolic link, which Straufi can't package.")
        if path.is_dir():
            yield from _traverse_directory(path, root, ignores)
        elif path.is_file():
            yield path


def collect_files(project: Project) -> list[Path]:
    """The files of the project, sorted, without virtual environments, caches, secrets and what git ignores."""
    files = list(_traverse_directory(project.path, project.path, ()))
    if len(files) > MAX_SOURCE_FILES:
        raise ProjectError(f"Your project has {len(files)} files, the maximum is {MAX_SOURCE_FILES}.")

    if sum(path.stat().st_size for path in files) > MAX_SOURCE_BYTES:
        raise ProjectError(
            f"Your project is bigger than {MAX_SOURCE_BYTES // 1024 // 1024} MB. "
            "Remove data files or other large files from it, or add them to .gitignore."
        )
    return files


def secret_files(project: Project, files: list[Path]) -> list[str]:
    """The files that look like secrets."""
    return [
        path.relative_to(project.path).as_posix()
        for path in files
        if any(fnmatch(path.name, pattern) for pattern in SECRET_PATTERNS)
    ]


def _tar_info(path: Path, name: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = path.stat().st_size
    info.mode = 0o755 if os.access(path, os.X_OK) else 0o644
    return info


def build_package(project: Project, files: list[Path]) -> Package:
    buffer = io.BytesIO()
    # GzipFile, as tarfile's gzip mode writes the current time in the gzip header.
    with (
        gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        for path in files:
            with path.open("rb") as content:
                archive.addfile(_tar_info(path, path.relative_to(project.path).as_posix()), content)

    data = buffer.getvalue()
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ProjectError(
            f"Your project is {len(data) // 1024 // 1024} MB once compressed, the maximum is "
            f"{MAX_ARCHIVE_BYTES // 1024 // 1024} MB. Remove data files or other large files from it, or add them to "
            ".gitignore."
        )
    names = [path.relative_to(project.path).as_posix() for path in files]
    return Package(files=names, data=data, sha256=hashlib.sha256(data).hexdigest())
