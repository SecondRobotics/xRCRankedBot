import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_BOT_TOKEN", "test")
os.environ.setdefault("DISCORD_APPLICATION_ID", "1")
os.environ.setdefault("API_KEY", "shared-api-key")
os.environ.setdefault("GUILD_ID", "1")
os.environ.setdefault("QUEUE_STATUS_CHANNEL_ID", "1")
os.environ.setdefault("QUEUE_CHANNEL_ID", "1")
os.environ.setdefault("RULES_CHANNEL_ID", "1")
os.environ.setdefault("CATEGORY_ID", "1")
os.environ.setdefault("EVENT_STAFF_ID", "1")
os.environ.setdefault("TRIAL_STAFF_ID", "1")
os.environ.setdefault("LOBBY_VC_ID", "1")
os.environ.setdefault("BOTS_ROLE_ID", "1")
os.environ.setdefault("RANKED_ADMIN_USERNAME", "RankedAdmin")
os.environ.setdefault("ORCHESTRATOR_TOKEN", "orch-token")

from orchestrator_client import OrchestratorAPIError, OrchestratorClient, OrchestratorTokens
from website_client import WebsiteClient
from cogs.server import ServerActions, build_status_embed, _opr_rows
from cogs.casual import CasualServers


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload or {}
        self.headers = {"Content-Type": "application/json"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self.payload

    async def text(self):
        return str(self.payload)


class FakeSession:
    def __init__(self, response):
        self.responses = list(response) if isinstance(response, list) else [response]
        self.requests = []
        self.closed = False

    def _next_response(self):
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self._next_response()

    def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        return self._next_response()


class FakeOrchestrator:
    def __init__(self):
        self.launch_payloads = []
        self.stop_calls = []
        self.sessions = [
            {"id": "sess-1", "port": 11115, "state": "running", "kind": "casual", "ownerDiscordUserId": "42"}
        ]

    async def launch_server(self, payload):
        self.launch_payloads.append(payload)
        return {"id": "sess-1", "port": 11115, "state": "running", "gameCode": payload["gameCode"]}

    async def stop_session(self, session_id, *, reason, actor=None):
        self.stop_calls.append((session_id, reason, actor))
        return {"id": session_id, "port": 11115}

    async def stop_session_by_port(self, port, *, reason, actor=None):
        self.stop_calls.append((port, reason, actor))
        return {"id": "sess-1", "port": port}

    async def list_servers(self, **filters):
        sessions = self.sessions
        if filters.get("ownerDiscordUserId"):
            sessions = [s for s in sessions if s.get("ownerDiscordUserId") == filters["ownerDiscordUserId"]]
        if filters.get("kind"):
            sessions = [s for s in sessions if s.get("kind") == filters["kind"]]
        return sessions

    async def get_session(self, session_id):
        return {
            "id": session_id,
            "port": 11115,
            "state": "running",
            "kind": "casual",
            "gameCode": "20",
            "players": [],
            "score": {"timer": "1:23", "redScore": 10, "blueScore": 8},
        }


class FakeWebsite:
    def __init__(self, active=True, active_session=None, games=None):
        self.active = active
        self.active_session = active_session
        self.games = games or [{"gameCode": "20", "name": "Push Back", "shortCode": "PB", "casualEnabled": True}]
        self.started = []
        self.stopped = []

    async def close(self):
        pass

    async def get_entitlement(self, discord_user_id):
        self.entitlement_user_id = discord_user_id
        return {"active": self.active, "active_session": self.active_session}

    async def get_casual_games(self):
        return self.games

    async def start_casual_server(self, **kwargs):
        self.started.append(kwargs)
        return {
            "id": "web-1",
            "status": "launching",
            "game": kwargs["game"],
            "game_code": kwargs["game_code"],
            "comment": kwargs["comment"],
            "host": "play.secondrobotics.org",
            "port": 11115,
            "password": kwargs["password"] or "generated",
            "allocated_minutes": kwargs["requested_minutes"],
        }

    async def stop_casual_server(self, website_session_id, *, reason):
        self.stopped.append((website_session_id, reason))
        return {"id": website_session_id, "status": "stopping", "stop_reason": reason}


class FakeResponseProxy:
    def __init__(self):
        self.deferred = False
        self.messages = []

    async def defer(self, **kwargs):
        self.deferred = True

    async def send_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))


class FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, *args, **kwargs):
        self.messages.append((args, kwargs))


class FakeUser:
    id = 42
    name = "Subscriber"
    display_name = "Subscriber"


class FakeInteraction:
    def __init__(self):
        self.id = 300
        self.user = FakeUser()
        self.guild_id = 100
        self.channel_id = 200
        self.response = FakeResponseProxy()
        self.followup = FakeFollowup()


class FakeBot:
    def __init__(self, server_actions=None):
        self.server_actions = server_actions

    def get_cog(self, name):
        if name == "ServerActions":
            return self.server_actions
        return None


class OrchestratorClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_launch_server_uses_bearer_token_and_payload(self):
        session = FakeSession(FakeResponse(201, {"id": "session-1", "port": 11115}))
        client = OrchestratorClient("http://orchestrator", OrchestratorTokens("token-a"), session=session)

        result = await client.launch_server({"kind": "ranked", "gameCode": "20"})

        self.assertEqual(result["id"], "session-1")
        method, url, kwargs = session.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "http://orchestrator/v1/servers")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer token-a")
        self.assertEqual(kwargs["json"]["kind"], "ranked")

    async def test_moderation_reads_use_moderation_token(self):
        session = FakeSession(FakeResponse(200, {"players": []}))
        client = OrchestratorClient(
            "http://orchestrator",
            OrchestratorTokens(default="default-token", moderation="mod-token"),
            session=session,
        )

        await client.get_players("session-1", moderation=True)

        _, _, kwargs = session.requests[0]
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer mod-token")

    async def test_admin_write_uses_admin_token(self):
        session = FakeSession(FakeResponse(200, {"id": "session-1", "port": 11115}))
        client = OrchestratorClient(
            "http://orchestrator",
            OrchestratorTokens(default="default-token", admin="admin-token"),
            session=session,
        )

        await client.kill_session("session-1", reason="hung")

        method, url, kwargs = session.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "http://orchestrator/v1/servers/session-1/kill")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer admin-token")

    async def test_http_error_raises_orchestrator_error_with_code(self):
        response = FakeResponse(409, {"error": {"code": "MATCH_ALREADY_RUNNING", "message": "Match exists."}})
        session = FakeSession(response)
        client = OrchestratorClient("http://orchestrator", OrchestratorTokens("token-a"), session=session)

        with self.assertRaises(OrchestratorAPIError) as cm:
            await client.launch_server({"kind": "ranked", "gameCode": "20"})

        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(cm.exception.code, "MATCH_ALREADY_RUNNING")


class WebsiteClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_casual_server_posts_to_secondwebsite_proxy(self):
        session = FakeSession(FakeResponse(200, {"success": True, "session": {"id": "web-1", "port": 11115}}))
        client = WebsiteClient("https://example.test", "site-token", session=session)

        result = await client.start_casual_server(
            owner_discord_id=42,
            game_code="20",
            game="Push Back",
            requested_minutes=30,
            comment="CasualPB",
            password="",
            guild_id=100,
            channel_id=200,
            interaction_id=300,
        )

        self.assertEqual(result["id"], "web-1")
        method, url, kwargs = session.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://example.test/api/subscriptions/server-sessions/start/")
        self.assertEqual(kwargs["headers"]["X-API-KEY"], "site-token")
        self.assertEqual(kwargs["json"]["owner_discord_id"], "42")
        self.assertEqual(kwargs["json"]["launch_source"], "discord_bot")
        self.assertEqual(kwargs["json"]["launch_context"]["discord_interaction_id"], "300")

    async def test_entitlement_failure_raises_website_error(self):
        session = FakeSession(FakeResponse(200, {"success": False, "message": "User is not linked."}))
        client = WebsiteClient("https://example.test", "site-token", session=session)

        with self.assertRaises(Exception) as cm:
            await client.get_entitlement(42)

        self.assertIn("User is not linked.", str(cm.exception))

    async def test_stop_casual_server_posts_to_secondwebsite_proxy(self):
        session = FakeSession(FakeResponse(200, {"success": True, "session": {"id": "web-1", "status": "stopping"}}))
        client = WebsiteClient("https://example.test", "site-token", session=session)

        result = await client.stop_casual_server("web-1")

        self.assertEqual(result["status"], "stopping")
        method, url, kwargs = session.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://example.test/api/subscriptions/server-sessions/web-1/stop/")
        self.assertEqual(kwargs["headers"]["X-API-KEY"], "site-token")


class ServerCommandPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_ranked_launch_payload_is_orchestrator_ranked_session(self):
        fake_orchestrator = FakeOrchestrator()
        actions = ServerActions(FakeBot(), orchestrator=fake_orchestrator)

        _, port, session_id, _ = await actions.start_server_process(
            "20",
            "RankedPB",
            "123",
            admin="RankedAdmin",
            kind="ranked",
            match_id="match-1",
            ranked_game_mode="Push Back 2v2",
            expected_discord_user_ids=["1", "2", "3", "4"],
        )

        self.assertEqual(port, 11115)
        self.assertEqual(session_id, "sess-1")
        payload = fake_orchestrator.launch_payloads[0]
        self.assertEqual(payload["kind"], "ranked")
        self.assertEqual(payload["matchId"], "match-1")
        self.assertEqual(payload["launchOptions"]["tournamentMode"], True)
        self.assertEqual(payload["launchOptions"]["minPlayers"], 4)

    async def test_admin_stop_uses_session_when_available(self):
        fake_orchestrator = FakeOrchestrator()
        actions = ServerActions(FakeBot(), orchestrator=fake_orchestrator)

        result = await actions.stop_server_process(11115, session_id="sess-1", reason="done")

        self.assertIn("shut down", result)
        self.assertEqual(fake_orchestrator.stop_calls[0][0], "sess-1")
        self.assertEqual(fake_orchestrator.stop_calls[0][1], "done")

    def test_status_embed_uses_orchestrator_score_and_players(self):
        embed = build_status_embed({
            "port": 11115,
            "gameCode": "20",
            "gameName": "Push Back",
            "players": [
                {"playerName": "RedOne", "position": "Red 1", "ipAddress": "10.0.0.1"},
                {"playerName": "BlueOne", "position": "Blue 1", "ipAddress": "10.0.0.2"},
            ],
            "score": {"timer": "0:42", "redScore": 15, "blueScore": 12},
        })

        self.assertEqual(embed.title, "Server Status for Port 11115")
        values = [field.value for field in embed.fields]
        self.assertIn("0:42", values)
        self.assertIn("RedOne - Red 1", values)
        self.assertIn("BlueOne - Blue 1", values)

    def test_orchestrator_split_opr_score_shape_is_supported(self):
        rows = _opr_rows({
            "redOpr": [{"playerName": "RedOne", "value": 42}],
            "blueOpr": [{"playerName": "BlueOne", "value": 37}],
        })

        self.assertEqual(rows, [("RedOne", 42), ("BlueOne", 37)])

    async def test_casual_start_uses_secondwebsite_proxy_not_orchestrator(self):
        fake_orchestrator = FakeOrchestrator()
        actions = ServerActions(FakeBot(), orchestrator=fake_orchestrator)
        bot = FakeBot(server_actions=actions)
        website = FakeWebsite()
        cog = CasualServers(bot, website=website)
        interaction = FakeInteraction()

        await CasualServers.casual_start.callback(cog, interaction, "20", 30, "", "")

        self.assertTrue(interaction.response.deferred)
        self.assertEqual(fake_orchestrator.launch_payloads, [])
        self.assertEqual(len(website.started), 1)
        payload = website.started[0]
        self.assertEqual(payload["owner_discord_id"], 42)
        self.assertEqual(payload["game_code"], "20")
        self.assertEqual(payload["requested_minutes"], 30)
        self.assertTrue(interaction.followup.messages)

    async def test_casual_start_does_not_launch_when_secondwebsite_denies_entitlement(self):
        fake_orchestrator = FakeOrchestrator()
        actions = ServerActions(FakeBot(), orchestrator=fake_orchestrator)
        bot = FakeBot(server_actions=actions)
        website = FakeWebsite(active=False)
        cog = CasualServers(bot, website=website)
        interaction = FakeInteraction()

        await CasualServers.casual_start.callback(cog, interaction, "20", 30, "", "")

        self.assertEqual(fake_orchestrator.launch_payloads, [])
        self.assertEqual(website.started, [])
        self.assertIn("does not see an active", interaction.followup.messages[0][0][0])

    async def test_casual_stop_uses_secondwebsite_proxy_not_orchestrator(self):
        fake_orchestrator = FakeOrchestrator()
        actions = ServerActions(FakeBot(), orchestrator=fake_orchestrator)
        bot = FakeBot(server_actions=actions)
        website = FakeWebsite(active_session={"id": "web-1", "status": "running", "comment": "CasualPB"})
        cog = CasualServers(bot, website=website)
        interaction = FakeInteraction()

        await CasualServers.casual_stop.callback(cog, interaction)

        self.assertTrue(interaction.response.deferred)
        self.assertEqual(fake_orchestrator.stop_calls, [])
        self.assertEqual(website.stopped[0], ("web-1", "discord_bot_stop"))
        embed = interaction.followup.messages[0][1]["embed"]
        self.assertEqual(embed.title, "Casual Server Stopping")


if __name__ == "__main__":
    unittest.main()


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_casual_status_refreshes_stale_cached_session(self):
        website = SimpleNamespace(get_entitlement=AsyncMock(return_value={"active_session": None}))
        cog = CasualServers(Mock(), website=website)
        cog.sessions_by_owner[42] = {"id": "old", "status": "running"}
        self.assertIsNone(await cog._get_active_website_session(42))
        website.get_entitlement.assert_awaited_once_with(42)

    async def test_reachable_orchestrator_without_old_ranked_session_cleans_discord(self):
        ranked = SimpleNamespace(find_match_by_session_id=Mock(return_value=object()),
                                 handle_orchestrator_inactivity_expired=AsyncMock())
        cog = ServerActions.__new__(ServerActions)
        cog.bot = SimpleNamespace(get_cog=lambda name: ranked)
        cog.orchestrator = SimpleNamespace(list_servers=AsyncMock(return_value=[]))
        cog.server_sessions_by_port = {11115: "old-ranked"}
        await cog._reconcile_ranked_sessions()
        ranked.handle_orchestrator_inactivity_expired.assert_awaited_once_with({"sessionId": "old-ranked"})

    async def test_orchestrator_outage_does_not_clear_ranked_match(self):
        ranked = SimpleNamespace(handle_orchestrator_inactivity_expired=AsyncMock())
        cog = ServerActions.__new__(ServerActions)
        cog.bot = SimpleNamespace(get_cog=lambda name: ranked)
        cog.orchestrator = SimpleNamespace(list_servers=AsyncMock(side_effect=OrchestratorAPIError(0, "offline", "offline")))
        cog.server_sessions_by_port = {11115: "old-ranked"}
        with self.assertRaises(OrchestratorAPIError):
            await cog._reconcile_ranked_sessions()
        ranked.handle_orchestrator_inactivity_expired.assert_not_awaited()
