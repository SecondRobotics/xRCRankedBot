import asyncio
from datetime import datetime, timedelta
from io import TextIOWrapper
import subprocess
from typing import Dict, Optional
from discord import app_commands, ButtonStyle
from discord.ui import View, Button
import random
from queue import Queue
from discord.utils import get
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
from .server import start_server_process, stop_server_process

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

ports_choices = [Choice(name=str(port), value=port) for port in PORTS]

active_games = list(server_games.keys())[-3:]
inactive_games = list(server_games.keys())[:-3]
inactive_games.remove("Bot Royale")
inactive_games.remove("Relic Recovery")

daily_game = random.choice(inactive_games)

games = requests.get("https://secondrobotics.org/api/ranked/").json()

games_choices = [Choice(name=game['name'], value=game['short_code'])
                 for game in games if game['game'] in active_games or game['game'] == daily_game]

games_players = {game['short_code']: game['players_per_alliance'] * 2
                 for game in games if game['game'] in active_games or game['game'] == daily_game}

games_categories = active_games.copy()
games_categories.append(daily_game)


class XrcGame():
    def __init__(self, game, alliance_size: int, api_short: str, full_game_name: str):
        self.queue = PlayerQueue()
        self.game_type = game
        self.game = None  # type: Game | None
        self.game_size = alliance_size * 2
        self.red_series = 2
        self.blue_series = 2
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
        self.last_ping_time = None  # type: datetime.datetime | None

        try:
            self.game_icon = game_logos[game]
        except:
            self.game_icon = None


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
    offset = qdata.queue.qsize() - qdata.game_size
    qsize = qdata.queue.qsize()
    players = [qdata.queue.get()
               for _ in range(qsize)]  # type: list[discord.Member]
    qdata.game = Game(players[0 + offset:qdata.game_size + offset])
    for player in players[0:offset]:
        qdata.queue.put(player)
    players = [qdata.queue.get() for _ in range(qdata.queue.qsize())]
    for player in players:
        qdata.queue.put(player)

    for game in game_queues.values():
        if game.game_type != game_type:
            for player in qdata.game.players:
                if player in game.queue:
                    game.queue.remove(player)

    return qdata


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
    
    async def startup(self):
        logger.info("Running startup code for ranked cog")

        global qstatus_channel
        qstatus_channel = get(self.bot.get_all_channels(), id=QUEUE_STATUS_CHANNEL_ID)
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
            logger.info(f"Initiating daily game ping, current time is {current_time}")

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
        active_queues = 0
        embed.add_field(name="Game of the Day",
                        value=f"Today's extra game is **{daily_game}**!", inline=False)
        for qdata in game_queues.values():
            if qdata.queue.qsize() > 0:
                active_queues += 1
                embed.add_field(name=qdata.full_game_name, value=f"*{qdata.queue.qsize()}/{qdata.game_size}*"
                                                                 f" players in queue", inline=False)
        if active_queues == 0:
            embed.add_field(name="No current queues",
                            value="Queue to get a match started!", inline=False)

        options = [discord.SelectOption(label=game, value=game)
                   for game in server_games.keys()]
        select = discord.ui.Select(
            placeholder="Choose a game to toggle ping", options=options)
        select.callback = self.dropdown_callback

        leave_all = discord.ui.Button(label="Leave All Queues", style=ButtonStyle.red, row=2)
        leave_all.callback = self.leave_all_queues
        
        view = discord.ui.View(timeout=None)
        view.add_item(select)

        for i, game in enumerate(games_categories):
            view.add_item(GameButton(game, short_code=short_codes[game], cog=self))

        view.add_item(leave_all)

        try:
            await self.ranked_display.edit(embed=embed, view=view)
        except Exception as e:
            logger.error(e)
            self.ranked_display = None

    async def dropdown_callback(self, interaction: discord.Interaction):
        game = interaction.data['values'][0]
        logger.info(f"{interaction.user.name} selected {game} from dropdown")
        guild = interaction.guild

        ping_role_name = f"{game} Ping"
        ping_role = discord.utils.get(guild.roles, name=ping_role_name)

        member = interaction.user
        if ping_role in member.roles:
            await member.remove_roles(ping_role)
            await interaction.response.send_message(f"You have been removed from the {ping_role_name} role.",
                                                    ephemeral=True, delete_after=30)
        else:
            await member.add_roles(ping_role)
            await interaction.response.send_message(f"You have been added to the {ping_role_name} role!",
                                                    ephemeral=True)

    server_game_names = [
        Choice(name=game, value=game) for game in server_games.keys()
    ]

    @app_commands.choices(game=server_game_names)
    @app_commands.command(name="rankedping", description="Toggle ranked pings for a game")
    async def rankedping(self, interaction: discord.Interaction, game: str):
        logger.info(f"{interaction.user.name} called /rankedping {game}")
        guild = interaction.guild

        ping_role_name = f"{game} Ping"
        ping_role = discord.utils.get(guild.roles, name=ping_role_name)

        member = interaction.user
        if ping_role in member.roles:
            await member.remove_roles(ping_role)
            await interaction.response.send_message(f"You have been removed from the {ping_role_name} role.",
                                                    ephemeral=True)
        else:
            await member.add_roles(ping_role)
            await interaction.response.send_message(f"You have been added to the {ping_role_name} role!",
                                                    ephemeral=True)

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
        print(game_queues)
        for game in game_queues.values():
            print(game)
            red = game.red_role
            blue = game.blue_role
            print(red, blue)
            if red in interaction.user.roles or blue in interaction.user.roles:
                await interaction.followup.send(game.full_game_name)
                return

    @app_commands.choices(game=games_choices)
    @app_commands.command(name="queue", description="Add yourself to the queue")
    async def q(self, interaction: discord.Interaction, game: str):
        await self.queue_player(interaction, game, False)

    async def queue_player(self, interaction: discord.Interaction, game: str, from_button: bool=False):
        logger.info(f"{interaction.user.name} called /q")
        await interaction.response.defer(ephemeral=True)

        url = f'https://secondrobotics.org/api/ranked/player/{interaction.user.id}'

        x = requests.get(url, headers=HEADER)
        res = x.json()
        logger.info(res)

        if not res["exists"]:
            await interaction.followup.send(
                f"You must register for an account at <{REGISTRATION_URL}> before you can queue.",
                ephemeral=True)
            return

        qdata = game_queues[game]

        if (isinstance(interaction.channel, discord.TextChannel) and
                (interaction.channel.id == QUEUE_CHANNEL_ID or from_button) and
                isinstance(interaction.user, discord.Member)):
            player = interaction.user
            if player in qdata.queue:
                await interaction.followup.send("You are already in this queue.", ephemeral=True)
                return

            roles = [y.id for y in interaction.user.roles]
            if qdata.red_role is not None and qdata.blue_role is not None:
                ranked_roles = [qdata.red_role.id, qdata.blue_role.id]
                queue_check = bool(set(roles).intersection(ranked_roles))
                if queue_check:
                    await interaction.followup.send("You are already playing in a game!", ephemeral=True)
                    return


            qdata.queue.put(player)
            await self.update_ranked_display()
            if interaction.user.id == 1112775920332324965:
                followup = await interaction.followup.send(
                f"🟢**{res['display_name']}**🟢\naddedtoqueuefor[{qdata.full_game_name}](https://secondrobotics.org/ranked/{qdata.api_short})."
                f"*({qdata.queue.qsize()}/{qdata.game_size})*\n"
                f"[Edit Display Name](https://secondrobotics.org/user/settings/)", ephemeral=True)
            else:

                followup = await interaction.followup.send(
                    f"🟢 **{res['display_name']}** 🟢\nadded to queue for [{qdata.full_game_name}](https://secondrobotics.org/ranked/{qdata.api_short})."
                    f" *({qdata.queue.qsize()}/{qdata.game_size})*\n"
                    f"[Edit Display Name](https://secondrobotics.org/user/settings/)", ephemeral=True)
            
            await followup.delete(delay=60)

            if (qdata.queue.qsize() == 3 and qdata.game_size == 4) or (
                    qdata.queue.qsize() == 4 and qdata.game_size == 6):
                current_time = datetime.now()
                if qdata.last_ping_time is None or (current_time - qdata.last_ping_time).total_seconds() > 3600:
                    qdata.last_ping_time = current_time

                    ping_role_name = f"{qdata.game_type} Ping"
                    logger.info(f"Pinging {ping_role_name}")
                    ping_role = discord.utils.get(
                        interaction.guild.roles, name=ping_role_name)
                    if ping_role is not None:
                        await queue_channel.send(
                            f"{ping_role.mention} Queue for [{qdata.full_game_name}](https://secondrobotics.org/ranked/{qdata.api_short}) is now {qdata.queue.qsize()}/{qdata.game_size}!")

            if qdata.queue.qsize() >= qdata.game_size:
                if qdata.red_series == 2 or qdata.blue_series == 2:
                    await self.start_match(qdata, interaction, from_button)
                else:
                    await queue_channel.send(
                        f"Queue for [{qdata.full_game_name}](https://secondrobotics.org/ranked/{qdata.api_short}) is now full! You can start as soon as the current match concludes.")
            else:
                qstatus = await queue_channel.send(
                    f"Queue for [{qdata.full_game_name}](https://secondrobotics.org/ranked/{qdata.api_short}) is now **[{qdata.queue.qsize()}/{qdata.game_size}]**")
                await qstatus.delete(delay=30)
        else:
            await interaction.followup.send(QUEUE_CHANNEL_ERROR_MSG, ephemeral=True)

    @app_commands.choices(game=games_choices)
    @app_commands.command(description="Force queue players")
    async def queueall(self, interaction: discord.Interaction,
                       game: str,
                       member1: Optional[discord.Member] = None,
                       member2: Optional[discord.Member] = None,
                       member3: Optional[discord.Member] = None,
                       member4: Optional[discord.Member] = None,
                       member5: Optional[discord.Member] = None,
                       member6: Optional[discord.Member] = None):
        logger.info(f"{interaction.user.name} called /queueall")
        qdata = game_queues[game]

        members = [member1, member2, member3, member4, member5, member6]
        members_clean = [i for i in members if i]
        added_players = ""
        if isinstance(interaction.user, discord.Member) and any(role.id == EVENT_STAFF_ID for role in interaction.user.roles):
            for member in members_clean:
                qdata.queue.put(member)
                added_players += f"\n{member.display_name}"
            await interaction.response.send_message(f"Successfully added{added_players} to the queue.",
                                                    ephemeral=True)
        else:
            await interaction.response.send_message("Nerd.", ephemeral=True)

        for member in members_clean:
            qdata.queue.put(member)
            added_players += f"\n{member.display_name}"
        await interaction.response.send_message(f"Successfully added{added_players} to the queue.",
                                                ephemeral=True)

        await self.update_ranked_display()

    @app_commands.choices(game=games_choices)
    @app_commands.command(description="Start a game")
    async def startmatch(self, interaction: discord.Interaction, game: str):
        logger.info(f"{interaction.user.name} called /startmatch")
        await interaction.response.defer()
        await self.start_match(game_queues[game], interaction, False)

    async def start_match(self, qdata: XrcGame, interaction: discord.Interaction, from_button: bool=False):
        if qdata.queue.qsize() < qdata.game_size:
            await interaction.followup.send("Queue is not full.", ephemeral=True)
            return

        if qdata.red_series == 2 or qdata.blue_series == 2:
            qdata.red_series = 0
            qdata.blue_series = 0
        else:
            await interaction.followup.send("Current match incomplete.", ephemeral=True)
            return

        if (interaction.channel is None or interaction.channel.id != QUEUE_CHANNEL_ID) and not from_button:
            await interaction.followup.send(QUEUE_CHANNEL_ERROR_MSG, ephemeral=True)
            return

        password = str(random.randint(100, 999))
        min_players = games_players[qdata.api_short]
        message, port = start_server_process(
            qdata.server_game, f"Ranked{qdata.api_short}", password, min_players=min_players)
        if port == -1:
            logger.warning("Server couldn't auto-start for ranked: " + message)
        else:
            qdata.server_port = port
            qdata.server_password = password

        await self.random(interaction, qdata.api_short)

    @app_commands.choices(game=games_choices)
    @app_commands.command(name="queuestatus", description="View who is currently in the queue")
    @app_commands.checks.has_any_role("Event Staff")
    async def queuestatus(self, interaction: discord.Interaction, game: str):
        logger.info(f"{interaction.user.name} called /queuestatus")
        qdata = game_queues[game]
        try:
            players = []
            for _ in range(0, 2):
                players = [qdata.queue.get() for _ in range(qdata.queue.qsize())]
                for player in players:
                    qdata.queue.put(player)
            embed = discord.Embed(
                color=0xcda03f, title=f"Signed up players for {game}")

            embed.set_thumbnail(url=qdata.game_icon)
            embed.add_field(name='Players',
                            value="{}".format(
                                "\n".join([player.mention for player in players])),
                            inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Empty:
            await interaction.response.send_message(f"Nobody is in queue for {game}!", ephemeral=True)
        except Exception as e:
            logger.error(f"Unexpected error occurred: {e}")
            await interaction.response.send_message(f"An error occurred while fetching the queue for {game}.", ephemeral=True)

    @app_commands.choices(game=games_choices)
    @app_commands.command(name="leave", description="Remove yourself from the queue")
    async def leave(self, interaction: discord.Interaction, game: str):
        logger.info(f"{interaction.user.name} called /leave")
        qdata = game_queues[game]

        ephemeral = False

        if (isinstance(interaction.channel, discord.TextChannel) and
                isinstance(interaction.user, discord.Member) and
                interaction.channel.id == QUEUE_CHANNEL_ID):
            player = interaction.user
            if player in qdata.queue:
                qdata.queue.remove(player)
                await self.update_ranked_display()
                cleaned_display_name = ''.join(
                    char for char in player.display_name if char.isalnum())
                message = f"🔴 **{cleaned_display_name}** 🔴\nremoved from the queue for [{qdata.full_game_name}](https://secondrobotics.org/ranked/{qdata.api_short}). *({qdata.queue.qsize()}/{qdata.game_size})*"
            else:
                message = "You aren't in this queue."
                ephemeral = True
        else:
            message = QUEUE_CHANNEL_ERROR_MSG
            ephemeral = True

        await interaction.response.send_message(message, ephemeral=ephemeral)
        await interaction.channel.send(
            f"Queue for [{qdata.full_game_name}](https://secondrobotics.org/ranked/{qdata.api_short}) is now **[{qdata.queue.qsize()}/{qdata.game_size}]**",
            delete_after=60)

    async def leave_all_queues(self, interaction: discord.Interaction, via_command = False):
        send_publicly = False

        if (not via_command or (isinstance(interaction.channel, discord.TextChannel) and
                isinstance(interaction.user, discord.Member) and
                interaction.channel.id == QUEUE_CHANNEL_ID and via_command)):
            player = interaction.user
            cleaned_display_name = ''.join(
                char for char in player.display_name if char.isalnum())
            message = f"🔴 **{cleaned_display_name}** 🔴\nremoved from the queue for "
            dequeued = []
            for game in game_queues.values():
                qdata = game
                if player in qdata.queue:
                    qdata.queue.remove(player)
                    message += f"__{qdata.full_game_name}__. *({qdata.queue.qsize()}/{qdata.game_size})*, "
                    dequeued.append(qdata)
                    send_publicly = True
            await self.update_ranked_display()
            if (len(dequeued) == 0):
                message = "You aren't in any queues."
                send_publicly = False
        else:
            message = QUEUE_CHANNEL_ERROR_MSG
            return

        await interaction.response.send_message(message, ephemeral=True, delete_after=30)
        if send_publicly:
            await queue_channel.send(message)
        for qdata in dequeued:        
            await queue_channel.send(
                f"Queue for [{qdata.full_game_name}](https://secondrobotics.org/ranked/{qdata.api_short}) is now **[{qdata.queue.qsize()}/{qdata.game_size}]**",
                delete_after=60)
        

    @app_commands.command(name="leaveall", description="Remove yourself from all queues")
    async def leaveall(self, interaction: discord.Interaction):
        logger.info(f"{interaction.user.name} called /leaveall")
        await self.leave_all_queues(interaction, True)


    @app_commands.choices(game=games_choices)
    @app_commands.command(description="Remove someone else from the queue")
    @app_commands.checks.has_any_role("Event Staff")
    async def kick(self, interaction: discord.Interaction, player: discord.Member, game: str):
        logger.info(f"{interaction.user.name} called /kick")
        qdata = game_queues[game]
        if isinstance(interaction.channel, discord.TextChannel) and interaction.channel.id == QUEUE_CHANNEL_ID:
            if player in qdata.queue:
                qdata.queue.remove(player)
                await self.update_ranked_display()
                await interaction.response.send_message(
                    f"**{player.display_name}**\nremoved to queue for [{game}](https://secondrobotics.org/ranked/{qdata.api_short}). *({qdata.queue.qsize()}/{qdata.game_size})*")
            else:
                await interaction.response.send_message("{} is not in queue.".format(player.display_name),
                                                        ephemeral=True)

    @app_commands.choices(game=games_choices)
    @app_commands.command(description="Edits the last match score (in the event of a human error)", name="editmatch")
    @app_commands.checks.cooldown(1, 20.0, key=lambda i: i.guild_id)
    async def edit_match(self, interaction: discord.Interaction, game: str, red_score: int, blue_score: int):
        logger.info(f"{interaction.user.name} called /editmatch")
        await interaction.response.defer()

        qdata = game_queues[game]

        if EVENT_STAFF_ID in [role.id for role in interaction.user.roles]:
            await handle_score_edit(interaction, qdata, red_score, blue_score)
        else:
            roles = [role.id for role in interaction.user.roles]
            if qdata.red_role and qdata.blue_role:
                ranked_roles = [qdata.red_role.id, qdata.blue_role.id]
            else:
                ranked_roles = []

            if not any(role in ranked_roles for role in roles):
                await interaction.followup.send("You are not eligible to edit a score.", ephemeral=True)
                return

            await interaction.followup.send("A score edit is being attempted. Please vote.", view=VoteView(interaction, qdata, red_score, blue_score))

    @app_commands.command(description="Submit Score")
    @app_commands.checks.cooldown(1, 20.0, key=lambda i: i.guild_id)
    async def submit(self, interaction: discord.Interaction, red_score: int, blue_score: int):
        logger.info(f"{interaction.user.name} called /submit")
        await interaction.response.defer()

        qdata = None
        for game in game_queues.values():
            red = game.red_role
            blue = game.blue_role
            if red in interaction.user.roles or blue in interaction.user.roles:
                logger.info(f"found game {game}")
                qdata = game
                logger.info(f"qdata {qdata}")
                break
        if qdata is None:
            await interaction.followup.send("You are ineligible to submit!", ephemeral=True)
            return

        if (
                isinstance(interaction.channel, discord.TextChannel)
                and interaction.channel.id == QUEUE_CHANNEL_ID
                and isinstance(interaction.user, discord.Member)
        ):
            roles = [role.id for role in interaction.user.roles]

            if qdata.red_role and qdata.blue_role:
                ranked_roles = [EVENT_STAFF_ID,
                                qdata.red_role.id, qdata.blue_role.id]
            else:
                ranked_roles = [EVENT_STAFF_ID]

            submit_check = any(role in ranked_roles for role in roles)

            if not submit_check:
                await interaction.followup.send("You are ineligible to submit!", ephemeral=True)
                return

            if qdata.red_series == 2 or qdata.blue_series == 2:
                await interaction.followup.send("Series is complete already!", ephemeral=True)
                return
        else:
            await interaction.followup.send(QUEUE_CHANNEL_ERROR_MSG, ephemeral=True)
            return

        if int(red_score) > int(blue_score):
            qdata.red_series += 1

        elif int(red_score) < int(blue_score):
            qdata.blue_series += 1

        gg = True
        if qdata.red_series == 2:
            await interaction.followup.send("🟥 Red Wins! 🟥")
        elif int(blue_score) < int(red_score):
            qdata.blue_series += 1
        if qdata.blue_series == 2:
            await interaction.followup.send("🟦 Blue Wins! 🟦")

        else:
            await interaction.followup.send("Score Submitted")
            gg = False

        red_ids = [player.id for player in qdata.game.red] if qdata.game else []
        blue_ids = [
            player.id for player in qdata.game.blue] if qdata.game else []

        url = f'https://secondrobotics.org/api/ranked/{qdata.api_short}/match/'
        json_data = {
            "red_alliance": red_ids,
            "blue_alliance": blue_ids,
            "red_score": red_score,
            "blue_score": blue_score
        }
        response = requests.post(url, json=json_data, headers=HEADER).json()
        logger.info(response)

        embed = discord.Embed(color=0x34eb3d,
                              title=f"[{qdata.full_game_name}] Score submitted | 🟥 {qdata.red_series}-{qdata.blue_series}  🟦 |")
        embed.set_thumbnail(url=qdata.game_icon)

        red = "\n".join(
            f"[{response['red_display_names'][i]}](https://secondrobotics.org/ranked/{qdata.api_short}/{response['red_player_elos'][i]['player']}) "
            f"`[{round(player['elo'], 2)}]` ```diff\n{'%+.2f' % (round(response['red_elo_changes'][i], 3))}\n```"
            for i, player in enumerate(response['red_player_elos'])
        )

        blue = "\n".join(
            f"[{response['blue_display_names'][i]}](https://secondrobotics.org/ranked/{qdata.api_short}/{response['blue_player_elos'][i]['player']}) "
            f"`[{round(player['elo'], 2)}]` ```diff\n{'%+.2f' % (round(response['blue_elo_changes'][i], 3))}\n```"
            for i, player in enumerate(response['blue_player_elos'])
        )

        embed.add_field(name=f'RED 🟥 ({red_score})',
                        value=red,
                        inline=True)
        embed.add_field(name=f'BLUE 🟦 ({blue_score})',
                        value=blue,
                        inline=True)

        class RejoinQueueView(discord.ui.View):
            def __init__(self, qdata: XrcGame, cog: Ranked):
                super().__init__()
                self.qdata = qdata
                self.cog = cog

            @discord.ui.button(label="Rejoin Queue", style=discord.ButtonStyle.blurple, emoji="🔄")
            async def rejoin_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
                await self.cog.queue_player(interaction, self.qdata.api_short)

        if gg:
            await interaction.channel.send(embed=embed, view=RejoinQueueView(qdata, self))
            await remove_roles(interaction.user.guild, qdata)

            if qdata.server_port:
                stop_server_process(qdata.server_port)

            lobby = self.bot.get_channel(LOBBY_VC_ID)
            for channel in [qdata.red_channel, qdata.blue_channel]:
                if channel:
                    for member in channel.members:
                        await member.move_to(lobby)
                    await channel.delete()
        else:
            await interaction.channel.send(embed=embed)

    async def random(self, interaction, game_type):
        qdata = create_game(game_type)

        if not qdata.game:
            await interaction.followup.send("No game found", ephemeral=True)
            return

        logger.info(f"Getting players for {qdata.game_type}")
        red = random.sample(qdata.game.players, int(qdata.team_size))
        for player in red:
            qdata.game.add_to_red(player)

        logger.info(f"Red: {red}")

        blue = list(qdata.game.players)
        for player in blue:
            qdata.game.add_to_blue(player)

        logger.info(f"Blue: {blue}")

        await self.display_teams(interaction, qdata)

    async def display_teams(self, ctx, qdata: XrcGame):

        async def fetch_player_elo(game, user_id):
            url = f'https://secondrobotics.org/api/ranked/{game}/player/{user_id}'
            response = requests.get(url)
            if response.status_code == 200:
                return response.json().get('elo', 0)
            else:
                logger.error(f"Failed to fetch ELO for player {user_id}: {response.status_code}")
                return 0

        async def assign_role(player, role):
            await player.add_roles(role)

        async def move_player(player, channel):
            try:
                await player.move_to(channel)
            except Exception as e:
                logger.error(e)
        
        logger.info(f"Displaying teams for {qdata.game_type}")
        channel = ctx.channel
        self.category = self.category or get(ctx.guild.categories, id=CATEGORY_ID)
        self.staff = self.staff or get(ctx.guild.roles, id=EVENT_STAFF_ID)
        self.bots = self.bots or get(ctx.guild.roles, id=BOTS_ROLE_ID)

        logger.info(f"Getting IP for {qdata.game_type}")

        red_field = "\n".join([f"🟥{player.mention}" for player in qdata.game.red])
        blue_field = "\n".join([f"🟦{player.mention}" for player in qdata.game.blue])

        description = f"""Server "Ranked{qdata.api_short}" started for you with password **{qdata.server_password}**
        || IP: {ip} Port: {qdata.server_port}||
        [Adjust Display Name](https://secondrobotics.org/user/settings/) | [Leaderboard](https://secondrobotics.org/ranked/{qdata.api_short})""" if qdata.server_port else None

        embed = discord.Embed(
            color=0x34dceb, title=f"Teams have been picked for {qdata.full_game_name}!", description=description
        )
        embed.set_thumbnail(url=qdata.game_icon)

        # Fetch ELOs concurrently
        red_elo_tasks = [fetch_player_elo(qdata.api_short, player.id) for player in qdata.game.red]
        blue_elo_tasks = [fetch_player_elo(qdata.api_short, player.id) for player in qdata.game.blue]

        red_elos = await asyncio.gather(*red_elo_tasks)
        blue_elos = await asyncio.gather(*blue_elo_tasks)

        # Calculate average ELO
        avg_red_elo = sum(red_elos) / len(red_elos) if red_elos else 0
        avg_blue_elo = sum(blue_elos) / len(blue_elos) if blue_elos else 0

        embed.add_field(name=f'RED (Avg ELO: {avg_red_elo:.2f})', value=red_field, inline=True)
        embed.add_field(name=f'BLUE (Avg ELO: {avg_blue_elo:.2f})', value=blue_field, inline=True)

        await queue_channel.send(embed=embed)

        qdata.red_role, qdata.blue_role = await asyncio.gather(
            ctx.guild.create_role(name=f"Red {qdata.full_game_name}", colour=discord.Color(0xFF0000)),
            ctx.guild.create_role(name=f"Blue {qdata.full_game_name}", colour=discord.Color(0x0000FF))
        )

        overwrites_red = {ctx.guild.default_role: discord.PermissionOverwrite(connect=False),
                        qdata.red_role: discord.PermissionOverwrite(connect=True),
                        self.staff: discord.PermissionOverwrite(connect=True),
                        self.bots: discord.PermissionOverwrite(connect=True)}
        overwrites_blue = {ctx.guild.default_role: discord.PermissionOverwrite(connect=False),
                        qdata.blue_role: discord.PermissionOverwrite(connect=True),
                        self.staff: discord.PermissionOverwrite(connect=True),
                        self.bots: discord.PermissionOverwrite(connect=True)}

        if qdata.game_size != 2:
            qdata.red_channel, qdata.blue_channel = await asyncio.gather(
                ctx.guild.create_voice_channel(name=f"🟥{qdata.full_game_name}🟥",
                                            category=self.category, overwrites=overwrites_red),
                ctx.guild.create_voice_channel(name=f"🟦{qdata.full_game_name}🟦",
                                            category=self.category, overwrites=overwrites_blue)
            )

            if not qdata.game:
                await channel.send("Error: No game found")
                return

        tasks = []
        for player in qdata.game.red | qdata.game.blue:
            tasks.append(assign_role(player, qdata.red_role if player in qdata.game.red else qdata.blue_role))
            if qdata.game_size != 2:
                tasks.append(move_player(player, qdata.red_channel if player in qdata.game.red else qdata.blue_channel))

        await asyncio.gather(*tasks)

        await queue_channel.send(f"{qdata.red_role.mention} {qdata.blue_role.mention}", delete_after=30)
        await self.update_ranked_display()

    @app_commands.choices(game=games_choices)
    @app_commands.command(name="clearmatch", description="Clears current running match")
    async def clearmatch(self, interaction: discord.Interaction, game: str):
        logger.info(f"{interaction.user.name} called /clearmatch")
        qdata = game_queues[game]

        ephemeral = False
        if isinstance(interaction.user, discord.Member) and EVENT_STAFF_ID in [y.id for y in
                                                                                   interaction.user.roles]:
            await interaction.response.defer()
            await self.do_clear_match(interaction.user.guild, qdata)
            message = "Cleared successfully!"
        else:
            message = "You don't have permission to do that!"
            ephemeral = True

        await interaction.followup.send(message, ephemeral=ephemeral)

    async def do_clear_match(self, guild: discord.Guild, qdata: XrcGame):
        if qdata.server_port:
            stop_server_process(qdata.server_port)

        qdata.red_series = qdata.blue_series = 2

        await remove_roles(guild, qdata)

        lobby = self.bot.get_channel(LOBBY_VC_ID)
        for channel in [qdata.red_channel, qdata.blue_channel]:
            if channel:
                for member in channel.members:
                    await member.move_to(lobby)
                await channel.delete()

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


class Game:
    def __init__(self, players: list[discord.Member]):
        self.players = set(players)
        if len(players) > 2:
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


queue_joins = {}
last_active = {}


class PlayerQueue(Queue):
    def _init(self, maxsize):
        self.queue = OrderedSet()

    def _put(self, item: discord.Member):
        self.queue.add(item)
        queue_joins[(self, item)] = datetime.now()

    def _get(self):
        return self.queue.pop()

    def remove(self, value: discord.Member):
        self.queue.remove(value)
        queue_joins.pop((self, value), None)

    def __contains__(self, item: discord.Member):
        with self.mutex:
            return item in self.queue


game_queues = {game['short_code']: XrcGame(
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
        if queue.server_port == server:
            if cog and guild:
                await cog.do_clear_match(guild, queue)
                logger.info(
                    f"Match cleared for server {server} due to inactivity")

            if queue.game:
                for player in queue.game.players:
                    await player.send(
                        "Your ranked match has been cancelled due to inactivity.")
            return

    stop_server_process(server)


async def server_has_players(server: int) -> bool:
    needed_players = 1
    for queue in game_queues.values():
        if queue.server_port == server:
            needed_players = queue.game_size
            break

    process = servers_active.get(server, None)
    if process is None or process.poll() is not None or process.stdout is None or process.stdin is None:
        return False

    process.stdin.write(b"PLAYERS\\n")
    process.stdin.flush()

    while True:
        line = process.stdout.readline().decode("utf-8")
        if line != b'_BEGIN_\n':
            break

    players = []
    while True:
        line = process.stdout.readline().decode("utf-8")
        if line == b'_END_\n':
            break
        players.append(line.strip())

    if len(players) >= needed_players:
        return True

    return False


async def warn_server_inactivity(server: int):
    for queue in game_queues.values():
        if queue.server_port == server:
            if queue.game:
                for player in queue.game.players:
                    await player.send(
                        "Your ranked match has been inactive - if all players are not present within 5 minutes, the match will be cancelled.")
            return


class GameButton(discord.ui.Button['game']):
    def __init__(self, game: str, short_code: str, cog: commands.Cog):
        is_daily = game not in list(server_games.keys())[-3:]

        super().__init__(style=discord.ButtonStyle.primary if is_daily else discord.ButtonStyle.green, label=game)
        self.game = game
        self.cog = cog
        self.short_code = short_code

    async def callback(self, interaction: discord.Interaction):
        logger.info('{} game button pressed'.format(self.game))

        embed = discord.Embed(title=self.game, description=f"Queue for {self.game}!", color=0x00ff00)

        try:
            game_icon = game_logos[self.game]
        except:
            game_icon = None

        if game_icon:
            embed.set_thumbnail(url=game_icon)

        view = discord.ui.View()

        max_alliance = int(default_game_players[server_games[self.game]]/2)

        logger.info("Max of {} players per alliance, generating buttons".format(max_alliance))

        for n in range(1, max_alliance+1):
            view.add_item(QueueButton(game=f'{self.game} {n}v{n}', short_code=self.short_code+f'{n}v{n}', display=f'{n}v{n}', cog=self.cog))
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True, delete_after=30)

class QueueButton(discord.ui.Button['queue']):
    def __init__(self, game: str, short_code: str, display: str, cog: commands.Cog):
        super().__init__(style=discord.ButtonStyle.green, label=display)
        self.game = game
        self.short_code = short_code
        self.display = display
        self.cog = cog
    
    async def callback(self, interaction: discord.Interaction):
        logger.info('{} button pressed!'.format(self.game))

        await self.cog.queue_player(interaction, self.short_code, True)
