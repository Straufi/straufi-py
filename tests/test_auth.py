import base64
import hashlib
import json
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
import keyring
import pytest
from keyring.backends import fail
from typer.testing import CliRunner

from straufi.cli import app
from straufi.cli.api import browser_login
from straufi.cli.auth import auth

runner = CliRunner()


def invoke(*args):
    return runner.invoke(app, list(args))


class FakeGateway(ThreadingHTTPServer):
    """The gateway's auth endpoints, with Passport's rules: one-time codes checked against their PKCE challenge, and
    refresh tokens valid once."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _GatewayHandler)
        self.codes: dict[str, str] = {}  # code → PKCE challenge, as the webapp would create them
        self.refresh_tokens: set[str] = set()
        self.calls: list[tuple[str, dict]] = []
        self.access_ttl = timedelta(minutes=15)
        self.refresh_delay = 0.0
        self.issued = 0
        self.lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def paths(self) -> list[str]:
        return [path for path, _ in self.calls]

    def issue(self) -> dict:
        self.issued += 1
        now = datetime.now(UTC)
        exp = int((now + self.access_ttl).timestamp())
        claims = json.dumps({"email": "jane@straufi.com", "exp": exp}).encode()
        claims = base64.urlsafe_b64encode(claims).rstrip(b"=").decode()
        refresh_token = f"refresh-{self.issued}"
        self.refresh_tokens.add(refresh_token)
        return {
            "accessToken": f"header.{claims}.signature-{self.issued}",
            "accessTokenExpiresAt": (now + self.access_ttl).isoformat(),
            "refreshToken": refresh_token,
            "refreshTokenExpiresAt": (now + timedelta(days=30)).isoformat(),
        }


class _GatewayHandler(BaseHTTPRequestHandler):
    server: FakeGateway  # pyright: ignore[reportIncompatibleVariableOverride]

    def do_POST(self) -> None:
        gateway = self.server
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        with gateway.lock:
            gateway.calls.append((self.path, body))

        if self.path == "/v1/auth/cli/token":
            challenge = gateway.codes.pop(body["code"], None)
            if challenge is None:
                return self._send(401, {"code": "INVALID_CLI_CODE", "message": "Invalid code."})
            digest = hashlib.sha256(body["codeVerifier"].encode()).digest()
            if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != challenge:
                return self._send(401, {"code": "INVALID_CODE_VERIFIER", "message": "Invalid verifier."})
            return self._send(200, gateway.issue())

        if self.path == "/v1/auth/refresh":
            time.sleep(gateway.refresh_delay)
            with gateway.lock:
                if body["refreshToken"] not in gateway.refresh_tokens:
                    return self._send(401, {"code": "REFRESH_TOKEN_REUSED", "message": "Reused."})
                gateway.refresh_tokens.remove(body["refreshToken"])
                return self._send(200, gateway.issue())

        if self.path == "/v1/auth/sign-out":
            gateway.refresh_tokens.discard(body["refreshToken"])
            return self._send(204, None)

        self._send(404, {"message": "Not found"})

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(self, status: int, body: dict | None) -> None:
        content = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        self.send_header("content-length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


class FakeBrowser:
    """Plays the webapp's /cli/authorize page: does each of `actions`, by visiting the CLI's callback."""

    def __init__(self, gateway: FakeGateway) -> None:
        self.gateway = gateway
        self.actions = ["authorize"]
        self.urls: list[str] = []
        self.pages: list[tuple[int, str]] = []
        self.threads: list[threading.Thread] = []

    def open(self, url: str) -> bool:
        self.urls.append(url)
        params = dict(parse_qsl(urlsplit(url).query))
        queries = []
        for action in self.actions:
            if action == "authorize":
                code = secrets.token_urlsafe()
                self.gateway.codes[code] = params["code_challenge"]
                queries.append({"code": code, "state": params["state"]})
            elif action == "unknown_code":
                queries.append({"code": "unknown", "state": params["state"]})
            elif action == "deny":
                queries.append({"error": "access_denied", "state": params["state"]})
            elif action == "wrong_state":
                queries.append({"code": "stolen", "state": "wrong"})

        callback = f"http://127.0.0.1:{params['port']}/callback"
        thread = threading.Thread(target=self._visit, args=([f"{callback}?{urlencode(q)}" for q in queries],))
        thread.start()
        self.threads.append(thread)
        return True

    def visited(self) -> list[tuple[int, str]]:
        """The pages the CLI answered, once all of them arrived."""
        for thread in self.threads:
            thread.join(timeout=10)
        return self.pages

    def _visit(self, urls: list[str]) -> None:
        for url in urls:
            response = httpx.get(url, timeout=10)
            self.pages.append((response.status_code, response.text))


@pytest.fixture
def gateway(monkeypatch):
    server = FakeGateway()
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    monkeypatch.setenv("STRAUFI_API_URL", server.url)
    monkeypatch.setenv("STRAUFI_WEBAPP_URL", "https://app.test/")
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def browser(gateway, monkeypatch):
    fake = FakeBrowser(gateway)
    monkeypatch.setattr(browser_login.webbrowser, "open", fake.open)
    yield fake
    fake.visited()


def test_login_refresh_logout(gateway, browser, config_dir, memory_keyring):
    result = invoke("login")
    assert result.exit_code == 0, result.output
    assert "Logged in as jane@straufi.com" in result.output
    status, page = browser.visited()[-1]
    assert status == 200 and "You can close this tab" in page

    url = urlsplit(browser.urls[0])
    params = dict(parse_qsl(url.query))
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://app.test/cli/authorize"
    assert len(params["code_challenge"]) == 43 and int(params["port"]) >= 1024

    # The whole login is in the keyring, in two entries: nothing on disk.
    def entry(name):
        return memory_keyring.passwords[("straufi", name)]

    path = config_dir / "credentials.json"
    assert not path.exists()
    assert len(memory_keyring.passwords) == 2
    access_token = entry("access_token")
    assert access_token.endswith("signature-1")
    assert json.loads(entry("refresh_token")).keys() == {"refresh_token", "refresh_token_expires_at", "logged_in_at"}
    assert json.loads(entry("refresh_token"))["refresh_token"] == "refresh-1"

    # Still valid: no refresh.
    assert auth.access_token() == access_token
    assert "/v1/auth/refresh" not in gateway.paths()

    # Expiring soon: refreshed, and the new refresh token saved.
    gateway.access_ttl = timedelta(seconds=30)
    assert invoke("login").exit_code == 0
    assert ("/v1/auth/sign-out", {"refreshToken": "refresh-1"}) in gateway.calls  # The previous login is revoked
    assert (auth.access_token() or "").endswith("signature-3")
    assert gateway.calls[-1] == ("/v1/auth/refresh", {"refreshToken": "refresh-2"})
    assert json.loads(entry("refresh_token"))["refresh_token"] == "refresh-3"
    assert entry("access_token").endswith("signature-3")

    result = invoke("logout")
    assert "Logged out" in result.output
    assert gateway.calls[-1] == ("/v1/auth/sign-out", {"refreshToken": "refresh-3"})
    assert memory_keyring.passwords == {}
    assert "not logged in" in invoke("logout").output
    assert auth.access_token() is None


def test_login_without_keyring_uses_a_private_file(gateway, browser, config_dir):
    keyring.set_keyring(fail.Keyring())
    gateway.access_ttl = timedelta(seconds=30)

    result = invoke("login")
    assert result.exit_code == 0, result.output
    assert "no system keyring found" in result.output

    path = config_dir / "credentials.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())["refresh_token"] == "refresh-1"

    assert (auth.access_token() or "").endswith("signature-2")  # Refreshed, and kept in the file
    assert json.loads(path.read_text())["refresh_token"] == "refresh-2"

    assert "Logged out" in invoke("logout").output
    assert not path.exists()


def test_login_ignores_callbacks_from_other_attempts(gateway, browser):
    browser.actions = ["wrong_state", "authorize"]
    result = invoke("login")
    assert result.exit_code == 0, result.output
    assert [status for status, _ in browser.visited()] == [400, 200]
    assert "another login attempt" in browser.pages[0][1]


@pytest.mark.parametrize(
    ("action", "message", "page"),
    [
        ("deny", "You denied the login", "was not authorized"),
        ("unknown_code", "Login failed: Invalid code.", "Invalid code."),
    ],
)
def test_login_failures(gateway, browser, config_dir, action, message, page):
    browser.actions = [action]
    result = invoke("login")
    assert result.exit_code == 1
    assert message in result.output
    status, content = browser.visited()[0]
    assert status == 400 and page in content
    assert not (config_dir / "credentials.json").exists()


def test_login_times_out(gateway, browser, monkeypatch):
    monkeypatch.setattr(browser_login, "_TIMEOUT", 0.2)
    result = invoke("login", "--no-browser")
    assert result.exit_code == 1
    assert "https://app.test/cli/authorize?port=" in result.output
    assert "Timed out" in result.output
    assert browser.urls == []  # --no-browser


def test_revoked_login_is_deleted(gateway, browser, config_dir):
    gateway.access_ttl = timedelta(seconds=30)
    invoke("login")
    gateway.refresh_tokens.clear()  # Revoked on Straufi's side

    with pytest.raises(auth.SessionExpiredError):
        auth.access_token()
    assert not (config_dir / "credentials.json").exists()


def test_concurrent_refreshes_use_the_refresh_token_once(gateway, browser):
    gateway.access_ttl = timedelta(seconds=30)
    invoke("login")
    gateway.access_ttl = timedelta(minutes=15)
    gateway.refresh_delay = 0.2

    tokens: list[str | None] = []
    threads = [threading.Thread(target=lambda: tokens.append(auth.access_token())) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert gateway.paths().count("/v1/auth/refresh") == 1
    assert len(tokens) == 4 and len(set(tokens)) == 1


def test_straufi_token_takes_precedence(gateway, monkeypatch):
    monkeypatch.setenv("STRAUFI_TOKEN", " ci-token ")
    assert auth.access_token() == "ci-token"
    assert gateway.calls == []


def test_credentials_of_older_versions_are_logged_out(config_dir):
    config_dir.mkdir(parents=True)
    (config_dir / "credentials.json").write_text('{"token": "abc", "logged_in_at": "2026-01-01T00:00:00+00:00"}')
    assert auth.credentials.load_from_store() is None
    assert "not logged in" in invoke("logout").output
    assert not (config_dir / "credentials.json").exists()


def test_missing_access_token_is_refreshed(gateway, browser, memory_keyring):
    invoke("login")
    del memory_keyring.passwords[("straufi", "access_token")]  # Crash between the two writes

    assert (auth.access_token() or "").endswith("signature-2")
    assert gateway.calls[-1] == ("/v1/auth/refresh", {"refreshToken": "refresh-1"})
