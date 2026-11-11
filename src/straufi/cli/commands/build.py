import time
from pathlib import Path

import typer

from ...lib.errors import StraufiError
from .. import ui
from ..api import StraufiClient, api
from ..local import package, project
from ..models import Build, BuildStatus

POLL_SECONDS = 2.0

_WAITING = {
    BuildStatus.QUEUED: "Waiting for a builder",
    BuildStatus.BUILDING: "Building your code",
}


def _package(found: project.Project) -> package.Package:
    """Runs the checks of the project and archives it."""
    with ui.spinner(f"Checking {found.entrypoint}"):
        warnings = project.check_project(found)
        loaded = project.load_strategy(found)

    instruments = ", ".join(str(instrument) for instrument in loaded.config.instruments.values())
    ui.success(f"Checked {found.entrypoint}, trades {instruments}")
    for warning in warnings:
        ui.warning(warning)

    with ui.spinner("Packaging"):
        files = package.collect_files(found)
        packaged = package.build_package(found, files)
    ui.success(f"Packaged {len(files)} files ({ui.format_size(len(packaged.data))})")

    if secrets := package.secret_files(found, files):
        ui.warning(f"These files look like secrets: {', '.join(secrets)}. Add them to .gitignore to leave them out.")
    return packaged


def _find_same_build(client: StraufiClient, found: project.Project, packaged: package.Package) -> Build | None:
    """A build of the exact same sources, which we don't need to make again."""
    for build in client.list_builds(found.strategy_id, BuildStatus.AVAILABLE):
        if build.get("uploadChecksum") == packaged.sha256 and build.get("pythonVersion") == project.python_version():
            return build
    return None


def _wait_for_build(client: StraufiClient, current: Build) -> Build:
    started = time.monotonic()
    try:
        with ui.spinner("Waiting for a builder") as update:
            while current["status"] in _WAITING:
                elapsed = ui.format_duration(time.monotonic() - started)
                update(f"{_WAITING[current['status']]} ({elapsed})")
                time.sleep(POLL_SECONDS)
                current = client.get_build(current["id"])
    except KeyboardInterrupt:
        client.cancel_build(current["id"])
        ui.warning(f"Canceled build {current['id']}")
        raise typer.Exit(130) from None

    if current["status"] != BuildStatus.AVAILABLE:
        reason = current.get("failureMessage") or current.get("failureReason") or current["status"]
        raise StraufiError(f"Build {current['id']} failed: {reason}")

    ui.success(f"Built {current['id']} in {ui.format_duration(time.monotonic() - started)}")
    return current


def run(path: Path, dry_run: bool) -> None:
    found = project.find_project(path)
    packaged = _package(found)
    if dry_run:
        for file in packaged.files:
            ui.info(f"  {file}")
        return

    client = StraufiClient()
    with ui.spinner("Looking for an existing build"):
        existing = _find_same_build(client, found, packaged)
    if existing is not None:
        ui.success(f"Nothing changed since build {existing['id']}")
        return

    with ui.spinner("Uploading"):
        created = client.create_build(found.strategy_id)
        api.upload(created["uploadUrl"], created["uploadHeaders"], packaged.data)
        committed = client.commit_build(
            created["build"]["id"],
            project.manifest(found),
            packaged.sha256,
            len(packaged.data),
            project.python_version(),
        )
    ui.success(f"Uploaded {ui.format_size(len(packaged.data))}")
    _wait_for_build(client, committed)
