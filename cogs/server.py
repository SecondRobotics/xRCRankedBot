import os
import shutil  # Ensure shutil is imported for directory operations
import subprocess
import logging
from datetime import datetime, timezone
from typing import Dict, Optional
import discord
from io import TextIOWrapper
from discord import app_commands
from discord.ext import commands, tasks
from discord.app_commands import Choice
import asyncio
import json  # For reading status.json

from config import (
    server_restart_modes,
    server_games_choices,
    PORTS,
    server_game_settings,
    default_game_players,
    GUILD_ID,
    server_games,
)

logger = logging.getLogger('discord')

# Define other constants here
SERVER_PATH = "./server/xRC Simulator.x86_64"
SERVER_LOGS_DIR = "./server_logs/"
SERVER_GAME_DATA_DIR = "./server_game_data/"  # Existing constant for score files

ports_choices = [Choice(name=str(port), value=port) for port in PORTS]


class ServerActions(commands.Cog):
    servers_active: Dict[int, subprocess.Popen] = {}
    log_files: Dict[int, TextIOWrapper] = {}
    last_active: Dict[int, datetime] = {}
    server_comments: Dict[int, str] = {}
    server_games: Dict[int, str] = {}
    watch_tasks: Dict[int, asyncio.Task] = {}  # Keep track of watch tasks

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

        # Set up output score files directory
        output_dir = os.path.join(SERVER_GAME_DATA_DIR, str(port))
        os.makedirs(output_dir, exist_ok=True)  # Create directories if they don't exist

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
            "NetStats=On", "Profiling=On",
            f"OUTPUT_SCORE_FILES={output_dir}"  # Added parameter
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

        # Delete server data directory for the port being shut down
        output_dir = os.path.join(SERVER_GAME_DATA_DIR, str(port))
        if os.path.exists(output_dir):
            for root, dirs, files in os.walk(output_dir, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
            os.rmdir(output_dir)
            logger.info(f"Deleted server data directory for port {port}")

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

    def get_server_data(self, port: int) -> Optional[Dict[str, any]]:
        """
        Retrieves server data for the specified port.
        Reads Timer.txt, Score_R.txt, and Score_B.txt from the server data directory.
        """
        server_data_dir = os.path.join(SERVER_GAME_DATA_DIR, str(port))
        timer_path = os.path.join(server_data_dir, 'Timer.txt')
        score_r_path = os.path.join(server_data_dir, 'Score_R.txt')
        score_b_path = os.path.join(server_data_dir, 'Score_B.txt')
        
        server_data = {}
        
        try:
            with open(timer_path, 'r') as f:
                server_data['timer'] = f.read().strip()
            with open(score_r_path, 'r') as f:
                server_data['Score_R'] = f.read().strip()
            with open(score_b_path, 'r') as f:
                server_data['Score_B'] = f.read().strip()
        except FileNotFoundError as e:
            logger.error(f"Required file not found for port {port}: {e}")
            return None
        
        return server_data

    @app_commands.command(description="Retrieve server data once", name="sever_peep")
    @app_commands.choices(port=ports_choices)
    async def server_peep(self, interaction: discord.Interaction, port: int):
        logger.info(f"{interaction.user.name} called /server_peep for port {port}")

        data = self.get_server_data(port)
        if not data:
            await interaction.response.send_message(f"⚠ Unable to retrieve data for port {port}.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Server Status for Port {port}",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Timer", value=data.get("timer", "N/A"), inline=True)
        embed.add_field(name="Score_R", value=data.get("Score_R", "N/A"), inline=True)
        embed.add_field(name="Score_B", value=data.get("Score_B", "N/A"), inline=True)
        embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Watch server data and update every 5 seconds", name="sever_watch")
    @app_commands.choices(port=ports_choices)
    async def server_watch(self, interaction: discord.Interaction, port: int):
        logger.info(f"{interaction.user.name} called /server_watch for port {port}")

        if port not in self.servers_active:
            await interaction.response.send_message(f"⚠ No active server on port {port}.", ephemeral=True)
            return

        data = self.get_server_data(port)
        if not data:
            await interaction.response.send_message(f"⚠ Unable to retrieve data for port {port}.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Watching Server Status for Port {port}",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Timer", value=data.get("timer", "N/A"), inline=True)
        embed.add_field(name="Score_R", value=data.get("Score_R", "N/A"), inline=True)
        embed.add_field(name="Score_B", value=data.get("Score_B", "N/A"), inline=True)
        embed.set_footer(text=f"Watching by {interaction.user.display_name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

        await interaction.response.send_message(embed=embed)

        # Define the update task
        async def update_embed():
            while True:
                await asyncio.sleep(5)  # Wait for 5 seconds
                updated_data = self.get_server_data(port)
                if not updated_data:
                    new_embed = discord.Embed(
                        title=f"Watching Server Status for Port {port}",
                        description="⚠ Unable to retrieve updated data. Stopping watch.",
                        color=discord.Color.red(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    try:
                        await interaction.edit_original_response(embed=new_embed)
                    except discord.HTTPException as e:
                        logger.error(f"Failed to update embed for port {port}: {e}")
                    break  # Stop watching if unable to get data

                new_embed = discord.Embed(
                    title=f"Watching Server Status for Port {port}",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                new_embed.add_field(name="Timer", value=updated_data.get("timer", "N/A"), inline=True)
                new_embed.add_field(name="Score_R", value=updated_data.get("Score_R", "N/A"), inline=True)
                new_embed.add_field(name="Score_B", value=updated_data.get("Score_B", "N/A"), inline=True)
                new_embed.set_footer(text=f"Watching by {interaction.user.display_name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

                try:
                    await interaction.edit_original_response(embed=new_embed)
                except discord.HTTPException as e:
                    logger.error(f"Failed to update embed for port {port}: {e}")
                    break  # Exit the loop if unable to update

            # Remove the task from watch_tasks when it's done
            if port in self.watch_tasks:
                del self.watch_tasks[port]

        # Start the background task
        task = self.bot.loop.create_task(update_embed())
        self.watch_tasks[port] = task

    @app_commands.command(description="Stops watching server data", name="stop_server_watch")
    @app_commands.choices(port=ports_choices)
    @app_commands.checks.has_any_role("Event Staff")
    async def stop_server_watch(self, interaction: discord.Interaction, port: int):
        logger.info(f"{interaction.user.name} called /stop_server_watch for port {port}")

        if port not in self.watch_tasks:
            await interaction.response.send_message(f"⚠ No watch task running for port {port}.", ephemeral=True)
            return

        task = self.watch_tasks[port]
        task.cancel()
        del self.watch_tasks[port]
        await interaction.response.send_message(f"✅ Stopped watching server on port {port}.")


async def setup(bot: commands.Bot) -> None:
    cog = ServerActions(bot)
    guild = await bot.fetch_guild(GUILD_ID)
    assert guild is not None

    await bot.add_cog(
        cog,
        guilds=[guild]
    )
