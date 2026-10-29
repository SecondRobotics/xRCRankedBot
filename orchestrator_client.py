import aiohttp
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlencode


class OrchestratorAPIError(RuntimeError):
    def __init__(self, status: int, code: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details or {}


@dataclass
class OrchestratorTokens:
    default: str
    moderation: Optional[str] = None
    admin: Optional[str] = None


def discord_actor(user) -> Dict[str, str]:
    return {
        "type": "discord_user",
        "discordUserId": str(getattr(user, "id", "")),
        "displayName": getattr(user, "display_name", None) or getattr(user, "name", "Discord User"),
    }


SERVICE_ACTOR = {"type": "service", "displayName": "ranked-bot"}


class OrchestratorClient:
    def __init__(
        self,
        base_url: str,
        tokens: OrchestratorTokens,
        session: Optional[aiohttp.ClientSession] = None,
        timeout_seconds: int = 15,
    ):
        self.base_url = base_url.rstrip("/")
        self.tokens = tokens
        self._session = session
        self._owns_session = session is None
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def close(self):
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
            self._owns_session = True
        return self._session

    def _token_for_scope(self, scope: str) -> str:
        if scope == "moderation":
            return self.tokens.moderation or self.tokens.default
        if scope == "admin":
            return self.tokens.admin or self.tokens.default
        return self.tokens.default

    async def _request(self, *args, **kwargs):
        try:
            return await self._request_unchecked(*args, **kwargs)
        except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError, ValueError) as exc:
            raise OrchestratorAPIError(0, 'SERVICE_UNAVAILABLE', 'The service could not be reached or returned an invalid response.') from exc

    async def _request_unchecked(
        self,
        method: str,
        path: str,
        *,
        json: Optional[dict] = None,
        query: Optional[dict] = None,
        scope: str = "default",
        timeout: Optional[aiohttp.ClientTimeout] = None,
    ) -> Any:
        token = self._token_for_scope(scope)
        if not token:
            raise OrchestratorAPIError(
                0,
                "MISSING_TOKEN",
                "ORCHESTRATOR_TOKEN is not configured.",
            )

        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode({k: v for k, v in query.items() if v is not None})}"

        headers = {"Authorization": f"Bearer {token}"}
        request_options = {"timeout": timeout} if timeout is not None else {}
        async with self._get_session().request(method, url, json=json, headers=headers, **request_options) as response:
            if response.status == 204:
                return None

            content_type = response.headers.get("Content-Type", "")
            payload = await response.json(content_type=None) if "json" in content_type else await response.text()

            if response.status >= 400:
                err = payload.get("error", {}) if isinstance(payload, dict) else {}
                raise OrchestratorAPIError(
                    response.status,
                    err.get("code", f"HTTP_{response.status}"),
                    err.get("message", str(payload)),
                    err.get("details", {}),
                )
            return payload

    async def launch_server(self, payload: dict) -> dict:
        return await self._request("POST", "/v1/servers", json=payload)

    async def list_servers(self, **filters) -> list[dict]:
        payload = await self._request("GET", "/v1/servers", query=filters)
        return payload.get("sessions", [])

    async def get_session(self, session_id: str) -> dict:
        return await self._request("GET", f"/v1/servers/{session_id}")

    async def get_session_by_port(self, port: int, *, moderation: bool = False) -> dict:
        return await self._request(
            "GET",
            f"/v1/servers/by-port/{port}",
            scope="moderation" if moderation else "default",
        )

    async def stop_session(self, session_id: str, *, reason: str, actor: Optional[dict] = None) -> dict:
        return await self._request(
            "POST",
            f"/v1/servers/{session_id}/stop",
            json={"reason": reason, "actor": actor or SERVICE_ACTOR},
        )

    async def stop_session_by_port(self, port: int, *, reason: str, actor: Optional[dict] = None) -> dict:
        return await self._request(
            "POST",
            f"/v1/servers/by-port/{port}/stop",
            json={"reason": reason, "actor": actor or SERVICE_ACTOR},
        )

    async def restart_session(self, session_id: str, *, reason: str, actor: Optional[dict] = None) -> dict:
        return await self._request(
            "POST",
            f"/v1/servers/{session_id}/restart",
            json={"reason": reason, "actor": actor or SERVICE_ACTOR},
        )

    async def kill_session(self, session_id: str, *, reason: str, actor: Optional[dict] = None) -> dict:
        return await self._request(
            "POST",
            f"/v1/servers/{session_id}/kill",
            json={"reason": reason, "actor": actor or SERVICE_ACTOR},
            scope="admin",
        )

    async def get_players(self, session_id: str, *, moderation: bool = False) -> list[dict]:
        payload = await self._request(
            "GET",
            f"/v1/servers/{session_id}/players",
            scope="moderation" if moderation else "default",
        )
        return payload.get("players", [])

    async def get_chat(self, session_id: str, *, limit: int = 100, moderation: bool = False) -> list[dict]:
        payload = await self._request(
            "GET",
            f"/v1/servers/{session_id}/chat",
            query={"limit": limit},
            scope="moderation" if moderation else "default",
        )
        return payload.get("messages", [])

    async def get_logs(self, session_id: str, *, lines: int = 100, download: bool = False) -> dict:
        return await self._request(
            "GET",
            f"/v1/servers/{session_id}/logs",
            query={"lines": lines, "download": str(download).lower()},
            scope="admin",
        )

    async def get_latest_score(self, session_id: str) -> Optional[dict]:
        payload = await self._request("GET", f"/v1/servers/{session_id}/scores/latest")
        return payload.get("score")

    async def admin_overview(self) -> dict:
        return await self._request("GET", "/v1/admin/overview", scope="admin")

    async def update_xrc_binary(self, *, reason: str, actor: Optional[dict] = None) -> dict:
        return await self._request(
            "POST",
            "/v1/admin/xrc-binary/update",
            json={"reason": reason, "actor": actor or SERVICE_ACTOR},
            scope="admin",
        )

    async def get_events(
        self,
        *,
        after_event_id: Optional[str] = None,
        types: Optional[list[str]] = None,
        wait_ms: int = 25000,
    ) -> list[dict]:
        payload = await self._request(
            "GET",
            "/v1/events",
            # Leave time for the full server wait plus network/response overhead.
            timeout=aiohttp.ClientTimeout(total=max(self._timeout.total or 0, wait_ms / 1000 + 10)),
            query={
                "afterEventId": after_event_id,
                "types": ",".join(types) if types else None,
                "waitMs": wait_ms,
            },
        )
        return payload.get("events", [])
