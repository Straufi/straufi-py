import os

_DEFAULT_WEBAPP_URL = "https://app.straufi.com"
_DEFAULT_API_URL = "https://api.straufi.com"


def get_webapp_url() -> str:
    return (os.environ.get("STRAUFI_WEBAPP_URL") or _DEFAULT_WEBAPP_URL).rstrip("/")


def get_api_url() -> str:
    return (os.environ.get("STRAUFI_API_URL") or _DEFAULT_API_URL).rstrip("/")
