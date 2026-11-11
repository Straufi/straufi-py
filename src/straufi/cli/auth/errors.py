from ...lib.errors import StraufiError


class SessionExpiredError(StraufiError):
    def __init__(self) -> None:
        super().__init__("Your login expired: run `straufi login` again.")


class CredentialsError(StraufiError):
    """The credentials could not be read."""
