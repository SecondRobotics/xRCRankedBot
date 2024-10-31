import asyncio
from datetime import datetime, timedelta
from io import TextIOWrapper
import subprocess
from typing import Dict, Optional
from discord import app_commands, ButtonStyle
from discord.ui import View, Button
import random
from queue import Queue as BaseQueue, Empty
from discord.utils import get, escape_mentions
import discord
import logging
from discord.ext import commands, tasks
from collections.abc import MutableSet
import requests
from dotenv import load_dotenv
import os
from discord.app_commands import Choice
import zipfile
import shutil
from config import *
import aiohttp
import config

# Constants
SERVER_PATH = "./server/xRC Simulator.x86_64"
SERVER_LOGS_DIR = "./server_logs/"
XRC_SIM_ZIP_URL = "https://xrcsimulator.org/Downloads/xRC_Linux_Server.zip"
XRC_SIM_ZIP_PATH = "./xRC_Linux_Server.zip"
XRC_SIM_LOGO_URL = "https://secondrobotics.org/logos/xRC%20Logo.png"
RULES_CHANNEL_LINK = f"The rules can be found here: <#{RULES_CHANNEL_ID}>"
QUEUE_CHANNEL_ERROR_MSG = f"<#{QUEUE_CHANNEL_ID}> >:("
REGISTRATION_URL = "https://www.secondrobotics.org/login"

logger = logging.getLogger('discord')

queue_channel = 0

team_size = 6
team_size_alt = 4
HEADER = {"x-api-key": SRC_API_TOKEN}

ip = requests.get('https://icanhazip.com').text
servers_active: Dict[int, subprocess.Popen] = {}
log_files: Dict[int, TextIOWrapper] = {}

listener = commands.Cog.listener

active_games = list(server_games.keys())[-3:]
inactive_games = list(server_games.keys())[:-3]
inactive_games.remove("Bot Royale")
inactive_games.remove("Relic Recovery")
#active_games.append("Test")

daily_game = random.choice(inactive_games)

games = requests.get("https://secondrobotics.org/api/ranked/").json()

games_choices = [Choice(name=game['name'], value=game['short_code'])
                 for game in games if game['game'] in active_games or game['game'] == daily_game]

games_players = {game['short_code']: game['players_per_alliance'] * 2 for game in games}

games_categories = active_games.copy()
games_categories.append(daily_game)


class OrderedSet(MutableSet):
    def __init__(self, iterable=None):
        self.end = end = []
        end += [None, end, end]
        self.map = {}
        if iterable is not None:
            self |= iterable

    def __len__(self):
        return len(self.map)

    def __contains__(self, key):
        return key in self.map

    def add(self, key):
        if key not in self.map:
            end = self.end
            curr = end[1]
            curr[2] = end[1] = self.map[key] = [key, curr, end]

    def discard(self, key):
        if key in self.map:
            key, prev, _next = self.map.pop(key)
            prev[2] = _next
            _next[1] = prev

    def __iter__(self):
        end = self.end
        curr = end[2]
        while curr is not end:
            yield curr[0]
            curr = curr[2]

    def __reversed__(self):
        end = self.end
        curr = end[1]
        while curr is not end:
            yield curr[0]
            curr = curr[1]

    def pop(self, last=True):
        if not self:
            raise KeyError('set is empty')
        key = self.end[1][0] if last else self.end[2][0]
        self.discard(key)
        return key

    def __repr__(self):
        if not self:
            return '%s()' % (self.__class__.__name__,)
        return '%s(%r)' % (self.__class__.__name__, list(self))

    def __eq__(self, other):
        if isinstance(other, OrderedSet):
            return len(self) == len(other) and list(self) == list(other)
        return set(self) == set(other)


class PlayerQueue(BaseQueue):
    def _init(self, maxsize):
        self.queue = OrderedSet()
        self.vote_queue = []  # Add this for vote queues

    def _put(self, item):
        if isinstance(item, tuple):  # Check if this is a vote queue entry
            self.vote_queue.append(item)
            queue_joins[(self, item[0])] = datetime.now()  # Store join time for the player
        else:
            self.queue.add(item)
            queue_joins[(self, item)] = datetime.now()

    def _get(self):
        if self.vote_queue:  # If this is a vote queue
            return self.vote_queue.pop(0)
        return self.queue.pop()

    def get_nowait(self):
        """Custom get_nowait implementation for vote queues"""
        with self.mutex:
            if self.vote_queue:
                if not self.vote_queue:
                    raise Empty
                return self.vote_queue.pop(0)
            else:
                if not self.queue:
                    raise Empty
                return self.queue.pop()

    def remove(self, value):
        if self.vote_queue:  # If this is a vote queue
            self.vote_queue = [x for x in self.vote_queue if x[0] != value]
            queue_joins.pop((self, value), None)
        else:
            self.queue.remove(value)
            queue_joins.pop((self, value), None)

    def __contains__(self, item):
        with self.mutex:
            if self.vote_queue:  # If this is a vote queue
                return any(item == x[0] for x in self.vote_queue)
            return item in self.queue

    def qsize(self):
        with self.mutex:
            if self.vote_queue:  # If this is a vote queue
                return len(self.vote_queue)
            return len(self.queue)

    def empty(self):
        """Custom empty check"""
        with self.mutex:
            if self.vote_queue is not None:
                return len(self.vote_queue) == 0
            return len(self.queue) == 0


class Game:
    def __init__(self, players):
        self.players = list(players)  # Ensure players is a list
        self.captains = []
        if len(self.players) >= 2:
            self.captains = random.sample(self.players, 2)
        self.red = set()
        self.blue = set()

    def add_to_blue(self, player):
        self.players.remove(player)
        self.blue.add(player)

    def add_to_red(self, player):
        self.players.remove(player)
        self.red.add(player)

    def __contains__(self, item):
        return item in self.players or item in self.red or item in self.blue


class XrcGame:
    def __init__(self, game, alliance_size: int, api_short: str, full_game_name: str):
        self.game_type = game
        self.game = None  # type: Game | None
        self.game_size = alliance_size * 2
        self.red_series = 0
        self.blue_series = 0
        self.red_captain = None
        self.blue_captain = None
        self.clearmatch_message = None
        self.autoq = []
        self.team_size = alliance_size
        self.api_short = api_short
        self.server_game = server_games[game]
        self.server_port = None  # type: int | None
        self.server_password = None  # type: str | None
        self.full_game_name = full_game_name
        self.red_role = None  # type: discord.Role | None
        self.blue_role = None  # type: discord.Role | None
        self.red_channel = None  # type: discord.VoiceChannel | None
        self.blue_channel = None  # type: discord.VoiceChannel | None
        self.last_ping_time = None  # type: datetime | None
        self.players = []

        try:
            self.game_icon = game_logos[game]
        except Exception as e:
            logger.warning(f"Error setting game icon: {e}")
            self.game_icon = None


class Queue:
    def __init__(self, game, alliance_size: int, api_short: str, full_game_name: str):
        self._queue = PlayerQueue()
        self.matches = []
        self.game_type = game
        self.alliance_size = alliance_size
        self.api_short = api_short
        self.full_game_name = full_game_name

    def create_match(self):
        match = XrcGame(self.game_type, self.alliance_size,
                        self.api_short, self.full_game_name)
        self.matches.append(match)
        logger.info('Create match called')
        return match

    def remove_match(self, match: XrcGame):
        self.matches.remove(match)


async def handle_score_edit(interaction: discord.Interaction, qdata: XrcGame, red_score: int, blue_score: int):
    url = f'https://secondrobotics.org/api/ranked/{qdata.api_short}/match/edit/'
    json = {
        "red_score": red_score,
        "blue_score": blue_score
    }
    x = requests.patch(url, json=json, headers=HEADER)
    response = x.json()
    logger.info(response)

    if 'error' in response:
        await interaction.followup.send(f"Error: {response['error']}")
    else:
        await interaction.followup.send(
            "Most recent match edited successfully. Note: the series will not be updated to reflect this change, but ELO will.")


class VoteView(View):
    def __init__(self, interaction: discord.Interaction, qdata: XrcGame, red_score: int, blue_score: int):
        super().__init__(timeout=120)
        self.interaction = interaction
        self.qdata = qdata
        self.red_score = red_score
        self.blue_score = blue_score
        self.approvals = 0
        self.rejections = 0
        self.total_voters = len(qdata.game.red | qdata.game.blue)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        roles = [role.id for role in interaction.user.roles]
        if self.qdata.red_role and self.qdata.blue_role:
            ranked_roles = [self.qdata.red_role.id, self.qdata.blue_role.id]
        else:
            ranked_roles = []

        if any(role in ranked_roles for role in roles):
            return True
        await interaction.response.send_message("You are not eligible to vote on this score edit.", ephemeral=True)
        return False

    @discord.ui.button(label="Approve Change", style=discord.ButtonStyle.green)
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.approvals += 1
        await interaction.response.send_message("You approved the score change.", ephemeral=True)
        await self.check_vote(interaction)

    @discord.ui.button(label="Reject Change", style=discord.ButtonStyle.red)
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.rejections += 1
        await interaction.response.send_message("You rejected the score change.", ephemeral=True)
        await self.check_vote(interaction)

    async def check_vote(self, interaction: discord.Interaction):
        if self.approvals > self.total_voters / 2:
            await handle_score_edit(self.interaction, self.qdata, self.red_score, self.blue_score)
            await self.interaction.followup.send(
                f"{self.qdata.red_role.mention} {self.qdata.blue_role.mention}\nScore edit approved: Red {self.red_score} - Blue {self.blue_score}")
            self.stop()
        elif self.rejections > self.total_voters / 2:
            await self.interaction.followup.send("Score edit rejected by the team.")
            self.stop()

    async def on_timeout(self):
        await self.interaction.followup.send("Score edit attempt failed. Continuing with the series.")
        self.stop()


async def remove_roles(guild: discord.Guild, qdata: XrcGame):
    red_check = get(guild.roles, name=f"Red {qdata.full_game_name}")
    blue_check = get(guild.roles, name=f"Blue {qdata.full_game_name}")
    if red_check:
        await red_check.delete()
    if blue_check:
        await blue_check.delete()


def create_game(game_type):
    qdata = game_queues[game_type]
    offset = qdata._queue.qsize() - qdata.alliance_size * 2
    qsize = qdata._queue.qsize()
    players = [qdata._queue.get() for _ in range(qsize)]  # type: list[discord.Member]
    match = qdata.create_match()
    match.game = Game(players[0 + offset:match.game_size + offset])
    match.players = match.game.players  # Set the players attribute of XrcGame
    for player in players[0:offset]:
        qdata._queue.put(player)
    players = [qdata._queue.get() for _ in range(qdata._queue.qsize())]
    for player in players:
        qdata._queue.put(player)

    for queue in game_queues.values():
        if queue.game_type != game_type:
            for player in match.players:
                if player in queue._queue:
                    queue._queue.remove(player)

    return match


def download_file(url):
    local_filename = url.split('/')[-1]
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(local_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return local_filename


class Ranked(commands.Cog):
    def __init__(self, bot):
        self.category = None  # type: discord.CategoryChannel | None
        self.staff = None  # type: discord.Role | None
        self.bots = None  # type: discord.Role | None
        self.bot = bot
        self.ranked_display = None
        self.check_queue_joins.start()
        self.has_daily_pinged = False
        self.check_daily_ping.start()
        self.lobby = self.bot.get_channel(LOBBY_VC_ID)

        self.bot.set_ranked_cog_reference(self)

        # self.check_empty_servers.start() # FIXME: Disabled for now
        self.bot.loop.create_task(self.cleanup_old_data())

        self.vote_queue_3v3 = Queue("Vote3v3", 3, "vote3v3", "Vote 3v3")
        self.vote_queue_2v2 = Queue("Vote2v2", 2, "vote2v2", "Vote 2v2")
        self.vote_queue_1v1 = Queue("Vote1v1", 1, "vote1v1", "Vote 1v1")

    async def cleanup_old_data(self):
        await self.bot.wait_until_ready()
        
        for guild in self.bot.guilds:
            category = guild.get_channel(CATEGORY_ID)
            if category and isinstance(category, discord.CategoryChannel):
                # Clean up old channels
                channel_tasks = []
                for channel in category.channels:
                    if channel.name.startswith("🟥") or channel.name.startswith("🟦"):
                        channel_tasks.append(self.delete_channel(channel))
                await asyncio.gather(*channel_tasks)

            # Clean up old roles
            role_tasks = []
            for role in guild.roles:
                if role.name.startswith("Red ") or role.name.startswith("Blue "):
                    role_tasks.append(self.delete_role(role))
            await asyncio.gather(*role_tasks)

        print("Cleanup of old data completed.")

    async def delete_channel(self, channel):
        try:
            await channel.delete()
            logger.info(f"Deleted old channel: {channel.name}")
        except discord.errors.Forbidden:
            logger.warning(f"No permission to delete channel: {channel.name}")
        except Exception as e:
            logger.error(f"Error deleting channel {channel.name}: {str(e)}")

    async def delete_role(self, role):
        try:
            await role.delete()
            logger.info(f"Deleted old role: {role.name}")
        except discord.errors.Forbidden:
            logger.warning(f"No permission to delete role: {role.name}")
        except Exception as e:
            logger.error(f"Error deleting role {role.name}: {str(e)}")

    async def startup(self):
        logger.info("Running startup code for ranked cog")

        global qstatus_channel
        qstatus_channel = get(self.bot.get_all_channels(),
                              id=QUEUE_STATUS_CHANNEL_ID)
        if qstatus_channel is None or not isinstance(qstatus_channel, discord.TextChannel):
            logger.fatal("Could not find queue status channel")
            raise RuntimeError("Could not find queue status channel")
        limit = 0
        async for _ in qstatus_channel.history(limit=None):
            limit += 1
        await qstatus_channel.purge(limit=limit)

        global queue_channel
        queue_channel = get(self.bot.get_all_channels(), id=QUEUE_CHANNEL_ID)
        if queue_channel is None or not isinstance(queue_channel, discord.TextChannel):
            logger.fatal("Could not find queue channel")
            raise RuntimeError("Could not find queue channel")

        embed = discord.Embed(title="xRC Sim Ranked Queues",
                              description="Ranked queues are open!", color=0x00ff00)
        embed.set_thumbnail(url=XRC_SIM_LOGO_URL)
        embed.add_field(name="No current queues",
                        value="Queue to get a match started!", inline=False)
        self.ranked_display = await qstatus_channel.send(embed=embed)

        await self.update_ranked_display()

    async def create_ping_roles(self):
        guild_id = GUILD_ID  # Guild ID of the desired guild
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            print(f"Guild with ID {guild_id} not found!")
            return

        games = server_games  # Use the server_games dictionary
        for game in games.keys():
            role_name = f"{game} Ping"
            existing_role = discord.utils.get(guild.roles, name=role_name)
            if existing_role is None:
                await guild.create_role(name=role_name)

    @tasks.loop(minutes=5)
    async def check_daily_ping(self):
        current_time = datetime.now()

        if current_time.hour == 13 and current_time.minute <= 10 and guild and not self.has_daily_pinged:
            logger.info(
                f"Initiating daily game ping, current time is {current_time}")

            self.has_daily_pinged = True

            daily_game_ping_role = discord.utils.get(
                await guild.fetch_roles(), name=f"{daily_game} Ping")
            if daily_game_ping_role is not None:
                await queue_channel.send(
                    f"{daily_game} is today's game of the day!\n{daily_game_ping_role.mention}")

            self.check_daily_ping.cancel()

    async def update_ranked_display(self):
        if self.ranked_display is None:
            logger.info("Finding Ranked Queue Display")

            qstatus_channel = get(
                self.bot.get_all_channels(), id=QUEUE_STATUS_CHANNEL_ID)
            async for msg in qstatus_channel.history(limit=None):
                if msg.author.id == self.bot.user.id:
                    self.ranked_display = msg
                    logger.info("Found Ranked Queue Display")
                    break

        if self.ranked_display is None:
            return

        embed = discord.Embed(title="xRC Sim Ranked Queues",
                              description="Ranked queues are open!", color=0x00ff00)
        embed.set_thumbnail(url=XRC_SIM_LOGO_URL)
        
        # Display active regular queues
        for qdata in game_queues.values():
            if qdata._queue.qsize() > 0:
                embed.add_field(name=qdata.full_game_name, 
                              value=f"*{qdata._queue.qsize()}/{qdata.alliance_size * 2}*"
                              f" players in queue", inline=False)

        # Add Vote queue status display
        vote_queues_status = ""
        for queue in [self.vote_queue_3v3, self.vote_queue_2v2, self.vote_queue_1v1]:
            vote_queues_status += f"{queue.full_game_name}: {queue._queue.qsize()}/{queue.alliance_size * 2} players\n"

        embed.add_field(name="Vote Queues", value=vote_queues_status, inline=False)

        leave_all = discord.ui.Button(
            label="Leave All Queues", style=ButtonStyle.red, row=2)
        leave_all.callback = self.leave_all_queues

        view = discord.ui.View(timeout=None)
        view.add_item(leave_all)

        try:
            await self.ranked_display.edit(embed=embed, view=view)
        except Exception as e:
            logger.error(e)
            self.ranked_display = None

    async def queue_player(self, interaction: discord.Interaction, game: str, from_button: bool = False):
        logger.info(f"{interaction.user.name} called /q")
        await interaction.response.defer(ephemeral=True)

        if not await self.validate_player(interaction, game):
            return

        qdata = game_queues[game]
        player = interaction.user

        if not self.is_valid_queue_channel(interaction, from_button):
            await interaction.followup.send(QUEUE_CHANNEL_ERROR_MSG, ephemeral=True)
            return

        if await self.is_player_in_queue_or_match(player, qdata):
            return

        await self.add_player_to_queue(player, qdata, interaction)
        await self.check_queue_status(qdata, interaction)

    async def validate_player(self, interaction: discord.Interaction, game: str) -> bool:
        url = f'https://secondrobotics.org/api/ranked/player/{interaction.user.id}'
        x = requests.get(url, headers=HEADER)
        res = x.json()
        logger.info(res)

        if not res["exists"]:
            await interaction.followup.send(
                f"You must register for an account at <{REGISTRATION_URL}> before you can queue.",
                ephemeral=True)
            return False

        # Check if the player is already in a game
        if await self.is_player_in_match(interaction.user):
            await interaction.followup.send(
                "You are already in a match. Please finish your current match before queuing for a new one.",
                ephemeral=True)
            return False

        return True

    async def is_player_in_match(self, player: discord.Member) -> bool:
        for qdata in game_queues.values():
            for match in qdata.matches:
                if match.red_role in player.roles or match.blue_role in player.roles:
                    return True
        return False

    def is_valid_queue_channel(self, interaction: discord.Interaction, from_button: bool) -> bool:
        return (isinstance(interaction.channel, discord.TextChannel) and
                (interaction.channel.id == QUEUE_CHANNEL_ID or from_button) and
                isinstance(interaction.user, discord.Member))

    async def is_player_in_queue_or_match(self, player: discord.Member, qdata: Queue) -> bool:
        if player in qdata._queue:
            await player.send("You are already in this queue.", ephemeral=True)
            return True

        roles = set(role.id for role in player.roles)
        if any(match.red_role and match.blue_role and 
               (match.red_role.id in roles or match.blue_role.id in roles)
               for match in qdata.matches):
            await player.send("You are already playing in a game!", ephemeral=True)
            return True

        return False

    async def add_player_to_queue(self, player: discord.Member, qdata: Queue, interaction: discord.Interaction):
        qdata._queue.put(player)
        await self.update_ranked_display()
        res = await self.get_player_info(player.id)
        followup = await interaction.followup.send(
            f"🟢 **{res['display_name']}** 🟢\nadded to queue for [{qdata.full_game_name}](https://secondrobotics.org/ranked/{qdata.api_short})."
            f" *({qdata._queue.qsize()}/{qdata.alliance_size * 2})*\n"
            f"[Edit Display Name](https://secondrobotics.org/user/settings/)", ephemeral=True)

        await followup.delete(delay=60)

    async def check_queue_status(self, qdata: Queue, interaction: discord.Interaction):
        if self.should_ping_queue(qdata):
            await self.ping_queue(qdata, interaction)

        if qdata._queue.qsize() >= qdata.alliance_size * 2:
            await self.start_match(qdata, interaction, False)
        else:
            await self.send_queue_status(qdata, interaction)

    def should_ping_queue(self, qdata: Queue) -> bool:
        return qdata._queue.qsize() in {3, 4} and qdata.alliance_size in {4, 6}

    async def ping_queue(self, qdata: Queue, interaction: discord.Interaction):
        current_time = datetime.now()
        last_match = qdata.matches[-1] if qdata.matches else None
        
        if not last_match or last_match.last_ping_time is None or (current_time - last_match.last_ping_time).total_seconds() > 3600:
            if last_match:
                last_match.last_ping_time = current_time

            ping_role_name = f"{qdata.game_type} Ping"
            logger.info(f"Pinging {ping_role_name}")
            ping_role = discord.utils.get(interaction.guild.roles, name=ping_role_name)
            
            if ping_role:
                await queue_channel.send(
                    f"{ping_role.mention} Queue for [{qdata.full_game_name}](https://secondrobotics.org/ranked/{qdata.api_short}) "
                    f"is now {qdata._queue.qsize()}/{qdata.alliance_size * 2}!"
                )
                

    async def send_queue_status(self, qdata: Queue, interaction: discord.Interaction):
        qstatus = await queue_channel.send(
            f"Queue for [{qdata.full_game_name}](https://secondrobotics.org/ranked/{qdata.api_short}) is now **[{qdata._queue.qsize()}/{qdata.alliance_size * 2}]**")
        await qstatus.delete(delay=30)

    async def get_player_info(self, player_id: int):
        url = f'https://secondrobotics.org/api/ranked/player/{player_id}'
        x = requests.get(url, headers=HEADER)
        return x.json()

    server_game_names = [
        Choice(name=game, value=game) for game in server_games.keys()
    ]

    async def start_match(self, qdata: Queue, interaction: discord.Interaction, from_button: bool = False):
        if qdata._queue.qsize() < qdata.alliance_size * 2:
            await interaction.followup.send("Queue is not full.", ephemeral=True)
            return

        # Always create a new match and reset series scores to 0
        await self.random(qdata, interaction, qdata.api_short, from_button)

    async def leave_all_queues(self, interaction: discord.Interaction, via_command=False):
        if not isinstance(interaction.channel, discord.TextChannel) or not isinstance(interaction.user, discord.Member):
            return

        if not via_command and interaction.channel.id != QUEUE_CHANNEL_ID:
            return

        player = interaction.user
        
        logger.info(f"Attempting to remove {player.name} from all queues")

        relevant_queues = [queue for queue in game_queues.values() if player in queue._queue]
        relevant_vote_queues = []

        for vote_queue in [self.vote_queue_3v3, self.vote_queue_2v2, self.vote_queue_1v1]:
            if any(entry[0] == player for entry in vote_queue._queue.queue):
                relevant_vote_queues.append(vote_queue)
                logger.info(f"{player.name} found in {vote_queue.full_game_name}")
            else:
                logger.info(f"{player.name} not found in {vote_queue.full_game_name}")

        if not relevant_queues and not relevant_vote_queues:
            logger.info(f"{player.name} not found in any queues")
            await interaction.response.send_message("You aren't in any queues.", ephemeral=True, delete_after=30)
            return

        message_parts = [f"🔴 **{escape_mentions(player.display_name)}** 🔴\nremoved from the queue for "]
        
        for queue in relevant_queues:
            queue._queue.remove(player)
            message_parts.append(f"__{queue.full_game_name}__. *({queue._queue.qsize()}/{queue.alliance_size * 2})*")
            logger.info(f"Removed {player.name} from {queue.full_game_name}")

        for queue in relevant_vote_queues:
            queue._queue.queue = [entry for entry in queue._queue.queue if entry[0] != player]
            message_parts.append(f"__{queue.full_game_name}__. *({len(queue._queue.queue)}/{queue.alliance_size * 2})*")
            logger.info(f"Removed {player.name} from vote queue {queue.full_game_name}")

        message = ", ".join(message_parts)
        
        await self.update_ranked_display()
        await interaction.response.send_message(message, ephemeral=True, delete_after=30)
        await queue_channel.send(message)

        for queue in relevant_queues + relevant_vote_queues:
            queue_size = queue._queue.qsize() if hasattr(queue._queue, 'qsize') else len(queue._queue.queue)
            await queue_channel.send(
                f"Queue for [{queue.full_game_name}](https://secondrobotics.org/ranked/{queue.api_short}) "
                f"is now **[{queue_size}/{queue.alliance_size * 2}]**",
                delete_after=60
            )
        
        logger.info(f"Finished removing {player.name} from all queues")
            
    async def random(self, qdata: Queue, interaction, game_type, from_button: bool = False):
        match = create_game(game_type)

        if not match.game:
            await interaction.followup.send("No game found", ephemeral=True)
            return

        # Create roles before assigning players to teams
        match.red_role = await interaction.guild.create_role(
            name=f"Red {match.full_game_name}", colour=discord.Color(0xFF0000))
        match.blue_role = await interaction.guild.create_role(
            name=f"Blue {match.full_game_name}", colour=discord.Color(0x0000FF))

        logger.info(f"Getting players for {match.game_type}")

        # Convert the set to a list before using random.sample
        players_list = list(match.game.players)
        
        # Assign players to red team and give them the red role
        red = random.sample(players_list, int(match.team_size))
        for player in red:
            match.game.add_to_red(player)
            # Only add roles to real members
            if not is_mock_member(player):
                await player.add_roles(match.red_role)

        logger.info(f"Red: {red}")

        # Assign remaining players to blue team and give them the blue role
        blue = [player for player in players_list if player not in red]
        for player in blue:
            match.game.add_to_blue(player)
            # Only add roles to real members
            if not is_mock_member(player):
                await player.add_roles(match.blue_role)

        logger.info(f"Blue: {blue}")

        # Remove players from other queues
        all_players = red + blue
        for queue in game_queues.values():
            if queue != qdata:
                for player in all_players:
                    if player in queue._queue:
                        queue._queue.remove(player)
                        logger.info(f"Removed {player.name} from {queue.full_game_name} queue")

        # Also remove from vote queues
        for vote_queue in [self.vote_queue_3v3, self.vote_queue_2v2, self.vote_queue_1v1]:
            vote_queue._queue.queue = [entry for entry in vote_queue._queue.queue if entry[0] not in all_players]

        # Code from start_match
        match.red_series = 0
        match.blue_series = 0

        if (interaction.channel is None or interaction.channel.id != QUEUE_CHANNEL_ID) and not from_button:
            await interaction.followup.send(QUEUE_CHANNEL_ERROR_MSG, ephemeral=True)
            return

        password = str(random.randint(100, 999))
        min_players = games_players[qdata.api_short]
        server_actions = self.bot.get_cog('ServerActions')
        message, port = server_actions.start_server_process(
            match.server_game, f"Ranked{qdata.api_short}", password, min_players=min_players)
        if port == -1:
            logger.warning("Server couldn't auto-start for ranked: " + message)
        else:
            match.server_port = port
            match.server_password = password

        await self.display_teams(interaction, match)

    def find_match_by_player(self, player: discord.Member):
        logger.info(f"Searching for match containing player: {player.name}")
        for queue in game_queues.values():
            logger.info(f"Checking queue: {queue.game_type}")
            for match in queue.matches:
                logger.info(f"Checking match: {match}")
                if match.game:
                    logger.info(f"Match game: {match.game}")
                    logger.info(f"Red team: {match.game.red}")
                    logger.info(f"Blue team: {match.game.blue}")
                if isinstance(match, XrcGame) and match.game and (player in match.game.red or player in match.game.blue):
                    logger.info(f"Found match for player {player.name}")
                    return match
        logger.info(f"No match found for player {player.name}")
        return None

    async def display_teams(self, ctx, match: XrcGame):

        async def fetch_player_elo(game, user_id):
            url = f'https://secondrobotics.org/api/ranked/{game}/player/{user_id}'
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('elo', 0)
                    else:
                        logger.error(
                            f"Failed to fetch ELO for player {user_id}: {response.status}")
                        return 0

        async def move_player(player, channel):
            try:
                await player.move_to(channel)
            except Exception as e:
                logger.error(e)

        logger.info(f"Displaying teams for {match.game_type}")

        self.category = self.category or get(
            ctx.guild.categories, id=CATEGORY_ID)
        self.staff = self.staff or get(ctx.guild.roles, id=EVENT_STAFF_ID)
        self.bots = self.bots or get(ctx.guild.roles, id=BOTS_ROLE_ID)

        logger.info(f"Getting IP for {match.game_type}")

        red_field = "\n".join(
            [f"🟥{player.mention}" for player in match.game.red])
        blue_field = "\n".join(
            [f"🟦{player.mention}" for player in match.game.blue])

        # Construct the description with all relevant variables
        description = (
            f"Server 'Ranked{match.api_short}' started for you with password **{match.server_password}**\n"
            f"|| IP: {ip} Port: {match.server_port} ||\n"
            f"[Adjust Display Name](https://secondrobotics.org/user/settings/) | [Leaderboard](https://secondrobotics.org/ranked/{match.api_short})\n\n"
        )

        embed = discord.Embed(
            color=0x34dceb, title=f"Teams have been picked for {match.full_game_name}!", description=description
        )
        embed.set_thumbnail(url=match.game_icon)

        # Fetch ELOs concurrently
        red_elo_tasks = [fetch_player_elo(
            match.api_short, player.id) for player in match.game.red]
        blue_elo_tasks = [fetch_player_elo(
            match.api_short, player.id) for player in match.game.blue]

        red_elos = await asyncio.gather(*red_elo_tasks)
        blue_elos = await asyncio.gather(*blue_elo_tasks)

        # Calculate average ELO
        avg_red_elo = sum(red_elos) / len(red_elos) if red_elos else 0
        avg_blue_elo = sum(blue_elos) / len(blue_elos) if blue_elos else 0

        embed.add_field(
            name=f'RED (Avg ELO: {avg_red_elo:.2f})', value=red_field, inline=True)
        embed.add_field(
            name=f'BLUE (Avg ELO: {avg_blue_elo:.2f})', value=blue_field, inline=True)

        await queue_channel.send(embed=embed)

        overwrites_red = {ctx.guild.default_role: discord.PermissionOverwrite(connect=False),
                          match.red_role: discord.PermissionOverwrite(connect=True),
                          self.staff: discord.PermissionOverwrite(connect=True),
                          self.bots: discord.PermissionOverwrite(connect=True)}
        overwrites_blue = {ctx.guild.default_role: discord.PermissionOverwrite(connect=False),
                           match.blue_role: discord.PermissionOverwrite(connect=True),
                           self.staff: discord.PermissionOverwrite(connect=True),
                           self.bots: discord.PermissionOverwrite(connect=True)}

        if match.game_size != 2:
            try:
                # Ensure the roles exist before creating channels
                if not match.red_role or not match.blue_role:
                    raise ValueError("Team roles are not properly set")

                # Create the voice channels with proper error handling
                match.red_channel, match.blue_channel = await asyncio.gather(
                    ctx.guild.create_voice_channel(f"🟥{match.full_game_name}🟥", category=self.category, overwrites=overwrites_red),
                    ctx.guild.create_voice_channel(f"🟦{match.full_game_name}🟦", category=self.category, overwrites=overwrites_blue)
                )
            except discord.errors.Forbidden:
                print("I don't have permission to create voice channels.")
                return
            except ValueError as e:
                print(f"Error: {str(e)}")
                return
            except Exception as e:
                print(f"An unexpected error occurred: {str(e)}")
                return

            if not match.game:
                print("Error: No game found")
                return

        tasks = []
        for player in match.game.red | match.game.blue:
            if match.game_size != 2:
                tasks.append(move_player(
                    player, match.red_channel if player in match.game.red else match.blue_channel))

        await asyncio.gather(*tasks, return_exceptions=True)

        await queue_channel.send(f"{match.red_role.mention} {match.blue_role.mention}", delete_after=30)
        await self.update_ranked_display()

    async def do_clear_match(self, guild: discord.Guild, match: XrcGame):
        if match.server_port:
            server_actions = self.bot.get_cog('ServerActions')
            server_actions.stop_server_process(match.server_port)

        match.red_series = match.blue_series = 2

        try:
            await remove_roles(guild, match)
        except Exception as e:
            logger.error(f"Error removing roles: {str(e)}")

        lobby = self.bot.get_channel(LOBBY_VC_ID)
        for channel in [match.red_channel, match.blue_channel]:
            if channel:
                try:
                    for member in channel.members:
                        await member.move_to(lobby)
                    await channel.delete()
                except discord.errors.NotFound:
                    logger.warning(f"Channel {channel.name} not found, it may have already been deleted.")
                except Exception as e:
                    logger.error(f"Error handling channel {channel.name}: {str(e)}")

        # Remove the match from the queue
        for queue in game_queues.values():
            if match in queue.matches:
                queue.matches.remove(match)
                break


  

    @app_commands.command(name="votequeue", description="Queue vote style")
    @app_commands.choices(mode=[
        Choice(name="3v3", value="3v3"),
        Choice(name="2v2", value="2v2"),
        Choice(name="1v1", value="1v1")
    ])
    @app_commands.choices(game=[Choice(name=game, value=game) for game in server_games.keys()])
    async def queue(self, interaction: discord.Interaction, mode: str, game: str):
        logger.info(f"{interaction.user.name} called /votequeue with mode {mode} and game {game}")
        
        queue = self.get_vote_queue(mode)
        if not queue:
            await interaction.response.send_message(f"Error: Invalid mode {mode}.", ephemeral=True)
            return

        # Check if player is already in a match
        if await self.is_player_in_match(interaction.user):
            await interaction.response.send_message(
                "You are already in a match. Please finish your current match before queuing.",
                ephemeral=True)
            return

        # Check if player is already in any vote queue
        for vq in [self.vote_queue_3v3, self.vote_queue_2v2, self.vote_queue_1v1]:
            if any(entry[0].id == interaction.user.id for entry in vq._queue.vote_queue):
                await interaction.response.send_message(
                    "You are already in a vote queue. Please leave that queue first.",
                    ephemeral=True)
                return

        # Check if player is in any regular queue
        for qdata in game_queues.values():
            if interaction.user in qdata._queue:
                await interaction.response.send_message(
                    "You are already in a regular queue. Please leave that queue first.",
                    ephemeral=True)
                return

        if not await self.validate_player(interaction, game):
            return

        await self.add_player_to_vote_queue(interaction.user, queue, game, interaction)
        await self.check_vote_queue_status(queue, interaction)

    def get_vote_queue(self, mode):
        if mode == "3v3":
            return self.vote_queue_3v3
        elif mode == "2v2":
            return self.vote_queue_2v2
        elif mode == "1v1":
            return self.vote_queue_1v1
        return None

    async def add_player_to_vote_queue(self, player: discord.Member, queue: Queue, preferred_game: str, interaction: discord.Interaction):
        queue._queue.put((player, preferred_game))
        await self.update_ranked_display()
        res = await self.get_player_info(player.id)
        await interaction.response.send_message(
            f"🟢 **{res['display_name']}** 🟢\nadded to {queue.full_game_name} queue with preferred game: {preferred_game}. "
            f"({queue._queue.qsize()}/{queue.alliance_size * 2})",
            ephemeral=True
        )

    async def check_vote_queue_status(self, queue: Queue, interaction: discord.Interaction):
        if queue._queue.qsize() >= queue.alliance_size * 2:
            await self.start_vote_match(queue, interaction)
        else:
            await self.send_queue_status(queue, interaction)

    async def start_vote_match(self, queue: Queue, interaction: discord.Interaction):
        logger.info("Starting vote match...")
        players_and_games = []
        queue_size = queue._queue.qsize()
        
        logger.info(f"Queue size: {queue_size}, Required size: {queue.alliance_size * 2}")
        
        if queue_size < queue.alliance_size * 2:
            await interaction.followup.send(f"Not enough players in queue ({queue_size}/{queue.alliance_size * 2})", ephemeral=True)
            return
            
        try:
            with queue._queue.mutex:  # Lock the queue while we process it
                # Get all players at once from the vote queue
                players_and_games = [(player, game) for player, game in queue._queue.vote_queue[:queue.alliance_size * 2]]
                # Remove the players we just got
                queue._queue.vote_queue = queue._queue.vote_queue[queue.alliance_size * 2:]
                
            if len(players_and_games) < queue.alliance_size * 2:
                logger.error(f"Not enough players in queue: got {len(players_and_games)}, needed {queue.alliance_size * 2}")
                return
                
            # Extract players and their preferred games
            players, preferred_games = zip(*players_and_games)
            
            # Choose random game from preferred games
            chosen_game = random.choice(preferred_games)
            logger.info(f"Chosen game: {chosen_game}")
            
            # Convert full game name to short code
            chosen_game_short = config.short_codes.get(chosen_game, chosen_game)
            logger.info(f"Game short code: {chosen_game_short}")
            
            # Append the alliance size to the game short code
            game_code = f"{chosen_game_short}{queue.alliance_size}v{queue.alliance_size}"
            logger.info(f"Final game code: {game_code}")
            
            if game_code not in game_queues:
                logger.error(f"Invalid game code: {game_code}")
                await interaction.followup.send(f"Error: '{game_code}' is not a valid game code. Available games: {list(game_queues.keys())}")
                # Put players back in queue
                for player, game in players_and_games:
                    queue._queue.put((player, game))
                return
                
            qdata = game_queues[game_code]
            
            # Add players to the chosen game's queue
            logger.info("Adding players to game queue...")
            for player in players:
                qdata._queue.put(player)
                logger.info(f"Added {player.display_name} to {game_code} queue")
            
            # Start the match
            logger.info("Starting match...")
            await self.start_match(qdata, interaction, False)
            
            # Inform players about the chosen game
            player_mentions = " ".join([player.mention for player in players])
            await interaction.followup.send(
                f"{player_mentions}\nThe randomly selected game is: **{chosen_game}** ({queue.alliance_size}v{queue.alliance_size})"
            )
            
        except Exception as e:
            logger.error(f"Error in start_vote_match: {str(e)}")
            # Return players to queue if there's an error
            for player, game in players_and_games:
                queue._queue.put((player, game))
            await interaction.followup.send(f"Error starting match: {str(e)}", ephemeral=True)

    @app_commands.command(description="Updates to the latest release version of xRC Sim")
    @app_commands.checks.has_any_role("Event Staff")
    async def update(self, interaction: discord.Interaction):
        logger.info(f"{interaction.user.name} called /update")
        await interaction.response.defer(thinking=True)

        if os.path.exists(XRC_SIM_ZIP_PATH):
            os.remove(XRC_SIM_ZIP_PATH)

        try:
            file = download_file(XRC_SIM_ZIP_URL)
        except Exception as e:
            logger.error(e)
            await interaction.followup.send("⚠ Update failed: Could not download file")
            return

        if os.path.exists("./server/"):
            shutil.rmtree("./server/")

        with zipfile.ZipFile(file, 'r') as zip_ref:
            zip_ref.extractall("./server")

        os.chmod(SERVER_PATH, 0o777)
        os.remove(XRC_SIM_ZIP_PATH)

        await interaction.followup.send("✅ Updated to the latest release version of xRC Sim!")
        logger.info("Updated successfully")

    @app_commands.command(description="memes")
    @app_commands.checks.has_any_role("Event Staff")
    async def test(self, interaction: discord.Interaction):
        logger.info(f"{interaction.user.name} called /test")
        await interaction.response.defer(ephemeral=True)
        for queue in game_queues.values():
            print(queue)
            red = [match.red_role for match in queue.matches]
            blue = [match.blue_role for match in queue.matches]
            print(red, blue)
            if any(role in interaction.user.roles for role in red + blue):
                await interaction.followup.send(queue.full_game_name)
                return

    @app_commands.choices(game=games_choices)
    @app_commands.command(name="queue", description="Add yourself to the queue")
    async def add_to_queue(self, interaction: discord.Interaction, game: str):
        await self.queue_player(interaction, game, False)

    
    @app_commands.choices(game=games_choices)
    @app_commands.command(description="Force queue players")
    async def forcequeue(self, interaction: discord.Interaction,
                       game: str,
                       member1: Optional[discord.Member] = None,
                       member2: Optional[discord.Member] = None,
                       member3: Optional[discord.Member] = None,
                       member4: Optional[discord.Member] = None,
                       member5: Optional[discord.Member] = None,
                       member6: Optional[discord.Member] = None):
        logger.info(f"{interaction.user.name} called /forcequeue")
        qdata = game_queues[game]

        members = [member1, member2, member3, member4, member5, member6]
        members_clean = [i for i in members if i]
        added_players = ""
        
        if isinstance(interaction.user, discord.Member) and any(role.id == EVENT_STAFF_ID for role in interaction.user.roles):
            for member in members_clean:
                qdata._queue.put(member)
                added_players += f"\n{member.display_name}"
            await interaction.response.send_message(f"Successfully added{added_players} to the queue.",
                                                    ephemeral=True)
        else:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        await self.update_ranked_display()
        await self.check_queue_status(qdata, interaction)

    @app_commands.command(description="Test vote 2v2 queue with dummy data")
    async def testvotequeue2v2(self, interaction: discord.Interaction):
        logger.info(f"{interaction.user.name} called /testvotequeue2v2")

        queue = self.vote_queue_2v2

        # Create dummy user data
        dummy_users = [
            {
                'name': f'TestUser{i}',
                'display_name': f'TestUser{i}',
                'id': 1000 + i,
                'mention': f'<@{1000 + i}>'
            } for i in range(1, 5)  # Creates 4 dummy users for 2v2
        ]

        # List of valid games for vote queue
        valid_games = list(server_games.keys())

        added_players = ""
        
        if isinstance(interaction.user, discord.Member) and any(role.id == EVENT_STAFF_ID for role in interaction.user.roles):
            for dummy_user in dummy_users:
                # Create a mock Member object with _is_mock flag
                mock_member = type('MockMember', (), {
                    'name': dummy_user['name'],
                    'display_name': dummy_user['display_name'],
                    'id': dummy_user['id'],
                    'mention': dummy_user['mention'],
                    'roles': [],
                    'add_roles': lambda x: None,
                    'remove_roles': lambda x: None,
                    'send': lambda x: None,
                    'move_to': lambda x: None,
                    '_is_mock': True,  # Add this flag
                    'guild': interaction.guild
                })

                chosen_game = random.choice(valid_games)
                queue._queue.put((mock_member, chosen_game))
                added_players += f"\n{mock_member.display_name} (Game: {chosen_game})"
            
            await interaction.response.send_message(f"Successfully added dummy players to the 2v2 vote queue:{added_players}", ephemeral=True)
        else:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        await self.update_ranked_display()
        await self.check_vote_queue_status(queue, interaction)

    @app_commands.choices(game=games_choices)
    @app_commands.command(description="Test queue with predefined user IDs")
    @app_commands.describe(game="The game to test")
    @app_commands.choices(game=[
        Choice(name=game['name'], value=game['short_code'])
        for game in games if game['game'] in active_games or game['game'] == daily_game
    ])
    async def testqueue(self, interaction: discord.Interaction, game: str):
        logger.info(f"{interaction.user.name} called /testqueue")
        qdata = game_queues[game]

        # Predefined list of user IDs
        user_ids = [
            718991656988180490,
            118000175816900615,
            863469112482856981,
            379349660764209152,
            276900035512500224,
            262011554403319809
        ]


        added_players = ""
        
        if isinstance(interaction.user, discord.Member) and any(role.id == EVENT_STAFF_ID for role in interaction.user.roles):
            for user_id in user_ids:
                member = interaction.guild.get_member(user_id)
                if member:
                    qdata._queue.put(member)
                    added_players += f"\n{member.display_name}"
                else:
                    added_players += f"\nUser ID {user_id} not found"
            
            await interaction.response.send_message(f"Successfully added{added_players} to the queue for {game}.",
                                                    ephemeral=True)
        else:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        await self.update_ranked_display()
        await self.check_queue_status(qdata, interaction)

    @app_commands.choices(game=games_choices)
    @app_commands.command(description="Start a game")
    @app_commands.describe(game="The game to start")
    @app_commands.choices(game=[
        Choice(name=game['name'], value=game['short_code'])
        for game in games if game['game'] in active_games or game['game'] == daily_game
    ])
    async def startmatch(self, interaction: discord.Interaction, game: str):
        logger.info(f"{interaction.user.name} called /startmatch")
        await interaction.response.defer()
        await self.start_match(game_queues[game], interaction, False)

    

    @app_commands.command(name="queuestatus", description="View who is currently in vote queues")
    @app_commands.checks.has_any_role("Event Staff")
    @app_commands.choices(size=[
        Choice(name="3v3", value=3),
        Choice(name="2v2", value=2),
        Choice(name="1v1", value=1)
    ])
    async def queuestatus(self, interaction: discord.Interaction, size: int):
        logger.info(f"{interaction.user.name} called /queuestatus for {size}v{size}")
        
        # Get corresponding vote queue
        vote_queue = self.get_vote_queue(f"{size}v{size}")
        if not vote_queue:
            await interaction.response.send_message(f"Invalid queue size: {size}v{size}", ephemeral=True)
            return
        
        embed = discord.Embed(color=0xcda03f, title=f"Vote Queue Status - {size}v{size}")
        
        try:
            # Debug logging
            logger.info(f"Vote queue object: {vote_queue}")
            logger.info(f"Vote queue _queue: {vote_queue._queue}")
            logger.info(f"Vote queue vote_queue: {vote_queue._queue.vote_queue}")
            
            # Access the vote_queue directly
            vote_players = vote_queue._queue.vote_queue
            
            if vote_players:
                players_info = []
                for player, game in vote_players:
                    # Format each player's info
                    player_info = f"{player.mention} (Preferred: {game})"
                    players_info.append(player_info)
                
                embed.add_field(
                    name=f'Players in Queue ({len(vote_players)}/{vote_queue.alliance_size * 2})',
                    value="\n".join(players_info),
                    inline=False
                )
            else:
                embed.add_field(name="No Players", value="Queue is empty", inline=False)

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in queuestatus: {e}")
            logger.error(f"Queue state: {vote_queue._queue.__dict__}")
            await interaction.response.send_message(f"An error occurred while fetching the queue status: {str(e)}", ephemeral=True)

    @app_commands.command(name="leave", description="Remove yourself from a vote queue")
    @app_commands.choices(size=[
        Choice(name="3v3", value=3),
        Choice(name="2v2", value=2),
        Choice(name="1v1", value=1)
    ])
    async def leave(self, interaction: discord.Interaction, size: int):
        logger.info(f"{interaction.user.name} called /leave for {size}v{size}")

        if not self.is_valid_queue_channel(interaction, False):
            await interaction.response.send_message(QUEUE_CHANNEL_ERROR_MSG, ephemeral=True)
            return

        vote_queue = self.get_vote_queue(f"{size}v{size}")
        if not vote_queue:
            await interaction.response.send_message(f"Invalid queue size: {size}v{size}", ephemeral=True)
            return

        player = interaction.user
        try:
            # Access the vote_queue directly
            vote_players = vote_queue._queue.vote_queue
            player_entry = next((entry for entry in vote_players if entry[0].id == player.id), None)

            if player_entry:
                preferred_game = player_entry[1]
                # Remove the player from the queue
                vote_queue._queue.vote_queue = [entry for entry in vote_players if entry[0].id != player.id]
                message = (
                    f"🔴 **{escape_mentions(player.display_name)}** 🔴\n"
                    f"removed from {vote_queue.full_game_name} vote queue "
                    f"(Preferred game was: {preferred_game}). "
                    f"*({len(vote_queue._queue.vote_queue)}/{vote_queue.alliance_size * 2})*"
                )
                await interaction.response.send_message(message, ephemeral=False)
                await self.update_ranked_display()
            else:
                await interaction.response.send_message("You aren't in this queue.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in leave command: {e}")
            logger.error(f"Queue state: {vote_queue._queue.__dict__}")
            await interaction.response.send_message(f"An error occurred while leaving the queue: {str(e)}", ephemeral=True)

    @app_commands.command(description="Remove someone else from a vote queue")
    @app_commands.checks.has_any_role("Event Staff")
    @app_commands.choices(size=[
        Choice(name="3v3", value=3),
        Choice(name="2v2", value=2),
        Choice(name="1v1", value=1)
    ])
    async def kick(self, interaction: discord.Interaction, player: discord.Member, size: int):
        logger.info(f"{interaction.user.name} called /kick for {size}v{size}")
        
        if not isinstance(interaction.channel, discord.TextChannel) or interaction.channel.id != QUEUE_CHANNEL_ID:
            await interaction.response.send_message(QUEUE_CHANNEL_ERROR_MSG, ephemeral=True)
            return

        vote_queue = self.get_vote_queue(f"{size}v{size}")
        if not vote_queue:
            await interaction.response.send_message(f"Invalid queue size: {size}v{size}", ephemeral=True)
            return

        try:
            # Debug logging
            logger.info(f"Vote queue object: {vote_queue}")
            logger.info(f"Vote queue _queue: {vote_queue._queue}")
            logger.info(f"Vote queue vote_queue: {vote_queue._queue.vote_queue}")
            
            # Access the vote_queue directly
            vote_players = vote_queue._queue.vote_queue
            player_entry = next((entry for entry in vote_players if entry[0].id == player.id), None)

            if player_entry:
                preferred_game = player_entry[1]
                # Remove the player from the queue
                vote_queue._queue.vote_queue = [entry for entry in vote_players if entry[0].id != player.id]
                
                message = (
                    f"**{player.display_name}** removed from {vote_queue.full_game_name} vote queue "
                    f"(Preferred game was: {preferred_game}). "
                    f"*({len(vote_queue._queue.vote_queue)}/{vote_queue.alliance_size * 2})*"
                )
                await self.update_ranked_display()
                await interaction.response.send_message(message)
            else:
                await interaction.response.send_message(f"{player.display_name} is not in the {size}v{size} vote queue.", ephemeral=True)

        except Exception as e:
            logger.error(f"Error in kick command: {e}")
            logger.error(f"Queue state: {vote_queue._queue.__dict__}")
            await interaction.response.send_message(f"An error occurred while kicking the player: {str(e)}", ephemeral=True)

    def get_vote_queue(self, size: str):
        """Helper method to get the appropriate vote queue based on size"""
        if size == "3v3":
            return self.vote_queue_3v3
        elif size == "2v2":
            return self.vote_queue_2v2
        elif size == "1v1":
            return self.vote_queue_1v1
        return None

    @app_commands.command(description="Edits the last match score (in the event of a human error)", name="editmatch")
    @app_commands.describe(
        game="The game to edit",
        red_score="New red alliance score",
        blue_score="New blue alliance score"
    )
    @app_commands.choices(game=[
        Choice(name=game['name'], value=game['short_code'])
        for game in games if game['game'] in active_games or game['game'] == daily_game
    ])
    @app_commands.checks.cooldown(1, 20.0, key=lambda i: i.guild_id)
    async def edit_match(self, interaction: discord.Interaction, game: str, red_score: int, blue_score: int):
        logger.info(f"{interaction.user.name} called /editmatch")
        await interaction.response.defer()

        qdata = game_queues[game]
        current_match = qdata.matches[-1] if qdata.matches else None

        if EVENT_STAFF_ID in [role.id for role in interaction.user.roles]:
            await handle_score_edit(interaction, current_match, red_score, blue_score)
            await interaction.followup.send(
                f"{current_match.red_role.mention} {current_match.blue_role.mention}\nScore edited successfully: Red {red_score} - Blue {blue_score}")
        else:
            roles = [role.id for role in interaction.user.roles]
            if current_match.red_role and current_match.blue_role:
                ranked_roles = [current_match.red_role.id,
                                current_match.blue_role.id]
            else:
                ranked_roles = []

            if not any(role in ranked_roles for role in roles):
                await interaction.followup.send("You are not eligible to edit a score.", ephemeral=True)
                return

            embed = discord.Embed(
                title="Score Edit Attempt",
                description=f"{interaction.user.mention} has proposed a score edit.",
                color=discord.Color.orange()
            )
            embed.add_field(name="Proposed Red Score",
                            value=str(red_score), inline=True)
            embed.add_field(name="Proposed Blue Score",
                            value=str(blue_score), inline=True)
            embed.set_footer(
                text="Please vote to approve or reject this edit.")

            await interaction.followup.send(
                f"A score edit is being attempted. {current_match.red_role.mention} {current_match.blue_role.mention}",
                embed=embed,
                view=VoteView(interaction, current_match,
                              red_score, blue_score)
            )

    
    @app_commands.command(description="Submit Score")
    @app_commands.checks.cooldown(1, 20.0, key=lambda i: i.guild_id)
    async def submit(self, interaction: discord.Interaction, red_score: int, blue_score: int):
        logger.info(f"{interaction.user.name} called /submit")
        await interaction.response.defer()

        # Find the current match and queue data
        qdata, current_match = self.find_current_match(interaction.user.roles)
        if not qdata or not current_match:
            await interaction.followup.send("You are ineligible to submit!", ephemeral=True)
            return

        if not self.is_valid_queue_channel(interaction, False):
            await interaction.followup.send(QUEUE_CHANNEL_ERROR_MSG, ephemeral=True)
            return

        if not self.is_eligible_to_submit(interaction.user.roles, current_match):
            await interaction.followup.send("You are ineligible to submit!", ephemeral=True)
            return

        if self.is_series_complete(current_match):
            await interaction.followup.send("Series is complete already!", ephemeral=True)
            return

        self.update_series_score(current_match, red_score, blue_score)
        
        gg, result_message = self.check_series_end(current_match)
        await interaction.followup.send(result_message)

        response = await self.submit_score_to_api(current_match, red_score, blue_score)
        embed = self.create_score_embed(current_match, red_score, blue_score, response)

        if gg:
            await self.handle_game_end(interaction, qdata, current_match, embed)
        else:
            await interaction.channel.send(embed=embed)

    # Helper methods
    def find_current_match(self, user_roles):
        user_roles = set(user_roles)
        for queue in game_queues.values():
            for match in queue.matches:
                if match.red_role in user_roles or match.blue_role in user_roles:
                    return queue, match
        return None, None

    def is_eligible_to_submit(self, user_roles, current_match):
        ranked_roles = [EVENT_STAFF_ID, current_match.red_role.id, current_match.blue_role.id] if current_match.red_role and current_match.blue_role else [EVENT_STAFF_ID]
        return any(role.id in ranked_roles for role in user_roles)

    def is_series_complete(self, current_match):
        return current_match.red_series == 2 or current_match.blue_series == 2

    def update_series_score(self, current_match, red_score, blue_score):
        if red_score > blue_score:
            current_match.red_series += 1
        elif blue_score > red_score:
            current_match.blue_series += 1
        logger.info(f"Updated match series scores: red_series={current_match.red_series}, blue_series={current_match.blue_series}")

    def check_series_end(self, current_match):
        if current_match.red_series == 2:
            return True, "🟥 Red Wins! 🟥"
        elif current_match.blue_series == 2:
            return True, "🟦 Blue Wins! 🟦"
        return False, "Score Submitted"

    async def submit_score_to_api(self, current_match, red_score, blue_score):
        url = f'https://secondrobotics.org/api/ranked/{current_match.api_short}/match/'
        json_data = {
            "red_alliance": [player.id for player in current_match.game.red] if current_match.game else [],
            "blue_alliance": [player.id for player in current_match.game.blue] if current_match.game else [],
            "red_score": red_score,
            "blue_score": blue_score
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=json_data, headers=HEADER) as resp:
                return await resp.json()

    def create_score_embed(self, current_match, red_score, blue_score, response):
        embed = discord.Embed(color=0x34eb3d,
                              title=f"[{current_match.full_game_name}] Score submitted | 🟥 {current_match.red_series}-{current_match.blue_series}  🟦 |")
        embed.set_thumbnail(url=current_match.game_icon)

        for color, score in [('red', red_score), ('blue', blue_score)]:
            players = "\n".join(
                f"[{response[f'{color}_display_names'][i]}](https://secondrobotics.org/ranked/{current_match.api_short}/{player['player']}) "
                f"`[{round(player['elo'], 2)}]` ```diff\n{'%+.2f' % (round(response[f'{color}_elo_changes'][i], 3))}\n```"
                for i, player in enumerate(response[f'{color}_player_elos'])
            )
            embed.add_field(name=f'{color.upper()} {"🟥" if color == "red" else "🟦"} ({score})',
                            value=players,
                            inline=True)
        return embed

    async def handle_game_end(self, interaction, qdata, current_match, embed):
        # class RejoinQueueView(discord.ui.View):
        #     def __init__(self, qdata: Queue, match: XrcGame, cog: Ranked):
        #         super().__init__()
        #         self.qdata = qdata
        #         self.match = match
        #         self.cog = cog

        #     @discord.ui.button(label="Rejoin Queue", style=discord.ButtonStyle.blurple, emoji="🔄")
        #     async def rejoin_queue(self, button_interaction: discord.Interaction, button: discord.ui.Button):
        #         await self.cog.queue_player(button_interaction, self.qdata.api_short)

        # view = RejoinQueueView(qdata, current_match, self)
        # await interaction.channel.send(embed=embed, view=view)

        await asyncio.gather(
            current_match.red_role.delete(),
            current_match.blue_role.delete()
        )

        lobby = self.bot.get_channel(LOBBY_VC_ID)
        move_tasks = []
        for channel in [current_match.red_channel, current_match.blue_channel]:
            if channel:
                move_tasks.extend([member.move_to(lobby) for member in channel.members])
                move_tasks.append(channel.delete())
        await asyncio.gather(*move_tasks)

        if current_match.server_port:
            server_actions = self.bot.get_cog('ServerActions')
            server_actions.stop_server_process(current_match.server_port)

        qdata.remove_match(current_match)

   
    
    @app_commands.command(name="clearmatch", description="Clears current running match for a player")
    async def clearmatch(self, interaction: discord.Interaction, player: discord.Member):
        logger.info(f"{interaction.user.name} called /clearmatch for player {player.name}")
        
        if EVENT_STAFF_ID not in [role.id for role in interaction.user.roles]:
            await interaction.response.send_message("You don't have permission to do that!", ephemeral=True)
            return

        await interaction.response.defer()
        
        current_match = self.find_match_by_player(player)
        if current_match:
            try:
                await self.do_clear_match(interaction.guild, current_match)
                await interaction.followup.send(f"Cleared match containing {player.name} successfully!")
            except Exception as e:
                logger.error(f"Error clearing match: {str(e)}")
                await interaction.followup.send(f"An error occurred while clearing the match: {str(e)}", ephemeral=True)
        else:
            await interaction.followup.send(f"No active match found for {player.name}.", ephemeral=True)

    

    @app_commands.command(name="rules", description="Posts a link the the rules")
    async def rules(self, interaction: discord.Interaction):
        logger.info(f"{interaction.user.name} called /rules")
        await interaction.response.send_message(RULES_CHANNEL_LINK)

    @tasks.loop(minutes=10)
    async def check_queue_joins(self):
        cutoff_time = datetime.now() - timedelta(hours=1)

        for (queue, player), timestamp in queue_joins.copy().items():
            if timestamp < cutoff_time:
                if player in queue:
                    queue.remove(player)
                    await player.send(
                        "You have been removed from a queue because you have been in the queue for more than 1 hour.")
                else:
                    queue_joins.pop((queue, player))

        await self.update_ranked_display()

    @check_queue_joins.before_loop
    async def before_check_queue_joins(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(5)
        await self.create_ping_roles()

    @tasks.loop(minutes=1)
    async def check_empty_servers(self):
        for server in servers_active.copy():
            if (await server_has_players(server)):
                last_active[server] = datetime.now()
            else:
                if server not in last_active:
                    last_active[server] = datetime.now()
                elif (datetime.now() - last_active[server]).total_seconds() > 60 * 15:
                    await shutdown_server_inactivity(server)
                elif (datetime.now() - last_active[server]).total_seconds() > 60 * 10:
                    await warn_server_inactivity(server)

    @check_empty_servers.before_loop
    async def before_check_empty_servers(self):
        await self.bot.wait_until_ready()


queue_joins = {}
last_active = {}
game_queues = {game['short_code']: Queue(
    game['game'], game['players_per_alliance'], game['short_code'], game['name']) for game in games}
cog = None
guild = None


async def setup(bot: commands.Bot) -> None:
    cog = Ranked(bot)

    global guild
    guild = await bot.fetch_guild(GUILD_ID)
    assert guild is not None

    await bot.add_cog(
        cog,
        guilds=[guild]
    )


async def shutdown_server_inactivity(server: int):
    for queue in game_queues.values():
        for match in queue.matches:
            if match.server_port == server:
                if cog and guild:
                    await cog.do_clear_match(guild, match)
                    logger.info(
                        f"Match cleared for server {server} due to inactivity")

                if match.game:
                    for player in match.game.players:
                        await player.send(
                            "Your ranked match has been cancelled due to inactivity.")
                return

    # stop_server_process(server)  # FIXME


async def server_has_players(server: int) -> bool:
    needed_players = 1
    for queue in game_queues.values():
        for match in queue.matches:
            if match.server_port == server:
                needed_players = match.game_size
                break

    process = servers_active.get(server, None)
    if process is None or process.poll() is not None or process.stdout is None or process.stdin is None:
        return False

    process.stdin.write(b"PLAYERS\n")
    process.stdin.flush()

    while True:
        line = process.stdout.readline().decode("utf-8")
        if line != '_BEGIN_\n':
            break

    players = []
    while True:
        line = process.stdout.readline().decode("utf-8")
        if line == '_END_\n':
            break
        players.append(line.strip())

    if len(players) >= needed_players:
        return True

    return False


async def warn_server_inactivity(server: int):
    for queue in game_queues.values():
        for match in queue.matches:
            if match.server_port == server:
                if match.game:
                    for player in match.game.players:
                        await player.send(
                            "Your ranked match has been inactive - if all players are not present within 5 minutes, the match will be cancelled.")
                return


def is_mock_member(member):
    """Check if a member is a mock/test member"""
    return hasattr(member, '_is_mock') and member._is_mock
