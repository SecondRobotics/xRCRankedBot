import os
import shutil  # Ensure shutil is imported for directory operations
import subprocess
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, List
import discord
from io import TextIOWrapper
from discord import app_commands
from discord.ext import commands, tasks
from discord.app_commands import Choice
import asyncio
import json  # For reading status.json
import re  # Add import for regex
from dataclasses import dataclass  # Add import for Player dataclass

from config import (
    server_restart_modes,
    server_games_choices,
    PORTS,
    server_game_settings,
    default_game_players,
    GUILD_ID,
    server_games,
    QUEUE_STATUS_CHANNEL_ID,
)

logger = logging.getLogger('discord')

# Define other constants here
SERVER_PATH = "./server/xRC Simulator.x86_64"
SERVER_LOGS_DIR = "./server_logs/"
SERVER_GAME_DATA_DIR = "./server_game_data/"  # Existing constant for score files

ports_choices = [Choice(name=str(port), value=port) for port in PORTS]

@dataclass
class Player:
    name: str
    join_time: datetime
    position: str
    ip: str

class ServerActions(commands.Cog):
    servers_active: Dict[int, subprocess.Popen] = {}
    log_files: Dict[int, TextIOWrapper] = {}
    last_active: Dict[int, datetime] = {}
    server_comments: Dict[int, str] = {}
    server_games: Dict[int, str] = {}
    watch_tasks: Dict[int, asyncio.Task] = {}  # Keep track of watch tasks
    players_active: Dict[int, List[Player]] = {}  # New attribute to track players
    log_read_positions: Dict[int, int] = {}  # Added to track last read positions
    watch_messages: Dict[int, discord.Message] = {}

    def __init__(self, bot):
        self.bot = bot
        self.players_active = {}  # Initialize the players_active dictionary
        self.log_read_positions = {}  # Initialize log read positions
        self.watch_messages = {}  # Initialize watch_messages dictionary
        self.bot.loop.create_task(self.monitor_logs())  # Start log monitoring

    async def monitor_logs(self):
        while True:
            for port, process in self.servers_active.items():
                log_path = f"{SERVER_LOGS_DIR}{port}.log"

                if port not in self.log_read_positions:
                    try:
                        with open(log_path, "r") as f:
                            last_start_pos = 0
                            while True:
                                line = f.readline()
                                if not line:
                                    break
                                if "Done setting up TCP socket.." in line:  # Updated start signal
                                    last_start_pos = f.tell()
                            self.log_read_positions[port] = last_start_pos
                    except FileNotFoundError:
                        logger.error(f"Log file for port {port} not found.")
                        continue
                    except Exception as e:
                        logger.error(f"Error initializing log file for port {port}: {e}")
                        continue

                try:
                    with open(log_path, "r") as f:
                        f.seek(self.log_read_positions[port])  # Move to the last read position
                        while True:
                            line = f.readline()
                            if not line:
                                break
                            self.parse_log_line(port, line)
                        self.log_read_positions[port] = f.tell()  # Update read position
                except FileNotFoundError:
                    logger.error(f"Log file for port {port} not found.")
                except Exception as e:
                    logger.error(f"Error reading log file for port {port}: {e}")
            await asyncio.sleep(1)  # Adjusted sleep interval if needed

    def parse_log_line(self, port: int, line: str):
        # Extract timestamp from the beginning of the log line
        try:
            timestamp_str, message = line.split(': ', 1)  # Split timestamp and message
            timestamp = datetime.strptime(timestamp_str, "%m/%d/%Y %I:%M:%S %p")  # Parse timestamp
        except ValueError:
            return

        # Initialize player list if not present
        if port not in self.players_active:
            self.players_active[port] = []

        # Clear player list on server start
        if "Done setting up TCP socket.." in message:  # Updated condition
            self.players_active[port].clear()  # Clear existing players
            return

        # Clear player list on server shutdown
        if "Server shut down at" in message:
            self.players_active[port].clear()  # Clear existing players
            return

        join_pattern = r"Player (\w+) joined on position (.+) from IP=(\d+\.\d+\.\d+\.\d+)."
        leave_pattern = r"Removing (\w+)"

        join_match = re.search(join_pattern, message)
        if join_match:
            name, position, ip = join_match.groups()
            player = Player(name=name, join_time=timestamp, position=position, ip=ip)  # Use log timestamp
            logger.info(f"Player {player.name} joined on {player.position} with ip {player.ip}")
            self.players_active.setdefault(port, []).append(player)
            return

        leave_match = re.match(leave_pattern, message)
        if leave_match:
            name = leave_match.group(1)
            logger.info(f"Player {name} left server")
            players = self.players_active.get(port, [])
            self.players_active[port] = [p for p in players if p.name != name]
    

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

        # After starting the server, create watch message
        game_type = server_games.get(game, "Unknown")
        asyncio.create_task(self._create_watch_message(port, game_type))  # Use helper method
        
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

        # Delete watch message using helper method
        asyncio.create_task(self._delete_watch_message(port))  # Use helper method
        
        return f"✅ Server on port {port} shut down"

    async def _create_watch_message(self, port: int, game_type: str):
        channel = self.bot.get_channel(QUEUE_STATUS_CHANNEL_ID)
        if channel:
            watch_message = await channel.send(f"🔔 **Server Started** on port `{port}`\n**Game Type:** {game_type}")
            self.watch_messages[port] = watch_message
            # Start the watch task for this server
            task = self.bot.loop.create_task(self.server_watch_task(port, watch_message))
            self.watch_tasks[port] = task
    
    async def _delete_watch_message(self, port: int):
        watch_message = self.watch_messages.get(port)
        if watch_message:
            try:
                await watch_message.delete()
                del self.watch_messages[port]
            except discord.NotFound:
                logger.warning(f"Watch message for port {port} not found.")
            except Exception as e:
                logger.error(f"Error deleting watch message for port {port}: {e}")
            # Cancel the associated watch task
            task = self.watch_tasks.get(port)
            if task:
                task.cancel()
                del self.watch_tasks[port]
    
    async def server_watch_task(self, port: int, message: discord.Message):
        while port in self.servers_active:
            data = self.get_server_data(port)
            if data:
                embed = discord.Embed(
                    title=f"🖥️ Server Watch for Port {port}",
                    color=discord.Color.blue(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(name="Game Type", value=self.server_games.get(port, "Unknown"), inline=True)
                embed.add_field(name="Timer", value=data.get("timer", "N/A"), inline=True)
                embed.add_field(name="Red Score", value=data.get("Score_R", "0"), inline=True)
                embed.add_field(name="Blue Score", value=data.get("Score_B", "0"), inline=True)
                
                # Display players by alliance
                players = self.players_active.get(port, [])
                red_alliance = [p for p in players if p.position.lower().startswith("red")]
                blue_alliance = [p for p in players if p.position.lower().startswith("blue")]
                spectators = [p for p in players if not p.position.lower().startswith(("red", "blue"))]

                if red_alliance:
                    red_players = "\n".join(f"{p.name} - {p.position}" for p in red_alliance)
                else:
                    red_players = "None"
                embed.add_field(name="🔴 Red Alliance", value=red_players, inline=False)

                if blue_alliance:
                    blue_players = "\n".join(f"{p.name} - {p.position}" for p in blue_alliance)
                else:
                    blue_players = "None"
                embed.add_field(name="🔵 Blue Alliance", value=blue_players, inline=False)

                if spectators:
                    spectator_list = "\n".join(f"{p.name} - {p.position}" for p in spectators)
                else:
                    spectator_list = "None"
                embed.add_field(name="👁️ Spectators", value=spectator_list, inline=False)
                
                try:
                    await message.edit(embed=embed)
                except discord.HTTPException as e:
                    logger.error(f"Failed to update watch embed for port {port}: {e}")
                    break
            await asyncio.sleep(5)  # Update every 5 seconds

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

    @app_commands.command(description="Retrieve server data once", name="server_peep")
    @app_commands.choices(port=ports_choices)
    async def server_peep(self, interaction: discord.Interaction, port: int):
        logger.info(f"{interaction.user.name} called /server_peep for port {port}")

        data = self.get_server_data(port)
        if not data:
            await interaction.response.send_message(f"⚠ Unable to retrieve data for port {port}.", ephemeral=True)
            return

        players = self.players_active.get(port, [])
        red_alliance = [player.name for player in players if player.position.lower().startswith("red")]
        blue_alliance = [player.name for player in players if player.position.lower().startswith("blue")]

        red_players = "\n".join(red_alliance) if red_alliance else "No players in Red Alliance."
        blue_players = "\n".join(blue_alliance) if blue_alliance else "No players in Blue Alliance."

        red_score = data.get("Score_R", "0")
        blue_score = data.get("Score_B", "0")

        game_type = self.server_games.get(port, "Unknown")

        embed = discord.Embed(
            title=f"Server Status for Port {port}",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Timer", value=data.get("timer", "N/A"), inline=True)
        embed.add_field(name="Red Alliance", value=red_players, inline=True)
        embed.add_field(name="Blue Alliance", value=blue_players, inline=True)
        embed.add_field(name="Red Score", value=red_score, inline=True)
        embed.add_field(name="Blue Score", value=blue_score, inline=True)
        embed.add_field(name="Game Type", value=game_type, inline=True)
        embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Watch server data and update every 5 seconds", name="server_watch")
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

        players = self.players_active.get(port, [])
        red_alliance = [player.name for player in players if player.position.lower().startswith("red")]
        blue_alliance = [player.name for player in players if player.position.lower().startswith("blue")]

        red_players = "\n".join(red_alliance) if red_alliance else "No players in Red Alliance."
        blue_players = "\n".join(blue_alliance) if blue_alliance else "No players in Blue Alliance."

        red_score = data.get("Score_R", "0")
        blue_score = data.get("Score_B", "0")

        game_type = self.server_games.get(port, "Unknown")

        embed = discord.Embed(
            title=f"Watching Server Status for Port {port}",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Timer", value=data.get("timer", "N/A"), inline=True)
        embed.add_field(name="Red Alliance", value=red_players, inline=True)
        embed.add_field(name="Blue Alliance", value=blue_players, inline=True)
        embed.add_field(name="Red Score", value=red_score, inline=True)
        embed.add_field(name="Blue Score", value=blue_score, inline=True)
        embed.add_field(name="Game Type", value=game_type, inline=True)
        embed.set_footer(text=f"Watching by {interaction.user.display_name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

        await interaction.response.send_message(embed=embed)

        # Start the server_watch_task instead of defining update_embed
        self.watch_tasks[port] = self.bot.loop.create_task(self.server_watch_task(port, await interaction.original_response()))

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

    @app_commands.command(description="Investigate server players", name="investigate")
    @app_commands.checks.has_any_role("Admin")
    @app_commands.choices(port=ports_choices)
    async def investigate(self, interaction: discord.Interaction, port: int, public: bool = False):  # Added 'public' parameter
        logger.info(f"{interaction.user.name} called /investigate for port {port}")
        players = self.players_active.get(port, [])
        if not players:
            await interaction.response.send_message("No active players on this server.", ephemeral=True)
            return
        
        # Sort players into alliances and spectators
        red_alliance = [p for p in players if p.position.lower().startswith("red")]
        blue_alliance = [p for p in players if p.position.lower().startswith("blue")]
        spectators = [p for p in players if not p.position.lower().startswith(("red", "blue"))]
        
        embed = discord.Embed(
            title=f"Players on Server Port {port}",
            color=discord.Color.purple(),
            timestamp=datetime.now(timezone.utc)
        )
        
        # Add Red Alliance section
        if red_alliance:
            red_players = "\n".join(
                [f"{p.name} - {p.position}" + (f"\nIP: {p.ip}" if not public else "") for p in red_alliance]
            )
        else:
            red_players = "None"
        embed.add_field(name="🔴 Red Alliance", value=red_players, inline=False)
        
        # Add Blue Alliance section
        if blue_alliance:
            blue_players = "\n".join(
                [f"{p.name} - {p.position}" + (f"\nIP: {p.ip}" if not public else "") for p in blue_alliance]
            )
        else:
            blue_players = "None"
        embed.add_field(name="🔵 Blue Alliance", value=blue_players, inline=False)
        
        # Add Spectators section
        if spectators:
            spectator_list = "\n".join(
                [f"{p.name} - {p.position}" + (f"\nIP: {p.ip}" if not public else "") for p in spectators]
            )
        else:
            spectator_list = "None"
        embed.add_field(name="👁️ Spectators", value=spectator_list, inline=False)
        
        embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await interaction.response.send_message(embed=embed, ephemeral=not public)  # Set ephemeral based on 'public'

async def setup(bot: commands.Bot) -> None:
    cog = ServerActions(bot)
    guild = await bot.fetch_guild(GUILD_ID)
    assert guild is not None

    await bot.add_cog(
        cog,
        guilds=[guild]
    )
