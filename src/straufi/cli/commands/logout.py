from .. import auth, ui
from ..api import api


def run():
    credentials = auth.logout()
    if credentials is None:
        ui.info("You were not logged in.")
        return

    try:
        api.sign_out(credentials.refresh_token)
        ui.success("Logged out.")
    except api.GatewayError as e:
        ui.warning(f"could not revoke the login on Straufi: {e}")
