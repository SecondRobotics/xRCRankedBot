import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands
from game_selection import game_autocomplete, resolve_game_id

from config import (
    GUILD_ID,
    ORCHESTRATOR_ADMIN_TOKEN,
    ORCHESTRATOR_BASE_URL,
    ORCHESTRATOR_MODERATION_TOKEN,
    ORCHESTRATOR_RELAY_CHAT_TO_DISCORD,
    ORCHESTRATOR_TOKEN,
    PORTS,
    QUEUE_STATUS_CHANNEL_ID,
    default_game_players,
    server_games,
    server_restart_modes,
)
from orchestrator_client import (
    OrchestratorAPIError,
    OrchestratorClient,
    OrchestratorTokens,
    SERVICE_ACTOR,
    discord_actor,
)

logger = logging.getLogger("discord")

CHAT_LOG_CHANNEL_ID = 1505392192724799528
ports_choices = [Choice(name=str(port), value=port) for port in PORTS]
ACTIVE_STATES = {"requested", "starting", "running", "stopping"}


def _game_name(game_code: str) -> str:
    return next((name for name, number in server_games.items() if number == str(game_code)), str(game_code))


def _score_value(score: Optional[dict], key: str, fallback: str = "0") -> str:
    if not score:
        return fallback
    value = score.get(key)
    return fallback if value is None else str(value)


def _players_by_alliance(players: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    red = [p for p in players if str(p.get("position", "")).lower().startswith("red")]
    blue = [p for p in players if str(p.get("position", "")).lower().startswith("blue")]
    spectators = [p for p in players if p not in red and p not in blue]
    return red, blue, spectators


def _player_name(player: dict) -> str:
    return player.get("playerName") or player.get("name") or "Unknown"


def _player_ip(player: dict) -> Optional[str]:
    return player.get("ipAddress") or player.get("ip")


def _format_player_lines(players: list[dict], *, include_ip: bool = False) -> str:
    if not players:
        return "None"
    lines = []
    for player in players:
        line = f"{_player_name(player)} - {player.get('position', 'Unknown')}"
        ip = _player_ip(player)
        if include_ip and ip and ip != "redacted":
            line = f"{line}\nIP: {ip}"
        lines.append(line)
    return "\n".join(lines)


def _opr_rows(score: dict) -> list[tuple[str, float]]:
    if score.get("opr"):
        return [(name, float(value)) for name, value in score["opr"].items()]

    rows = []
    for entry in (score.get("redOpr") or []) + (score.get("blueOpr") or []):
        if "playerName" not in entry or "value" not in entry:
            continue
        rows.append((str(entry["playerName"]), float(entry["value"])))
    return rows


def build_status_embed(session: dict, *, title_prefix: str = "Server Status") -> discord.Embed:
    port = session.get("port", "Unknown")
    score = session.get("score") or {}
    players = session.get("players") or []
    red, blue, _ = _players_by_alliance(players)

    embed = discord.Embed(
        title=f"{title_prefix} for Port {port}",
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Timer", value=_score_value(score, "timer", "N/A"), inline=True)
    embed.add_field(name="Red Alliance", value=_format_player_lines(red), inline=True)
    embed.add_field(name="Blue Alliance", value=_format_player_lines(blue), inline=True)
    embed.add_field(name="Red Score", value=_score_value(score, "redScore"), inline=True)
    embed.add_field(name="Blue Score", value=_score_value(score, "blueScore"), inline=True)
    embed.add_field(name="Game Type", value=session.get("gameName") or _game_name(session.get("gameCode")), inline=True)
    return embed


class ServerActions(commands.Cog):
    def __init__(self, bot, orchestrator: Optional[OrchestratorClient] = None):
        self.bot = bot
        self.orchestrator = orchestrator or OrchestratorClient(
            ORCHESTRATOR_BASE_URL,
            OrchestratorTokens(
                default=ORCHESTRATOR_TOKEN,
                moderation=ORCHESTRATOR_MODERATION_TOKEN,
                admin=ORCHESTRATOR_ADMIN_TOKEN,
            ),
        )
        self.server_sessions_by_port: Dict[int, str] = {}
        self.server_metadata: Dict[int, dict] = {}
        self.watch_tasks: Dict[int, asyncio.Task] = {}
        self.watch_messages: Dict[int, discord.Message] = {}
        self.score_posted: Dict[str, bool] = {}
        self._events_task: Optional[asyncio.Task] = None
        self._last_event_id: Optional[str] = None
        self.chat_discord_buffer: list[str] = []
        self.chat_header_posted: set[int] = set()

    async def cog_load(self):
        self._events_task = asyncio.create_task(self._consume_orchestrator_events())
        if ORCHESTRATOR_RELAY_CHAT_TO_DISCORD:
            asyncio.create_task(self._flush_chat_buffer())

    async def cog_unload(self):
        if self._events_task:
            self._events_task.cancel()
        for task in self.watch_tasks.values():
            task.cancel()
        await self.orchestrator.close()

    def _launch_options(
        self,
        *,
        restart_mode: int,
        frame_rate: int,
        update_time: int,
        tournament_mode: bool,
        start_when_ready: bool,
        register: bool,
        spectators: int,
        min_players: int,
        restart_all: bool,
    ) -> dict:
        return {
            "frameRate": frame_rate,
            "updateTime": update_time,
            "tournamentMode": tournament_mode,
            "register": register,
            "spectators": spectators,
            "startWhenReady": start_when_ready,
            "restartAll": restart_all,
            "restartMode": str(restart_mode),
            "netStats": False,
            "profiling": False,
            "minPlayers": min_players,
        }

    async def start_server_process(
        self,
        game: str,
        comment: str,
        password: str = "",
        admin: str = "Admin",
        restart_mode: int = -1,
        frame_rate: int = 60,
        update_time: int = 20,
        tournament_mode: bool = True,
        start_when_ready: bool = True,
        register: bool = True,
        spectators: int = 4,
        min_players: int = -1,
        restart_all: bool = True,
        timeout: int = -1,
        *,
        kind: str = "admin",
        actor: Optional[dict] = None,
        match_id: Optional[str] = None,
        ranked_game_mode: Optional[str] = None,
        expected_discord_user_ids: Optional[list[str]] = None,
        discord_channel_ids: Optional[dict] = None,
        owner_discord_user_id: Optional[str] = None,
        website_server_session_id: Optional[str] = None,
        requested_minutes: Optional[int] = None,
        max_minutes: Optional[int] = None,
    ) -> tuple[str, int, Optional[str], Optional[dict]]:
        if restart_mode == -1:
            restart_mode = server_restart_modes.get(str(game), 1)
        if min_players == -1:
            min_players = default_game_players.get(str(game), 4)

        payload = {
            "kind": kind,
            "gameCode": str(game),
            "comment": comment,
            "password": password,
            "adminUsername": admin,
            "launchSource": "discord_bot",
            "actor": actor or SERVICE_ACTOR,
            "launchOptions": self._launch_options(
                restart_mode=restart_mode,
                frame_rate=frame_rate,
                update_time=update_time,
                tournament_mode=tournament_mode,
                start_when_ready=start_when_ready,
                register=register,
                spectators=spectators,
                min_players=min_players,
                restart_all=restart_all,
            ),
        }

        if timeout > 0:
            payload["timeoutMinutes"] = timeout
        if kind == "ranked":
            payload.update({
                "matchId": match_id,
                "rankedGameMode": ranked_game_mode,
                "minPlayers": min_players,
                "expectedDiscordUserIds": expected_discord_user_ids or [],
                "discordChannelIds": discord_channel_ids or {},
            })
        if kind == "casual":
            payload.update({
                "websiteServerSessionId": website_server_session_id,
                "ownerDiscordUserId": owner_discord_user_id,
                "requestedMinutes": requested_minutes,
                "maxMinutes": max_minutes,
            })

        try:
            session = await self.orchestrator.launch_server({k: v for k, v in payload.items() if v is not None})
        except OrchestratorAPIError as e:
            return f"⚠ Orchestrator launch failed: {e}", -1, None, None

        port = int(session["port"])
        session_id = session["id"]
        self.server_sessions_by_port[port] = session_id
        self.server_metadata[port] = session
        return f"✅ Launched server '{comment}' on port {port}", port, session_id, session

    async def stop_server_process(
        self,
        port: int,
        *,
        session_id: Optional[str] = None,
        reason: str = "discord stop requested",
        actor: Optional[dict] = None,
    ) -> str:
        try:
            if session_id:
                session = await self.orchestrator.stop_session(session_id, reason=reason, actor=actor)
            else:
                session = await self.orchestrator.stop_session_by_port(port, reason=reason, actor=actor)
        except OrchestratorAPIError as e:
            return f"⚠ Server on port {port} could not be stopped: {e}"

        self.server_sessions_by_port.pop(port, None)
        self.server_metadata.pop(port, None)
        await self._delete_watch_message(port)
        stopped_port = session.get("port", port) if isinstance(session, dict) else port
        return f"✅ Server on port {stopped_port} shut down"

    async def _create_watch_message(self, port: int, game_type: str):
        channel = self.bot.get_channel(QUEUE_STATUS_CHANNEL_ID)
        if channel:
            watch_message = await channel.send(f"🔔 **Server Started** on port `{port}`\n**Game Type:** {game_type}")
            self.watch_messages[port] = watch_message
            task = self.bot.loop.create_task(self.server_watch_task(port, watch_message))
            self.watch_tasks[port] = task

    async def _delete_watch_message(self, port: int):
        watch_message = self.watch_messages.pop(port, None)
        if watch_message:
            try:
                await watch_message.delete()
            except discord.NotFound:
                logger.warning("Watch message for port %s not found.", port)
            except Exception as e:
                logger.error("Error deleting watch message for port %s: %s", port, e)

        task = self.watch_tasks.pop(port, None)
        if task:
            task.cancel()

    async def server_watch_task(self, port: int, message: discord.Message):
        while True:
            try:
                session = await self.orchestrator.get_session_by_port(port)
                if session.get("state") not in ACTIVE_STATES:
                    break
                await message.edit(embed=build_status_embed(session, title_prefix="Server Watch"))
            except OrchestratorAPIError as e:
                logger.warning("Stopping watch for port %s: %s", port, e)
                break
            except discord.HTTPException as e:
                logger.error("Failed to update watch embed for port %s: %s", port, e)
                break
            await asyncio.sleep(5)

    @app_commands.autocomplete(game=game_autocomplete)
    @app_commands.command(description="Launches a new instance of xRC Sim server", name="launchserver")
    @app_commands.checks.has_any_role("Event Staff")
    async def launch_server(
        self,
        interaction: discord.Interaction,
        game: str,
        comment: str,
        password: str = "",
        admin: str = "Admin",
        restart_mode: int = -1,
        frame_rate: int = 120,
        update_time: int = 10,
        tournament_mode: bool = True,
        start_when_ready: bool = True,
        register: bool = True,
        spectators: int = 4,
        min_players: int = -1,
        restart_all: bool = True,
        timeout: int = -1,
        silent: bool = False,
    ):
        logger.info("%s called /launchserver", interaction.user.name)
        game = resolve_game_id(game)
        if game is None:
            await interaction.response.send_message("Choose a supported game from autocomplete.", ephemeral=True)
            return
        await interaction.response.defer()

        result, port, _, _ = await self.start_server_process(
            game,
            comment,
            password,
            admin,
            restart_mode,
            frame_rate,
            update_time,
            tournament_mode,
            start_when_ready,
            register,
            spectators,
            min_players,
            restart_all,
            timeout,
            kind="admin",
            actor=discord_actor(interaction.user),
        )

        if not silent and port != -1:
            asyncio.create_task(self._create_watch_message(port, _game_name(game)))

        await interaction.followup.send(result)

    @app_commands.command(description="Shutdown a running xRC Sim server", name="landserver")
    @app_commands.checks.has_any_role("Event Staff")
    @app_commands.choices(port=ports_choices)
    async def land_server(self, interaction: discord.Interaction, port: int):
        logger.info("%s called /landserver", interaction.user.name)
        result = await self.stop_server_process(port, actor=discord_actor(interaction.user))
        await interaction.response.send_message(result)

    @app_commands.command(description="Restart a running xRC Sim server", name="restartserver")
    @app_commands.checks.has_any_role("Event Staff")
    @app_commands.choices(port=ports_choices)
    async def restart_server(self, interaction: discord.Interaction, port: int, reason: str = "discord restart requested"):
        logger.info("%s called /restartserver", interaction.user.name)
        await interaction.response.defer()
        try:
            session = await self.orchestrator.get_session_by_port(port)
            restarted = await self.orchestrator.restart_session(session["id"], reason=reason, actor=discord_actor(interaction.user))
            self.server_sessions_by_port[int(restarted["port"])] = restarted["id"]
            self.server_metadata[int(restarted["port"])] = restarted
            await interaction.followup.send(f"✅ Restarted server on port {restarted['port']}")
        except OrchestratorAPIError as e:
            await interaction.followup.send(f"⚠ Restart failed: {e}", ephemeral=True)

    @app_commands.command(description="Force kill a running xRC Sim server", name="killserver")
    @app_commands.checks.has_any_role("Admin")
    @app_commands.choices(port=ports_choices)
    async def kill_server(self, interaction: discord.Interaction, port: int, reason: str):
        logger.info("%s called /killserver", interaction.user.name)
        await interaction.response.defer(ephemeral=True)
        try:
            session = await self.orchestrator.get_session_by_port(port)
            await self.orchestrator.kill_session(session["id"], reason=reason, actor=discord_actor(interaction.user))
            self.server_sessions_by_port.pop(port, None)
            self.server_metadata.pop(port, None)
            await self._delete_watch_message(port)
            await interaction.followup.send(f"✅ Killed server on port {port}", ephemeral=True)
        except OrchestratorAPIError as e:
            await interaction.followup.send(f"⚠ Kill failed: {e}", ephemeral=True)

    @app_commands.command(description="Lists the running server instances", name="listservers")
    @app_commands.checks.has_any_role("Event Staff")
    async def list_servers(self, interaction: discord.Interaction):
        logger.info("%s called /listservers", interaction.user.name)
        try:
            sessions = await self.orchestrator.list_servers(active="true")
        except OrchestratorAPIError as e:
            await interaction.response.send_message(f"⚠ Could not list servers: {e}", ephemeral=True)
            return

        if not sessions:
            await interaction.response.send_message("⚠ No servers are running")
            return

        lines = [
            f"Port {s.get('port')}: {s.get('gameName') or _game_name(s.get('gameCode'))} - '{s.get('comment', 'N/A')}' ({s.get('kind')}/{s.get('state')})"
            for s in sessions
        ]
        await interaction.response.send_message("Running servers:\n" + "\n".join(lines))

    @app_commands.command(description="Show live performance stats for running servers", name="serverstats")
    @app_commands.checks.has_any_role("Event Staff")
    async def server_stats(self, interaction: discord.Interaction):
        logger.info("%s called /serverstats", interaction.user.name)
        await interaction.response.defer()

        try:
            overview, sessions = await asyncio.gather(
                self.orchestrator.admin_overview(),
                self.orchestrator.list_servers(active="true"),
            )
        except OrchestratorAPIError as e:
            await interaction.followup.send(f"⚠ Could not fetch server stats: {e}", ephemeral=True)
            return

        if not sessions:
            await interaction.followup.send("⚠ No servers are currently running.")
            return

        detail_tasks = [
            self.orchestrator.get_session(session["id"]) if session.get("id") else asyncio.sleep(0, result=session)
            for session in sessions
        ]
        session_details = await asyncio.gather(*detail_tasks, return_exceptions=True)
        detailed_sessions = [
            detail if isinstance(detail, dict) else session
            for session, detail in zip(sessions, session_details)
        ]

        embed = discord.Embed(title="Server Performance", color=0x34DCEB, timestamp=datetime.now(timezone.utc))
        embed.description = (
            f"Running: {overview.get('runningServerCount', len(sessions))} | "
            f"Available ports: {', '.join(map(str, overview.get('availablePorts', []))) or 'N/A'}"
        )

        for session in detailed_sessions:
            players = session.get("players") or []
            player_count = len(players) if players else session.get("playerCount", "N/A")
            embed.add_field(
                name=f"Port {session.get('port')} - {session.get('gameName') or _game_name(session.get('gameCode'))}",
                value=(
                    f"**Comment:** {session.get('comment', 'N/A')}\n"
                    f"**State:** {session.get('state', 'unknown')}\n"
                    f"**Kind:** {session.get('kind', 'unknown')}\n"
                    f"**Players:** {player_count}\n"
                    f"**Last Activity:** {session.get('lastActivityAt') or 'N/A'}"
                ),
                inline=False,
            )

        await interaction.followup.send(embed=embed)

    @app_commands.command(description="Retrieve server data once", name="server_peep")
    @app_commands.choices(port=ports_choices)
    async def server_peep(self, interaction: discord.Interaction, port: int):
        logger.info("%s called /server_peep for port %s", interaction.user.name, port)
        try:
            session = await self.orchestrator.get_session_by_port(port)
        except OrchestratorAPIError as e:
            await interaction.response.send_message(f"⚠ Unable to retrieve data for port {port}: {e}", ephemeral=True)
            return

        embed = build_status_embed(session)
        embed.set_footer(
            text=f"Requested by {interaction.user.display_name}",
            icon_url=interaction.user.avatar.url if interaction.user.avatar else None,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Watch server data and update every 5 seconds", name="server_watch")
    @app_commands.choices(port=ports_choices)
    async def server_watch(self, interaction: discord.Interaction, port: int):
        logger.info("%s called /server_watch for port %s", interaction.user.name, port)
        try:
            session = await self.orchestrator.get_session_by_port(port)
        except OrchestratorAPIError as e:
            await interaction.response.send_message(f"⚠ No active server on port {port}: {e}", ephemeral=True)
            return

        if session.get("state") not in ACTIVE_STATES:
            await interaction.response.send_message(f"⚠ No active server on port {port}.", ephemeral=True)
            return

        await interaction.response.send_message(embed=build_status_embed(session, title_prefix="Watching Server Status"))
        self.watch_tasks[port] = self.bot.loop.create_task(
            self.server_watch_task(port, await interaction.original_response())
        )

    @app_commands.command(description="Stops watching server data", name="stop_server_watch")
    @app_commands.choices(port=ports_choices)
    @app_commands.checks.has_any_role("Event Staff")
    async def stop_server_watch(self, interaction: discord.Interaction, port: int):
        logger.info("%s called /stop_server_watch for port %s", interaction.user.name, port)
        task = self.watch_tasks.pop(port, None)
        if not task:
            await interaction.response.send_message(f"⚠ No watch task running for port {port}.", ephemeral=True)
            return
        task.cancel()
        await interaction.response.send_message(f"✅ Stopped watching server on port {port}.")

    @app_commands.command(description="Investigate server players", name="investigate")
    @app_commands.checks.has_any_role("Admin", "Mod")
    @app_commands.choices(port=ports_choices)
    async def investigate(self, interaction: discord.Interaction, port: int, public: bool = False):
        logger.info("%s called /investigate for port %s", interaction.user.name, port)
        try:
            session = await self.orchestrator.get_session_by_port(port, moderation=not public)
        except OrchestratorAPIError as e:
            await interaction.response.send_message(f"⚠ Could not inspect players: {e}", ephemeral=True)
            return

        players = session.get("players") or []
        if not players:
            await interaction.response.send_message("No active players on this server.", ephemeral=True)
            return

        red, blue, spectators = _players_by_alliance(players)
        embed = discord.Embed(
            title=f"Players on Server Port {port}",
            color=discord.Color.purple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="🔴 Red Alliance", value=_format_player_lines(red, include_ip=not public), inline=False)
        embed.add_field(name="🔵 Blue Alliance", value=_format_player_lines(blue, include_ip=not public), inline=False)
        embed.add_field(name="👁️ Spectators", value=_format_player_lines(spectators, include_ip=not public), inline=False)
        embed.set_footer(
            text=f"Requested by {interaction.user.display_name}",
            icon_url=interaction.user.avatar.url if interaction.user.avatar else None,
        )
        await interaction.response.send_message(embed=embed, ephemeral=not public)

    async def _consume_orchestrator_events(self):
        await self.bot.wait_until_ready()
        types = ["match_timer_finished", "ranked_inactivity_warning", "ranked_inactivity_expired", "server_stopped"]
        if ORCHESTRATOR_RELAY_CHAT_TO_DISCORD:
            types.append("chat_message")

        while not self.bot.is_closed():
            try:
                events = await self.orchestrator.get_events(
                    after_event_id=self._last_event_id,
                    types=types,
                    wait_ms=25000,
                )
                for event in events:
                    await self._handle_orchestrator_event(event)
                    self._last_event_id = str(event.get("id"))
                await self._reconcile_ranked_sessions()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Orchestrator event consumer error: %s", e)
                await asyncio.sleep(5)

    async def _reconcile_ranked_sessions(self):
        ranked = self.bot.get_cog("Ranked")
        if not ranked:
            return
        # Reachability failure raises; never clear Discord matches on an outage.
        active = await self.orchestrator.list_servers(kind="ranked", active=True)
        live_ids = {session["id"] for session in active}
        for session_id in list(self.server_sessions_by_port.values()):
            match = ranked.find_match_by_session_id(session_id)
            if match and session_id not in live_ids:
                await ranked.handle_orchestrator_inactivity_expired({"sessionId": session_id})

    async def _handle_orchestrator_event(self, event: dict):
        event_type = event.get("type")
        if event_type == "server_stopped":
            await self._reconcile_ranked_sessions()
        elif event_type == "match_timer_finished":
            await self._handle_match_timer_finished(event)
        elif event_type == "ranked_inactivity_warning":
            ranked = self.bot.get_cog("Ranked")
            if ranked:
                await ranked.handle_orchestrator_inactivity_warning(event)
        elif event_type == "ranked_inactivity_expired":
            ranked = self.bot.get_cog("Ranked")
            if ranked:
                await ranked.handle_orchestrator_inactivity_expired(event)
        elif event_type == "chat_message" and ORCHESTRATOR_RELAY_CHAT_TO_DISCORD:
            await self._handle_chat_message(event)

    async def _handle_match_timer_finished(self, event: dict):
        session_id = event.get("sessionId")
        if not session_id or self.score_posted.get(session_id):
            return

        ranked = self.bot.get_cog("Ranked")
        if not ranked:
            return

        match = ranked.find_match_by_session_id(session_id) or ranked.find_match_by_port(event.get("port"))
        if not match or not match.password_channel_id:
            return

        try:
            score = await self.orchestrator.get_latest_score(session_id)
        except OrchestratorAPIError as e:
            logger.error("Could not fetch score for session %s: %s", session_id, e)
            return

        await self._post_match_scores(event.get("port"), score or {}, match)
        self.score_posted[session_id] = True

    async def _post_match_scores(self, port: int, score: dict, match):
        try:
            channel = self.bot.get_channel(match.password_channel_id)
            if not channel:
                return
            red = int(float(score.get("redScore", 0)))
            blue = int(float(score.get("blueScore", 0)))
            if red > blue:
                result = "🟥 Red wins"
                color = discord.Color(0xE74C3C)
            elif blue > red:
                result = "🟦 Blue wins"
                color = discord.Color(0x3498DB)
            else:
                result = "🤝 Tie"
                color = discord.Color(0x95A5A6)

            embed = discord.Embed(
                title=f"🏁 {match.full_game_name} - Match Over",
                description=f"## 🟥 `{red:>3}` - `{blue:<3}` 🟦\n**{result}**",
                color=color,
                timestamp=datetime.now(timezone.utc),
            )

            opr = _opr_rows(score)
            if opr:
                rows = [f"{name:<20} {value:>6g}" for name, value in sorted(opr, key=lambda item: -item[1])]
                embed.add_field(name="OPR", value="```\n" + "\n".join(rows[:20]) + "\n```", inline=False)

            await channel.send(embed=embed)
        except Exception as e:
            logger.error("Error posting match scores for port %s: %s", port, e)

    async def _handle_chat_message(self, event: dict):
        port = int(event.get("port") or 0)
        data = event.get("data") or {}
        username = data.get("playerName", "Unknown")
        message = data.get("message") or event.get("message") or ""
        session = self.server_metadata.get(port) or {}
        game_name = session.get("gameName") or _game_name(session.get("gameCode", "Unknown"))
        game_number = str(session.get("gameCode", ""))
        alliance_size = default_game_players.get(game_number, 4) // 2
        game_format = f"{alliance_size}v{alliance_size}"
        self._buffer_chat_message(port, game_name, game_format, username, message)

    def _buffer_chat_message(self, port: int, game_name: str, game_format: str, username: str, message: str):
        reset = "\x1b[0m"
        dim_cyan = "\x1b[2;36m"
        bold_yellow = "\x1b[1;33m"
        bold_green = "\x1b[1;32m"

        if port not in self.chat_header_posted:
            self.chat_header_posted.add(port)
            sep = "-" * 44
            self.chat_discord_buffer.append(
                f"{bold_green}{sep}\n  {game_name} {game_format}  |  Port {port}\n{sep}{reset}"
            )

        safe_message = message.replace("```", "`\u200b`\u200b`")
        self.chat_discord_buffer.append(
            f"{dim_cyan}[{port} | {game_name} {game_format}]{reset} {bold_yellow}{username}{reset}: {safe_message}"
        )

    async def _flush_chat_buffer(self):
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(CHAT_LOG_CHANNEL_ID)
        while True:
            await asyncio.sleep(2)
            if not self.chat_discord_buffer or not channel:
                continue
            lines, self.chat_discord_buffer = self.chat_discord_buffer, []
            chunks = []
            current = []
            current_len = 0
            for line in lines:
                if current_len + len(line) + 1 > 1900:
                    chunks.append(current)
                    current = []
                    current_len = 0
                current.append(line)
                current_len += len(line) + 1
            if current:
                chunks.append(current)
            for chunk in chunks:
                try:
                    await channel.send("```ansi\n" + "\n".join(chunk) + "\n```")
                except Exception as e:
                    logger.error("Error flushing chat buffer to Discord: %s", e)


async def setup(bot: commands.Bot) -> None:
    cog = ServerActions(bot)
    guild = await bot.fetch_guild(GUILD_ID)
    assert guild is not None
    await bot.add_cog(cog, guilds=[guild])
