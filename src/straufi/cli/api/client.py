from typing import Any

from ...lib.errors import StraufiError
from .. import auth
from ..models import (
    Build,
    BuildStatus,
    CreatedBuild,
    Execution,
    Strategy,
    StrategyMode,
)
from . import api


class StraufiClient:
    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None, query: dict[str, Any] | None = None
    ) -> Any:
        # Asked for on every request because access token lasts only 15 minutes.
        token = auth.access_token()
        if token is None:
            raise StraufiError("You are not logged in: run `straufi login` first.")
        try:
            return api.request(method, path, body, query, token)
        except api.GatewayError as e:
            if e.status == 401:
                raise auth.SessionExpiredError() from None
            raise

    def create_strategy(self, name: str, mode: StrategyMode) -> Strategy:
        return self._request("POST", "/v1/strategies", {"displayName": name, "mode": mode})

    def get_strategy(self, strategy_id: str) -> Strategy:
        try:
            return self._request("GET", f"/v1/strategies/{strategy_id}")
        except api.GatewayError as e:
            if e.status == 404:
                raise StraufiError(f"Strategy {strategy_id} doesn't exist, or belongs to another account.") from None
            raise

    def set_active(self, strategy_id: str, active: bool) -> Strategy:
        return self._request("PATCH", f"/v1/strategies/{strategy_id}", {"isActive": active})

    def create_build(self, strategy_id: str) -> CreatedBuild:
        return self._request("POST", f"/v1/strategies/{strategy_id}/builds")

    def commit_build(
        self, build_id: str, manifest: dict[str, Any], checksum: str, size: int, python_version: str
    ) -> Build:
        body = {
            "submittedManifest": manifest,
            "uploadChecksum": checksum,
            "uploadSizeBytes": size,
            "pythonVersion": python_version,
        }
        return self._request("POST", f"/v1/builds/{build_id}/commit", body)

    def get_build(self, build_id: str) -> Build:
        return self._request("GET", f"/v1/builds/{build_id}")

    def list_builds(self, strategy_id: str, status: BuildStatus | None = None, limit: int = 20) -> list[Build]:
        query = {"status": status, "pageSize": limit}
        return self._request("GET", f"/v1/strategies/{strategy_id}/builds", query=query)["builds"]

    def cancel_build(self, build_id: str) -> Build:
        return self._request("POST", f"/v1/builds/{build_id}/cancel")

    def list_executions(self, strategy_id: str, limit: int = 5) -> list[Execution]:
        query = {"pageSize": limit}
        return self._request("GET", f"/v1/strategies/{strategy_id}/executions", query=query)["executions"]
