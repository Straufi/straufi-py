import base64
import json
import os
import sys
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import cached_property
from pathlib import Path
from typing import Any

from ..api import api
from . import keyring
from .errors import CredentialsError

REFRESH_MARGIN = timedelta(seconds=60)
"""Access tokens expiring sooner than that are refreshed before use."""


class Storage(StrEnum):
    """The system keyring, or credentials.json when there is none."""

    KEYRING = "keyring"
    FILE = "file"


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "straufi"


def credentials_path() -> Path:
    return config_dir() / "credentials.json"


@dataclass
class Credentials:
    access_token: str | None
    refresh_token: str
    refresh_token_expires_at: datetime
    logged_in_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    storage: Storage = Storage.KEYRING

    @classmethod
    def from_tokens(cls, tokens: api.Tokens) -> "Credentials":
        return cls(tokens.access_token, tokens.refresh_token, tokens.refresh_token_expires_at)

    @property
    def expires_soon(self) -> bool:
        exp = self._claims.get("exp")
        return not isinstance(exp, int | float) or datetime.fromtimestamp(exp, UTC) - datetime.now(UTC) < REFRESH_MARGIN

    @property
    def email(self) -> str | None:
        email = self._claims.get("email")
        return email if isinstance(email, str) else None

    @cached_property
    def _claims(self) -> dict[str, Any]:
        """Extracts the claims from the access token (doesn't verify the signature)."""
        try:
            payload = (self.access_token or "").split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            return claims if isinstance(claims, dict) else {}
        except (IndexError, ValueError):
            return {}


def save(credentials: Credentials) -> Credentials:
    """Saves the login where `credentials.storage` says, or in credentials.json when the keyring fails."""
    login = {
        "refresh_token": credentials.refresh_token,
        "refresh_token_expires_at": credentials.refresh_token_expires_at.isoformat(),
        "logged_in_at": credentials.logged_in_at.isoformat(),
    }
    path = credentials_path()

    # Two entries, because Windows limits each one to ~1280 characters, and the access token is a JWT. The refresh
    # token goes first: after a crash in between, the old access token is expired, and the new refresh token renews it.
    if credentials.storage == Storage.KEYRING and keyring.set(json.dumps(login), credentials.access_token or ""):
        path.unlink(missing_ok=True)
    else:
        credentials.storage = Storage.FILE
        keyring.delete()  # Don't leave half a login behind.

        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps({**login, "access_token": credentials.access_token})

        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")  # Created with 0600
        with os.fdopen(fd, "w") as f:
            f.write(content)

        os.replace(temporary, path)

    return credentials


def remove() -> None:
    keyring.delete()
    credentials_path().unlink(missing_ok=True)


def load_from_store() -> Credentials | None:
    """Reads the login from credentials.json when it was saved there without a keyring, or else from the keyring."""
    storage: Storage
    try:
        if credentials_path().exists():
            data = json.loads(credentials_path().read_text())
            storage = Storage.FILE
        elif entries := keyring.get():
            refresh_entry, access_token = entries
            data = {**json.loads(refresh_entry), "access_token": access_token}
            storage = Storage.KEYRING
        else:
            return None
        return Credentials(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            refresh_token_expires_at=datetime.fromisoformat(data["refresh_token_expires_at"]),
            logged_in_at=datetime.fromisoformat(data["logged_in_at"]),
            storage=storage,
        )
    except (OSError, ValueError, KeyError, TypeError):  # Written by an older version.
        return None


@contextmanager
def lock_refresh_token() -> Generator[None]:
    """Locks the credentials against the other straufi processes, while reading, refreshing and saving them."""
    path = config_dir() / "credentials.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as f:
        if sys.platform == "win32":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


def load_or_none() -> Credentials | None:
    """Unreadable credentials are replaced or deleted anyway."""
    try:
        return load_from_store()
    except CredentialsError:
        return None
