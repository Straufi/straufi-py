import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError


class MemoryKeyring(KeyringBackend):
    priority = 1  # pyright: ignore[reportAssignmentType]

    def __init__(self) -> None:
        super().__init__()
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        try:
            del self.passwords[(service, username)]
        except KeyError:
            raise PasswordDeleteError(username) from None


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("STRAUFI_TOKEN", raising=False)
    return tmp_path / "config" / "straufi"


@pytest.fixture(autouse=True)
def memory_keyring():
    """Never touch the real system keyring."""
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)
