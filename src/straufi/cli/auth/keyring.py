from contextlib import suppress

from .errors import CredentialsError

KEYRING_SERVICE = "straufi"


def get() -> tuple[str, str | None] | None:
    """Returns the refresh entry and the access token, or None when not logged in with the keyring."""
    import keyring
    from keyring.errors import KeyringError, NoKeyringError

    try:
        refresh_entry = keyring.get_password(KEYRING_SERVICE, "refresh_token")
        access_token = keyring.get_password(KEYRING_SERVICE, "access_token")
    except NoKeyringError:
        return None
    except KeyringError as e:
        raise CredentialsError(f"Could not read your login from the system keyring: {e}") from None
    return (refresh_entry, access_token) if refresh_entry is not None else None


def set(refresh_entry: str, access_token: str) -> bool:
    """Returns False when there is no usable keyring."""
    import keyring
    from keyring.errors import KeyringError

    try:
        keyring.set_password(KEYRING_SERVICE, "refresh_token", refresh_entry)
        keyring.set_password(KEYRING_SERVICE, "access_token", access_token)
        return True
    except KeyringError:
        return False


def delete() -> None:
    import keyring
    from keyring.errors import KeyringError

    for entry in ("refresh_token", "access_token"):
        with suppress(KeyringError):  # Not there, or no keyring at all.
            keyring.delete_password(KEYRING_SERVICE, entry)
