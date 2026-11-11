import gzip
import hashlib
import io
import os
import tarfile

import pytest

from straufi.cli.local.package import MAX_SOURCE_FILES, build_package, collect_files, secret_files
from straufi.cli.local.project import Project, ProjectError


def make_project(path) -> Project:
    (path / "strategy.py").write_text("code")
    return Project(path=path, entrypoint="strategy:Moon", strategy_id="id", pyproject={})


def names(project: Project) -> list[str]:
    return [p.relative_to(project.path).as_posix() for p in collect_files(project)]


def test_leaves_out_environments_caches_and_secrets(tmp_path):
    project = make_project(tmp_path)
    for name in (".env", ".env.local", "module.pyc", "native.pyd", ".DS_Store", ".venv/lib.py", "__pycache__/a.pyc"):
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).write_text("x")
    (tmp_path / "some-env").mkdir()
    (tmp_path / "some-env" / "pyvenv.cfg").write_text("x")
    (tmp_path / "some-env" / "lib.py").write_text("x")

    assert names(project) == ["strategy.py"]


def test_follows_gitignore_files_at_every_level(tmp_path):
    project = make_project(tmp_path)
    (tmp_path / ".gitignore").write_text("*.parquet\ndata/\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "candles.csv").write_text("x")
    (tmp_path / "prices.parquet").write_text("x")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / ".gitignore").write_text("local.py\n")
    (tmp_path / "pkg" / "local.py").write_text("x")
    (tmp_path / "pkg" / "kept.py").write_text("x")
    (tmp_path / "local.py").write_text("x")

    assert names(project) == [".gitignore", "local.py", "pkg/.gitignore", "pkg/kept.py", "strategy.py"]


def test_refuses_symbolic_links(tmp_path):
    project = make_project(tmp_path)
    (tmp_path / "link.py").symlink_to("/etc/hosts")

    with pytest.raises(ProjectError, match=r"link\.py is a symbolic link"):
        collect_files(project)


def test_ignored_symbolic_links_are_fine(tmp_path):
    project = make_project(tmp_path)
    (tmp_path / ".gitignore").write_text("link.py\n")
    (tmp_path / "link.py").symlink_to("/etc/hosts")

    assert names(project) == [".gitignore", "strategy.py"]


def test_refuses_too_many_files(tmp_path):
    project = make_project(tmp_path)
    for index in range(MAX_SOURCE_FILES):
        (tmp_path / f"{index}.py").touch()

    with pytest.raises(ProjectError, match="the maximum is 5000"):
        collect_files(project)


def test_refuses_a_project_too_big_once_compressed(tmp_path):
    project = make_project(tmp_path)
    (tmp_path / "data.bin").write_bytes(os.urandom(21 * 1024 * 1024))

    with pytest.raises(ProjectError, match="once compressed"):
        build_package(project, collect_files(project))


def test_finds_files_that_look_like_secrets(tmp_path):
    project = make_project(tmp_path)
    (tmp_path / "private.pem").write_text("x")
    (tmp_path / "credentials.json").write_text("x")

    assert secret_files(project, collect_files(project)) == ["credentials.json", "private.pem"]


def test_the_same_sources_give_the_same_archive(tmp_path):
    project = make_project(tmp_path)
    first = build_package(project, collect_files(project))

    os.utime(tmp_path / "strategy.py", (1, 1))
    second = build_package(project, collect_files(project))

    assert first.sha256 == second.sha256 == hashlib.sha256(first.data).hexdigest()
    assert gzip.decompress(first.data)[:11] == b"strategy.py"


def test_archives_have_no_metadata_of_the_machine(tmp_path):
    project = make_project(tmp_path)
    script = tmp_path / "run.sh"
    script.write_text("x")
    script.chmod(0o775)

    package = build_package(project, collect_files(project))

    with tarfile.open(fileobj=io.BytesIO(package.data)) as archive:
        members = {member.name: member for member in archive.getmembers()}
        assert archive.extractfile("strategy.py").read() == b"code"  # pyright: ignore[reportOptionalMemberAccess]

    assert package.files == ["run.sh", "strategy.py"]
    assert (members["run.sh"].mode, members["strategy.py"].mode) == (0o755, 0o644)
    assert all((m.mtime, m.uid, m.gid, m.uname, m.gname) == (0, 0, 0, "", "") for m in members.values())
