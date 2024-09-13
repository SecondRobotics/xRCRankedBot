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
from config import server_restart_modes, server_games_choices, PORTS, server_game_settings, default_game_players, GUILD_ID, server_games

logger = logging.getLogger('discord')

# Define other constants here
SERVER_PATH = "./server/xRC Simulator.x86_64"
SERVER_LOGS_DIR = "./server_logs/"

ports_choices = [Choice(name=str(port), value=port) for port in PORTS]


class ServerActions(commands.Cog):
    servers_active: Dict[int, subprocess.Popen] = {}
    log_files: Dict[int, TextIOWrapper] = {}
    last_active: Dict[int, datetime] = {}
    server_comments: Dict[int, str] = {}
    server_games: Dict[int, str] = {}

    def __init__(self, bot):
        self.bot = bot

    def start_server_process(self, game: str, comment: str, password: str = "", admin: str = "Admin",
                             restart_mode: int = -1, frame_rate: int = 120, update_time: int = 10,
                             tournament_mode: bool = True, start_when_ready: bool = True,
                             register: bool = True, spectators: int = 4, min_players: int = -1,
                             restart_all: bool = True):
        if not os.path.exists(SERVER_PATH):
            return "⚠ xRC Sim server not found, use `/update` to update", -1

        if len(self.servers_active) >= len(PORTS):
            return "⚠ The maximum number of servers are already running", -1

        port = -1
        for p in PORTS:
            if p not in self.servers_active:
                port = p
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
        self.log_files[port] = f
        f.write(f"Server started at {datetime.now()}\n")

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

        process = subprocess.Popen(command, stdout=f, stderr=f, shell=False)
        self.servers_active[port] = process
        self.last_active[port] = datetime.now()
        self.server_comments[port] = comment
        self.server_games[port] = game

        logger.info(f"Server launched on port {port}: '{comment}'")
        return f"✅ Launched server '{comment}' on port {port}", port

    def stop_server_process(self, port: int):
        if port not in self.servers_active:
            return f"⚠ Server on port {port} not found"

        logger.info(f"Shutting down server on port {port}")
        self.log_files[port].write(f"Server shut down at {datetime.now()}\n")

        self.servers_active[port].terminate()
        self.log_files[port].close()
        del self.servers_active[port]
        del self.last_active[port]
        del self.log_files[port]
        del self.server_comments[port]
        del self.server_games[port]

        logger.info(f"Server on port {port} shut down")
        return f"✅ Server on port {port} shut down"

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

        result, _ = self.start_server_process(game, comment, password, admin, restart_mode, frame_rate, update_time,
                                              tournament_mode, start_when_ready, register, spectators, min_players, restart_all)

        await interaction.response.send_message(result)

    @app_commands.command(description="Shutdown a running xRC Sim server", name="landserver")
    @app_commands.checks.has_any_role("Event Staff")
    @app_commands.choices(port=ports_choices)
    async def land_server(self, interaction: discord.Interaction, port: int):
        logger.info(f"{interaction.user.name} called /landserver")

        result = self.stop_server_process(port)

        await interaction.response.send_message(result)

    @app_commands.command(description="Lists the running server instances", name="listservers")
    @app_commands.checks.has_any_role("Event Staff")
    async def list_servers(self, interaction: discord.Interaction):
        logger.info(f"{interaction.user.name} called /listservers")
        if not self.servers_active:
            await interaction.response.send_message("⚠ No servers are running")
            return

        server_list = []
        for port, process in self.servers_active.items():
            comment = self.server_comments.get(port, "N/A")
            game_number = self.server_games.get(port, "Unknown")
            game_name = next((name for name, number in server_games.items() if number == game_number), "Unknown")
            server_list.append(f"Port {port}: {game_name} - '{comment}'")

        response = "Running servers:\n" + "\n".join(server_list)
        await interaction.response.send_message(response)


async def setup(bot: commands.Bot) -> None:
    cog = ServerActions(bot)
    guild = await bot.fetch_guild(GUILD_ID)
    assert guild is not None

    await bot.add_cog(
        cog,
        guilds=[guild]
    )
