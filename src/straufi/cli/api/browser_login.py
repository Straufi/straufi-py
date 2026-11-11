"""Logging in through the browser: an OAuth-style localhost redirect, with PKCE (RFC 7636, S256).

1. We open the webapp's /cli/authorize page with a PKCE challenge, a state, and the port of a local HTTP server.
2. Once the user authorizes the CLI, the webapp redirects their browser to http://127.0.0.1:<port>/callback?code=….
3. We exchange that one-time code and our PKCE verifier for tokens, through the gateway.

The verifier never leaves this process, so a code leaked from the browser (history, extensions...) is useless.
"""

import base64
import hashlib
import html
import secrets
import time
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qsl, urlencode, urlsplit

from ...lib.errors import StraufiError
from . import api, url

_TIMEOUT = 5 * 60
"""Seconds the user has to log in."""


class LoginError(StraufiError):
    pass


def _pkce_pair() -> tuple[str, str]:
    """Returns a (verifier, challenge) pair: 86 base64url characters, and base64url(sha256(verifier))."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def login(show_url: Callable[[str, bool], None], open_browser: bool = True) -> api.Tokens:
    """`show_url` gets the login page's URL, and whether the browser was opened on it."""
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)

    with _CallbackServer(state, exchange=lambda code: api.exchange_cli_code(code, verifier)) as server:
        query = urlencode({"port": server.port, "state": state, "code_challenge": challenge})
        full_url = f"{url.get_webapp_url()}/cli/authorize?{query}"
        show_url(full_url, open_browser and webbrowser.open(full_url))
        return server.wait(_TIMEOUT)


class _CallbackServer(HTTPServer):
    """Serves /callback on 127.0.0.1, on a random free port, until the webapp redirects the browser to it."""

    def __init__(self, state: str, exchange: Callable[[str], api.Tokens]) -> None:
        # 127.0.0.1 and not localhost, which may resolve to ::1 or something else: that's what the webapp redirects to.
        super().__init__(("127.0.0.1", 0), _CallbackHandler)
        self.state = state
        self.exchange = exchange
        self.outcome: api.Tokens | StraufiError | None = None

    @property
    def port(self) -> int:
        return self.server_address[1]

    def wait(self, timeout: float) -> api.Tokens:
        deadline = time.monotonic() + timeout
        while self.outcome is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LoginError("Timed out waiting for you to log in in the browser.")
            self.timeout = min(remaining, 0.5)  # Of each handle_request(), to check the deadline in between.
            self.handle_request()

        if isinstance(self.outcome, StraufiError):
            raise self.outcome
        return self.outcome


class _CallbackHandler(BaseHTTPRequestHandler):
    server: _CallbackServer  # pyright: ignore[reportIncompatibleVariableOverride]
    timeout = 1  # Browsers open speculative connections that send nothing: don't let them block the server.

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path != "/callback":
            return self._page(404, "Not found", "This page doesn't exist.")

        params = dict(parse_qsl(url.query))
        if not secrets.compare_digest(params.get("state", ""), self.server.state):
            # From another login attempt (an old tab), or another site: ignore it, and keep waiting for ours.
            return self._page(
                400, "Login failed", "This link is from another login attempt. Run `straufi login` again."
            )

        if error := params.get("error"):
            message = "You denied the login." if error == "access_denied" else f"Login failed: {error}"
            return self._fail(message, "The Straufi CLI was not authorized. You can close this tab.", "Login canceled")
        if not (code := params.get("code")):
            return self._fail(
                "Login failed: the webapp sent no code.", "The webapp sent no code. Run `straufi login` again."
            )

        # Exchanged before answering, so the page tells whether the login really worked.
        try:
            self.server.outcome = self.server.exchange(code)
        except StraufiError as e:
            return self._fail(f"Login failed: {e}", f"{e} Run `straufi login` again.")

        self._page(
            200, "Logged in", "The Straufi CLI is logged in. You can close this tab and go back to your terminal."
        )

    def _fail(self, error: str, page: str, title: str = "Login failed") -> None:
        self.server.outcome = LoginError(error)
        self._page(400, title, page)

    def log_message(self, format: str, *args: object) -> None:
        pass  # Disable logs

    def _page(self, status: int, title: str, message: str) -> None:
        body = _PAGE.format(title=html.escape(title), message=html.escape(message)).encode()
        self.send_response(status)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.send_header("referrer-policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Straufi</title>
<style>
  :root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
  body {{ display: grid; place-items: center; min-height: 100vh; margin: 0; padding: 0 16px; }}
  main {{ max-width: 28rem; text-align: center; }}
</style>
</head>
<body><main><h1>{title}</h1><p>{message}</p></main></body>
</html>
"""
