import aiohttp
from typing import Any, Optional, Union


class WebsiteAPIError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


class WebsiteClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        session: Optional[aiohttp.ClientSession] = None,
        timeout_seconds: int = 15,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
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

    async def _request(self, *args, **kwargs):
        try:
            return await self._request_unchecked(*args, **kwargs)
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise WebsiteAPIError(0, 'SERVICE_UNAVAILABLE', 'The service could not be reached or returned an invalid response.') from exc

    async def _request_unchecked(self, method: str, path: str, *, json: Optional[dict] = None) -> dict[str, Any]:
        if not self.api_key:
            raise WebsiteAPIError(0, "MISSING_TOKEN", "API_KEY is not configured.")

        headers = {"X-API-KEY": self.api_key}
        url = f"{self.base_url}/{path.strip('/')}/"
        async with self._get_session().request(method, url, json=json, headers=headers) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise WebsiteAPIError(
                    response.status,
                    data.get("code") or data.get("error", "HTTP_ERROR"),
                    data.get("message") or data.get("detail", "SecondWebsite request failed."),
                )
            if data.get("success") is False:
                raise WebsiteAPIError(
                    response.status,
                    data.get("code") or "WEBSITE_REJECTED",
                    data.get("message") or "SecondWebsite rejected the request.",
                )
            return data

    async def get_casual_games(self) -> list[dict]:
        data = await self._request("GET", "/api/subscriptions/casual-games/")
        return data.get("games", [])

    async def get_entitlement(self, discord_user_id: Union[int, str]) -> dict:
        data = await self._request("GET", f"/api/subscriptions/users/{discord_user_id}/entitlement/")
        return data.get("entitlement", {})

    async def start_casual_server(
        self,
        *,
        owner_discord_id: Union[int, str],
        game_code: str,
        game: Optional[str],
        requested_minutes: int,
        comment: str,
        password: str,
        guild_id: Optional[int],
        channel_id: Optional[int],
        interaction_id: Optional[int],
    ) -> dict:
        data = await self._request(
            "POST",
            "/api/subscriptions/server-sessions/start/",
            json={
                "owner_discord_id": str(owner_discord_id),
                "game_code": str(game_code),
                "game": game,
                "requested_minutes": requested_minutes,
                "comment": comment[:120],
                "password": password,
                "launch_source": "discord_bot",
                "launch_context": {
                    "discord_guild_id": str(guild_id) if guild_id else None,
                    "discord_channel_id": str(channel_id) if channel_id else None,
                    "discord_interaction_id": str(interaction_id) if interaction_id else None,
                },
            },
        )
        return data.get("session", {})

    async def stop_casual_server(self, website_session_id: str, *, reason: str = "discord_bot_stop") -> dict:
        data = await self._request(
            "POST",
            f"/api/subscriptions/server-sessions/{website_session_id}/stop/",
            json={"reason": reason},
        )
        return data.get("session", {})
