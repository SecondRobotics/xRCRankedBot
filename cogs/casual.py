import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import (
    API_KEY,
    GUILD_ID,
    SECONDWEBSITE_BASE_URL,
    server_games,
)
from website_client import WebsiteAPIError, WebsiteClient
from game_selection import game_autocomplete, resolve_game_id

logger = logging.getLogger("discord")


def _session_is_active(session: Optional[dict]) -> bool:
    if not session:
        return False
    return session.get("status") in {"launching", "starting", "running", "ready"} or session.get("orchestrator_state") in {
        "requested",
        "starting",
        "running",
    }


def _format_connection(session: dict) -> str:
    host = session.get("host") or "pending"
    port = session.get("port") or "pending"
    return f"||Host: {host} Port: {port}||"


def _casual_session_embed(title: str, session: dict, *, color: discord.Color) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=f"Server `{session.get('comment', session.get('game', 'Casual Server'))}` is {session.get('status', 'pending')}.",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Game", value=session.get("game") or session.get("game_code") or "Unknown", inline=True)
    embed.add_field(name="Connection", value=_format_connection(session), inline=False)
    if session.get("password"):
        embed.add_field(name="Password", value=f"||{session['password']}||", inline=True)
    if session.get("allocated_minutes") or session.get("requested_minutes"):
        embed.add_field(
            name="Minutes",
            value=str(session.get("allocated_minutes") or session.get("requested_minutes")),
            inline=True,
        )
    if session.get("expires_at"):
        embed.add_field(name="Expires", value=session["expires_at"], inline=False)
    return embed


class CasualServers(commands.Cog):
    def __init__(self, bot, website: Optional[WebsiteClient] = None):
        self.bot = bot
        self.website = website or WebsiteClient(
            SECONDWEBSITE_BASE_URL,
            API_KEY,
        )
        self.sessions_by_owner: dict[int, dict] = {}

    async def cog_unload(self):
        await self.website.close()

    async def _get_active_website_session(self, user_id: int) -> Optional[dict]:
        entitlement = await self.website.get_entitlement(user_id)
        active_session = entitlement.get("active_session")
        if _session_is_active(active_session):
            self.sessions_by_owner[user_id] = active_session
            return active_session
        return None

    @app_commands.autocomplete(game=game_autocomplete)
    @app_commands.command(name="casual_start", description="Start a subscriber casual xRC server")
    async def casual_start(
        self,
        interaction: discord.Interaction,
        game: str,
        minutes: app_commands.Range[int, 5, 1440] = 60,
        password: str = "",
        comment: str = "",
    ):
        logger.info("%s called /casual_start", interaction.user.name)
        await interaction.response.defer(ephemeral=True)

        game = resolve_game_id(game)
        if game is None:
            await interaction.followup.send("Choose a supported game from autocomplete.", ephemeral=True)
            return
        try:
            entitlement = await self.website.get_entitlement(interaction.user.id)
        except WebsiteAPIError as e:
            logger.warning("SecondWebsite entitlement check failed: %s", e)
            await interaction.followup.send(f"⚠ Casual server check failed: {e}", ephemeral=True)
            return

        if not entitlement.get("active"):
            await interaction.followup.send(
                "⚠ SecondWebsite does not see an active casual server subscription for your Discord account.",
                ephemeral=True,
            )
            return

        active_session = entitlement.get("active_session")
        if active_session:
            self.sessions_by_owner[interaction.user.id] = active_session
            embed = _casual_session_embed("Casual Server Already Active", active_session, color=discord.Color.orange())
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        try:
            casual_games = await self.website.get_casual_games()
        except WebsiteAPIError as e:
            logger.warning("SecondWebsite casual game lookup failed: %s", e)
            await interaction.followup.send(f"⚠ Could not load casual games from SecondWebsite: {e}", ephemeral=True)
            return

        game_record = next((g for g in casual_games if str(g.get("gameCode")) == str(game) and g.get("casualEnabled", True)), None)
        if not game_record:
            await interaction.followup.send("⚠ SecondWebsite does not currently allow casual servers for that game.", ephemeral=True)
            return

        game_name = game_record.get("name") or next((name for name, code in server_games.items() if code == str(game)), str(game))
        launch_comment = (comment or f"Casual{game_record.get('shortCode') or game}")[:120]

        try:
            session = await self.website.start_casual_server(
                owner_discord_id=interaction.user.id,
                game_code=game,
                game=game_name,
                requested_minutes=minutes,
                comment=launch_comment,
                password=password,
                guild_id=interaction.guild_id,
                channel_id=interaction.channel_id,
                interaction_id=interaction.id,
            )
        except WebsiteAPIError as e:
            logger.warning("SecondWebsite casual launch failed: %s", e)
            await interaction.followup.send(f"⚠ Casual server launch failed: {e}", ephemeral=True)
            return

        self.sessions_by_owner[interaction.user.id] = session
        await interaction.followup.send(
            embed=_casual_session_embed("Casual Server Started", session, color=discord.Color.green()),
            ephemeral=True,
        )

    @app_commands.command(name="casual_status", description="Show your active casual xRC server")
    async def casual_status(self, interaction: discord.Interaction):
        logger.info("%s called /casual_status", interaction.user.name)
        await interaction.response.defer(ephemeral=True)
        try:
            session = await self._get_active_website_session(interaction.user.id)
        except WebsiteAPIError as e:
            await interaction.followup.send(f"⚠ Could not fetch casual server status: {e}", ephemeral=True)
            return

        if not session:
            await interaction.followup.send("You do not have an active casual server.", ephemeral=True)
            return

        await interaction.followup.send(
            embed=_casual_session_embed("Casual Server Status", session, color=discord.Color.blue()),
            ephemeral=True,
        )

    @app_commands.command(name="casual_stop", description="Stop your active casual xRC server")
    async def casual_stop(self, interaction: discord.Interaction):
        logger.info("%s called /casual_stop", interaction.user.name)
        await interaction.response.defer(ephemeral=True)

        try:
            session = await self._get_active_website_session(interaction.user.id)
            if not session:
                await interaction.followup.send("You do not have an active casual server.", ephemeral=True)
                return

            stopped = await self.website.stop_casual_server(session["id"], reason="discord_bot_stop")
            self.sessions_by_owner.pop(interaction.user.id, None)
            await interaction.followup.send(
                embed=_casual_session_embed("Casual Server Stopping", stopped or session, color=discord.Color.orange()),
                ephemeral=True,
            )
        except WebsiteAPIError as e:
            await interaction.followup.send(f"⚠ Could not stop casual server: {e}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    cog = CasualServers(bot)
    guild = await bot.fetch_guild(GUILD_ID)
    assert guild is not None
    await bot.add_cog(cog, guilds=[guild])
