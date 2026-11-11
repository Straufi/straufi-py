from dataclasses import dataclass
from datetime import datetime
from functools import cache
from typing import Any

import httpx

from ... import __version__
from ...lib.errors import StraufiError
from .url import get_api_url

TIMEOUT = 30


class GatewayError(StraufiError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    refresh_token_expires_at: datetime

    @classmethod
    def from_response(cls, body: Any) -> "Tokens":
        try:
            return cls(
                access_token=body["accessToken"],
                refresh_token=body["refreshToken"],
                refresh_token_expires_at=datetime.fromisoformat(body["refreshTokenExpiresAt"]),
            )
        except (KeyError, TypeError, ValueError):
            raise GatewayError("Straufi sent an unexpected response") from None


def exchange_cli_code(code: str, code_verifier: str) -> Tokens:
    return Tokens.from_response(request("POST", "/v1/auth/cli/token", {"code": code, "codeVerifier": code_verifier}))


def refresh(refresh_token: str) -> Tokens:
    return Tokens.from_response(request("POST", "/v1/auth/refresh", {"refreshToken": refresh_token}))


def sign_out(refresh_token: str) -> None:
    request("POST", "/v1/auth/sign-out", {"refreshToken": refresh_token})


@cache
def _get_http_client() -> httpx.Client:
    """One client per command, so that polling reuses its connection."""

    return httpx.Client(headers={"user-agent": f"straufi-cli/{__version__}"}, timeout=TIMEOUT)


def request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    token: str | None = None,
) -> Any:
    params = {key: value for key, value in (query or {}).items() if value is not None}
    headers = {"authorization": f"Bearer {token}"} if token is not None else None
    try:
        response = _get_http_client().request(method, get_api_url() + path, json=body, params=params, headers=headers)
    except httpx.TransportError as e:
        raise GatewayError(f"Could not reach Straufi at {get_api_url()}: {e}") from None

    if not response.is_success:
        raise GatewayError(_get_error_message(response), status=response.status_code)
    try:
        return response.json() if response.content else None
    except ValueError:
        raise GatewayError("Straufi sent an unexpected response") from None


def _get_error_message(response: httpx.Response) -> str:
    try:
        message = response.json().get("message")
    except (ValueError, AttributeError):
        message = None
    return message or f"Straufi answered with HTTP {response.status_code}"


def upload(upload_url: str, headers: dict[str, str], data: bytes) -> None:
    """PUTs a file to a presigned URL."""
    try:
        response = _get_http_client().put(upload_url, headers=headers, content=data)
    except httpx.TransportError as e:
        raise GatewayError(f"Could not upload to Straufi: {e}") from None
    if not response.is_success:
        raise GatewayError(f"The upload failed with HTTP {response.status_code}", status=response.status_code)
