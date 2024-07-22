# server.py

import os
import subprocess
import logging
from datetime import datetime
from typing import Dict
import discord
from io import TextIOWrapper
from discord import app_commands
from discord.ext import commands
from discord.app_commands import Choice
from config import server_games, server_restart_modes, server_games_choices, PORTS, server_game_settings, short_codes, game_logos, default_game_players, GUILD_ID

logger = logging.getLogger('discord')

servers_active: Dict[int, subprocess.Popen] = {}
log_files: Dict[int, TextIOWrapper] = {}
last_active: Dict[int, datetime] = {}

# Define other constants here
SERVER_PATH = "./server/xRC Simulator.x86_64"
SERVER_LOGS_DIR = "./server_logs/"

def start_server_process(game: str, comment: str, password: str = "", admin: str = "Admin",
                         restart_mode: int = -1, frame_rate: int = 120, update_time: int = 10,
                         tournament_mode: bool = True, start_when_ready: bool = True,
                         register: bool = True, spectators: int = 4, min_players: int = -1,
                         restart_all: bool = True):
    if not os.path.exists(SERVER_PATH):
        return "⚠ xRC Sim server not found, use `/update` to update", -1

    if len(servers_active) >= len(PORTS):
        return "⚠ The maximum number of servers are already running", -1

    port = -1
    for port in PORTS:
        if port not in servers_active:
            break

    if port == -1:
        return "⚠ Could not find a port to run the server on", -1

    logger.info(f"Launching server on port {port}")

    game_settings = server_game_settings.get(game, "")
    if restart_mode == -1:
        restart_mode = server_restart_modes.get(game, 1)

    if min_players == -1:
        min_players = default_game_players.get(game, 4)

    f = open(f"{SERVER_LOGS_DIR}{port}.log", "a")
    log_files[port] = f
    f.write(f"Server started at {datetime.now()}")

    command = [
        SERVER_PATH, "-batchmode", "-nographics",
        f"RouterPort={port}", f"Port={port}", f"Game={game}",
        f"GameOption={restart_mode}", f"FrameRate={frame_rate}",
        f"Tmode={'On' if tournament_mode else 'Off'}",
        f"Register={'On' if register else 'Off'}",
        f"Spectators={spectators}", f"UpdateTime={update_time}",
        "MaxData=1000000",
        f"StartWhenReady={'On' if start_when_ready else 'Off'}",
        f"Comment={comment}", f"Password={password}",
        f"Admin={admin}", f"GameSettings={game_settings}",
        f"MinPlayers={min_players}",
        f"RestartAll={'On' if restart_all else 'Off'}",
        "NetStats=On", "Profiling=On"
    ]

    servers_active[port] = subprocess.Popen(
        command,
        stdout=f, stderr=f, shell=False
    )

    last_active[port] = datetime.now()

    logger.info(f"Server launched on port {port}: '{comment}'")
    return f"✅ Launched server '{comment}' on port {port}", port


def stop_server_process(port: int):
    if port not in servers_active:
        return f"⚠ Server on port {port} not found"

    logger.info(f"Shutting down server on port {port}")
    log_files[port].write(f"Server shut down at {datetime.now()}")

    servers_active[port].terminate()
    log_files[port].close()
    del servers_active[port]
    del last_active[port]
    del log_files[port]

    logger.info(f"Server on port {port} shut down")
    return f"✅ Server on port {port} shut down"


class ServerActions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.choices(game=server_games_choices)
    @app_commands.command(description="Launches a new instance of xRC Sim server", name="launchserver")
    @app_commands.checks.has_any_role("Event Staff")
    async def launch_server(self, interaction: discord.Interaction,
                            game: str, comment: str, password: str = "", admin: str = "Admin",
                            restart_mode: int = -1, frame_rate: int = 120, update_time: int = 10,
                            tournament_mode: bool = True, start_when_ready: bool = True,
                            register: bool = True, spectators: int = 4, min_players: int = -1,
                            restart_all: bool = True):
        logger.info(f"{interaction.user.name} called /launchserver")

        result, _ = start_server_process(game, comment, password, admin, restart_mode, frame_rate, update_time,
                                         tournament_mode, start_when_ready, register, spectators, min_players, restart_all)

        await interaction.response.send_message(result)

    @app_commands.command(description="Shutdown a running xRC Sim server", name="landserver")
    @app_commands.checks.has_any_role("Event Staff")
    @app_commands.choices(port=[Choice(name=str(port), value=port) for port in PORTS])
    async def land_server(self, interaction: discord.Interaction, port: int):
        logger.info(f"{interaction.user.name} called /landserver")

        result = stop_server_process(port)

        await interaction.response.send_message(result)

    @app_commands.command(description="Lists the running server instances", name="listservers")
    @app_commands.checks.has_any_role("Event Staff")
    async def list_servers(self, interaction: discord.Interaction):
        logger.info(f"{interaction.user.name} called /listservers")
        if not servers_active:
            await interaction.response.send_message("⚠ No servers are running")
            return

        await interaction.response.send_message("Servers running: " + ", ".join([str(port) for port in servers_active]))


async def setup(bot: commands.Bot) -> None:
    cog = ServerActions(bot)
    guild = await bot.fetch_guild(GUILD_ID)
    assert guild is not None

    await bot.add_cog(
        cog,
        guilds=[guild]
    )
