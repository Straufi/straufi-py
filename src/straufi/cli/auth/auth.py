import os
from dataclasses import replace
from datetime import UTC, datetime

from ..api import api
from . import credentials
from .errors import SessionExpiredError


def access_token() -> str | None:
    """A valid access token, refreshed if needed, or None when logged out.

    You can also define the environment variable `STRAUFI_TOKEN` which will always take precedence,
    for example for a CI system. It will not be refreshed or saved.
    """
    if token := os.environ.get("STRAUFI_TOKEN", "").strip():
        return token

    creds = credentials.load_from_store()
    if creds is None or not creds.expires_soon:
        return creds and creds.access_token

    # Ensure only a single process at a time refreshes the access token, because refresh tokens
    # are valid once, and reusing one revokes the login.
    with credentials.lock_refresh_token():
        # Another process may have refreshed (or logged out) while we waited the lock.
        creds = credentials.load_from_store()
        if creds is None or not creds.expires_soon:
            return creds and creds.access_token

        if creds.refresh_token_expires_at <= datetime.now(UTC):
            credentials.remove()
            raise SessionExpiredError()

        try:
            tokens = api.refresh(creds.refresh_token)
        except api.GatewayError as e:
            if e.status == 401:  # Revoked, expired, or reused: the login is over.
                credentials.remove()
                raise SessionExpiredError() from None
            raise

        refreshed = replace(
            creds,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            refresh_token_expires_at=tokens.refresh_token_expires_at,
        )
        return credentials.save(refreshed).access_token


def login(tokens: api.Tokens) -> tuple[credentials.Credentials, credentials.Credentials | None]:
    """Saves a new login. Returns it, and the previous one, for the caller to revoke."""
    with credentials.lock_refresh_token():
        previous = credentials.load_or_none()
        return credentials.save(credentials.Credentials.from_tokens(tokens)), previous


def logout() -> credentials.Credentials | None:
    """Deletes the login. Returns it, for the caller to revoke."""
    with credentials.lock_refresh_token():
        previous = credentials.load_or_none()
        credentials.remove()
        return previous
