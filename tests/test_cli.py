import hashlib
import json
import re
import subprocess
import sys
import tomllib
from typing import Any
from unittest.mock import Mock, create_autospec

import httpx
import pytest
from typer.testing import CliRunner

import straufi.cli as cli
from straufi.cli import app, commands
from straufi.cli.api import api
from straufi.cli.api import client as api_client
from straufi.cli.api.client import StrategyMode, StraufiClient
from straufi.cli.auth import auth
from straufi.cli.commands import _common
from straufi.cli.commands import build as build_command
from straufi.cli.local import environment

runner = CliRunner()
NOW = "2026-10-01T10:00:00Z"


def strategy(**overrides: Any) -> dict[str, Any]:
    defaults = {
        "id": "strategy-1",
        "userId": "user-1",
        "displayName": "moon",
        "mode": "paper",
        "isActive": False,
        "baseBudget": {},
        "recurrenceDates": [],
        "stopIfError": True,
        "maxExecutionDelay": 60,
        "createdAt": NOW,
        "updatedAt": NOW,
        "instruments": [],
    }
    return {**defaults, **overrides}


def build(status: str = "available", **overrides: Any) -> dict[str, Any]:
    defaults = {"id": "build-1", "userId": "user-1", "strategyId": "strategy-1", "status": status, "createdAt": NOW}
    return {**defaults, **overrides}


def execution(**overrides: Any) -> dict[str, Any]:
    defaults = {
        "id": "execution-1",
        "buildId": "build-1",
        "executionTime": NOW,
        "mode": "paper",
        "status": "succeeded",
        "createdAt": NOW,
    }
    return {**defaults, **overrides}


def invoke(*args, **kwargs):
    return runner.invoke(app, [str(a) for a in args], **kwargs)


@pytest.fixture
def client(monkeypatch):
    """The API, as a stub: the tests give it their answers, and check what the CLI asked for."""
    stub = create_autospec(StraufiClient, instance=True)
    stub.create_strategy.return_value = strategy()
    stub.get_strategy.return_value = strategy()
    stub.list_builds.return_value = []
    stub.create_build.return_value = {
        "build": build("awaiting-upload"),
        "uploadUrl": "url",
        "uploadHeaders": {},
        "uploadExpiresAt": NOW,
    }
    stub.commit_build.return_value = build("queued")
    stub.get_build.return_value = build()
    # Each command imports the client on its own, so replace it wherever it's imported.
    for module in (api_client, *(getattr(commands, name) for name in commands.__all__)):
        if hasattr(module, "StraufiClient"):
            monkeypatch.setattr(module, "StraufiClient", lambda: stub)
    monkeypatch.setattr(build_command, "POLL_SECONDS", 0)
    monkeypatch.setattr(api, "upload", Mock())
    return stub


@pytest.fixture(autouse=True)
def browser(monkeypatch):
    """Never open a real browser."""
    fake = Mock(return_value=True)
    monkeypatch.setattr(_common.webbrowser, "open", fake)
    return fake


@pytest.fixture
def project(tmp_path, client):
    path = tmp_path / "moon"
    result = invoke("init", path, "--no-install")
    assert result.exit_code == 0, result.output
    return path


@pytest.mark.parametrize("flag", ["-v", "--version"])
def test_version(flag):
    assert invoke(flag).output.startswith("straufi ")


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help(flag):
    assert "Usage" in invoke(flag).output and "Usage" in invoke("build", flag).output


def test_init_creates_the_strategy_and_its_project(tmp_path, client):
    project = tmp_path / "2 moon-shot"
    result = invoke("init", project, "--no-install", "--mode", "live")
    assert result.exit_code == 0, result.output

    client.create_strategy.assert_called_once_with("2 moon-shot", "live")
    assert {p.name for p in project.iterdir()} == {"pyproject.toml", "README.md", "strategy.py", ".gitignore"}
    assert "class Strategy2MoonShot(Strategy)" in (project / "strategy.py").read_text()
    assert tomllib.loads((project / "pyproject.toml").read_text())["tool"]["straufi"]["id"] == "strategy-1"
    assert invoke("init", project).exit_code == 1  # Not empty anymore


def test_init_needs_a_login_and_creates_nothing_without_it(tmp_path):
    project = tmp_path / "moon"
    result = invoke("init", project, "--no-install")
    assert result.exit_code == 1 and "straufi login" in result.output
    assert not project.exists()


def test_the_sample_strategy_trades_supported_instruments(project):
    """The platform refuses the others: see `allSupportedPairs` in the codebase."""
    assert 'Instrument("BTC", "USDT", "binance")' in (project / "strategy.py").read_text()


def test_project_without_strategy_points_to_init(project):
    pyproject = project / "pyproject.toml"
    pyproject.write_text(re.sub(r'id = ".*"', "", pyproject.read_text()))
    result = invoke("build", "-p", project, "--dry-run")
    assert result.exit_code == 1 and "straufi init" in result.output


def test_dry_run_shows_user_errors_without_our_frames(project):
    strategy = project / "strategy.py"
    strategy.write_text(strategy.read_text().replace("lookback=24 * 120", "lookback=1 / 0"))
    result = invoke("build", "-p", project, "--dry-run")
    assert result.exit_code == 1
    assert "ZeroDivisionError" in result.output and "strategy.py" in result.output
    assert "straufi/cli" not in result.output


def test_dry_run_warns_about_secrets(project, client):
    (project / ".env").write_text("SECRET=1")
    (project / "private.pem").write_text("key")
    result = invoke("build", "-p", project, "--dry-run")
    assert result.exit_code == 0, result.output
    assert "strategy.py" in result.output and "  .env\n" not in result.output
    assert "private.pem" in result.output and "look like secrets" in result.output
    client.create_build.assert_not_called()


def test_dry_run_refuses_a_project_without_straufi(project):
    pyproject = project / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('"straufi>=', '"straufi-runner>='))
    result = invoke("build", "-p", project, "--dry-run")
    assert result.exit_code == 1 and "straufi is not in the dependencies" in result.output


def test_build_uploads_the_archive_it_declares(project, client):
    result = invoke("build", "-p", project)
    assert result.exit_code == 0, result.output
    assert "Built build-1" in result.output

    data = api.upload.call_args.args[2]  # pyright: ignore[reportFunctionMemberAccess]
    build_id, manifest, checksum, size, python = client.commit_build.call_args.args
    assert (build_id, checksum, size) == ("build-1", hashlib.sha256(data).hexdigest(), len(data))
    assert python == f"{sys.version_info[0]}.{sys.version_info[1]}"
    assert manifest["entrypoint"] == "strategy:Moon"


def test_build_reuses_the_build_of_the_same_sources(project, client):
    invoke("build", "-p", project)
    _, _, checksum, _, python = client.commit_build.call_args.args
    client.reset_mock()
    client.list_builds.return_value = [build(id="old", uploadChecksum=checksum, pythonVersion=python)]

    result = invoke("build", "-p", project)
    assert "Nothing changed since build old" in result.output
    client.create_build.assert_not_called()

    (project / "strategy.py").write_text((project / "strategy.py").read_text() + "\n# Changed\n")
    invoke("build", "-p", project)
    client.create_build.assert_called_once()


def test_build_shows_why_it_failed(project, client):
    client.get_build.return_value = build("failed", failureMessage="No such package")
    result = invoke("build", "-p", project)
    assert result.exit_code == 1 and "No such package" in result.output


def test_ctrl_c_cancels_the_build(project, client, monkeypatch):
    monkeypatch.setattr(build_command.time, "sleep", Mock(side_effect=KeyboardInterrupt))
    result = invoke("build", "-p", project)
    assert result.exit_code == 130
    client.cancel_build.assert_called_once_with("build-1")


@pytest.mark.parametrize(("command", "page"), [("backtest", "backtests/new"), ("deploy", "builds/deploy")])
def test_backtest_and_deploy_open_their_page(project, client, browser, monkeypatch, command, page):
    monkeypatch.setenv("STRAUFI_WEBAPP_URL", "https://app.test/")
    (project / "strategy.py").write_text("broken(")  # The code doesn't matter: nothing is built.
    client.reset_mock()

    result = invoke(command, "-p", project)
    assert result.exit_code == 0, result.output
    url = f"https://app.test/strategies/strategy-1/{page}"
    browser.assert_called_once_with(url)
    assert url in result.output
    assert client.mock_calls == []


def test_without_a_browser_the_page_is_shown(project, browser):
    browser.return_value = False
    result = invoke("deploy", "-p", project)
    assert result.exit_code == 0, result.output
    assert (
        "Open this page in your browser: https://app.straufi.com/strategies/strategy-1/builds/deploy" in result.output
    )


def test_status_shows_the_strategy_and_its_failures(project, client):
    instruments = [{"base": "BTC", "quote": "USDT", "broker": "binance"}]
    client.get_strategy.return_value = strategy(
        isActive=True, baseBudget={"binance": {"USDT": 1}}, instruments=instruments
    )
    client.list_executions.return_value = [execution(status="failed", failureReason="strategy-error")]
    result = invoke("status", "-p", project)
    assert result.exit_code == 0, result.output
    assert "BTC/USDT on binance" in result.output and "binance: 1 USDT" in result.output
    assert "strategy-error" in result.output


def respond(monkeypatch, *responses: httpx.Response | Exception) -> list[httpx.Request]:
    """Answers the requests at the transport level, so what's tested is what goes over the wire."""
    requests = []
    answers = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(api, "_get_http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("STRAUFI_TOKEN", "token")
    return requests


def test_an_expired_login_says_so(monkeypatch):
    respond(monkeypatch, httpx.Response(401, json={"message": "Nope"}))
    with pytest.raises(auth.SessionExpiredError):
        StraufiClient().list_builds("strategy-1")


def test_an_unknown_strategy_says_so(monkeypatch):
    respond(monkeypatch, httpx.Response(404, json={"message": "Not found."}))
    with pytest.raises(cli.StraufiError, match="belongs to another account"):
        StraufiClient().get_strategy("strategy-1")


def test_api_errors_show_their_message(monkeypatch):
    respond(monkeypatch, httpx.Response(400, json={"message": "Cannot activate a strategy without instruments"}))
    with pytest.raises(api.GatewayError, match="without instruments"):
        StraufiClient().set_active("strategy-1", True)


def test_an_unreachable_gateway_says_so(monkeypatch):
    respond(monkeypatch, httpx.ConnectError("refused"))
    with pytest.raises(api.GatewayError, match="Could not reach Straufi"):
        StraufiClient().get_build("build-1")


def test_an_error_without_a_message_shows_its_status(monkeypatch):
    respond(monkeypatch, httpx.Response(502, text="<html>Bad gateway</html>"))
    with pytest.raises(api.GatewayError, match="HTTP 502"):
        StraufiClient().get_build("build-1")


def test_an_unexpected_response_says_so(monkeypatch):
    respond(monkeypatch, httpx.Response(200, text="<html>Hello</html>"))
    with pytest.raises(api.GatewayError, match="unexpected response"):
        StraufiClient().get_build("build-1")


def test_requests_carry_the_token_and_the_camel_case_body(monkeypatch):
    requests = respond(monkeypatch, httpx.Response(201, json=strategy()))
    StraufiClient().create_strategy("moon", StrategyMode.PAPER)

    request = requests[0]
    assert request.headers["authorization"] == "Bearer token"
    assert request.url.path == "/v1/strategies"
    assert json.loads(request.content) == {"displayName": "moon", "mode": "paper"}


def test_empty_query_values_are_left_out(monkeypatch):
    requests = respond(monkeypatch, httpx.Response(200, json={"builds": []}))
    StraufiClient().list_builds("strategy-1")
    assert dict(requests[0].url.params) == {"pageSize": "20"}


def test_uploads_send_the_file_and_its_headers(monkeypatch):
    requests = respond(monkeypatch, httpx.Response(200))
    api.upload("http://bucket/key?signature=1", {"x-amz-checksum-sha256": "abc"}, b"archive")

    request = requests[0]
    assert (request.method, request.content) == ("PUT", b"archive")
    assert request.headers["x-amz-checksum-sha256"] == "abc" and "authorization" not in request.headers


def test_a_refused_upload_says_so(monkeypatch):
    respond(monkeypatch, httpx.Response(403, text="<Error/>"))
    with pytest.raises(api.GatewayError, match="upload failed with HTTP 403"):
        api.upload("http://bucket/key", {}, b"archive")


@pytest.mark.parametrize(
    ("available", "expected"),
    [({"uv", "poetry"}, "uv"), ({"poetry"}, "poetry"), (set(), "pip")],
)
def test_package_manager_precedence(monkeypatch, available, expected):
    monkeypatch.setattr(environment.shutil, "which", lambda name: f"/bin/{name}" if name in available else None)
    monkeypatch.setattr(
        environment.subprocess, "run", lambda command, **_: subprocess.CompletedProcess(command, 0, "", "")
    )
    assert environment.detect_manager() == expected


def test_broken_package_managers_are_skipped(tmp_path, monkeypatch):
    broken = tmp_path / "uv"
    broken.write_text("#!/nonexistent/python\n")
    broken.chmod(0o755)
    failing = tmp_path / "poetry"
    failing.write_text("#!/bin/sh\nexit 1\n")
    failing.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert environment.detect_manager() == "pip"

    failing.write_text("#!/bin/sh\nexit 0\n")
    assert environment.detect_manager() == "poetry"


@pytest.mark.parametrize("manager", ["uv", "poetry", "pip"])
def test_init_creates_the_environment(tmp_path, monkeypatch, manager, client):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        assert kwargs["cwd"] == tmp_path / "proj" and "VIRTUAL_ENV" not in kwargs["env"]
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setenv("VIRTUAL_ENV", "/some/other/venv")
    monkeypatch.setattr(environment, "detect_manager", lambda: manager)
    monkeypatch.setattr(environment.subprocess, "run", fake_run)
    result = invoke("init", tmp_path / "proj")
    assert result.exit_code == 0, result.output
    assert f"{environment.run_hint(manager)} backtest" in result.output

    pyproject = tomllib.loads((tmp_path / "proj" / "pyproject.toml").read_text())
    if manager == "uv":
        assert commands == [["uv", "sync"]]
    elif manager == "poetry":
        assert pyproject["tool"]["poetry"] == {"package-mode": False}
        assert commands[-1] == ["poetry", "install", "--with", "dev"]
    else:
        assert commands[0][1:] == ["-m", "venv", ".venv"]
        assert [c.split(">")[0] for c in commands[1][3:]] == ["install", "straufi", "pandas", "numpy", "ruff"]


def test_init_reports_install_failures(tmp_path, monkeypatch, client):
    monkeypatch.setattr(environment, "detect_manager", lambda: "uv")
    monkeypatch.setattr(
        environment.subprocess, "run", lambda command, **_: subprocess.CompletedProcess(command, 1, "", "no network")
    )
    result = invoke("init", tmp_path / "proj")
    assert result.exit_code == 1
    assert "no network" in result.output and (tmp_path / "proj" / "strategy.py").exists()
