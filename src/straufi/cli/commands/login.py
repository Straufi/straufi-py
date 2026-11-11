from .. import auth, ui
from ..api import api, browser_login


def _show_url(url: str, opened: bool) -> None:
    ui.info(
        "Your browser has been opened to log you in. If it didn't open, visit:"
        if opened
        else "Open this page in your browser to log in:"
    )
    ui.info(f"  {url}\n\nWaiting for you to log in... (Ctrl+C to cancel)")


def run(browser: bool):
    credentials, previous = auth.login(browser_login.login(_show_url, open_browser=browser))

    if previous is not None:
        try:
            api.sign_out(previous.refresh_token)
        except api.GatewayError as e:
            ui.warning(f"could not revoke the previous login on Straufi: {e}")

    if credentials.storage == "file":
        ui.warning(f"no system keyring found, your login is saved in {auth.credentials_path()} instead.")
    ui.success(f"Logged in as {email}." if (email := credentials.email) else "Logged in.")
