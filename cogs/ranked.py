import asyncio
from datetime import datetime
import subprocess
from typing import Dict, Optional
from discord import app_commands
import random
from queue import Queue
from discord.utils import get
import discord
import logging
from discord.ext import commands
from collections.abc import MutableSet
import requests
from dotenv import load_dotenv
import os
from discord.app_commands import Choice
import zipfile
import shutil
from discord.ext import tasks

logger = logging.getLogger('discord')
load_dotenv()

SRC_API_TOKEN = os.getenv('SRC_API_TOKEN')
if not SRC_API_TOKEN:
    logger.fatal('SRC_API_TOKEN not found')
    raise RuntimeError('SRC_API_TOKEN not found')

GUILD_ID = 637407041048281098
QUEUE_CHANNEL = 824691989366046750

team_size = 6
team_size_alt = 4
approved_channels = [824691989366046750, 712297302857089025,
                     650967104933330947, 754569102873460776, 754569222260129832]
HEADER = {"x-api-key": SRC_API_TOKEN}

PORTS = [11115, 11116, 11117, 11118, 11119, 11120]
# dictionary mapping port number to process of running server
servers_active: Dict[int, subprocess.Popen] = {}

listener = commands.Cog.listener

ports_choices = [Choice(name=str(port), value=port) for port in PORTS]

games = requests.get("https://secondrobotics.org/api/ranked/").json()

games_choices = [Choice(name=game['name'], value=game['short_code'])
                 for game in games]

games_players = {game['short_code']: game['players_per_alliance'] * 2
                 for game in games}

# disctionary mapping game name to game number string
server_games = {
    "Splish Splash": "0",
    "Relic Recovery": "1",
    "Rover Ruckus": "2",
    "Skystone": "3",
    "Infinite Recharge": "4",
    "Change Up": "5",
    "Bot Royale": "6",
    "Ultimate Goal": "7",
    "Tipping Point": "8",
    "Freight Frenzy": "9",
    "Rapid React": "10",
    "Spin Up": "11",
    "Power Play": "12",
    "Charged Up": "13",
}

# dictionary mapping game name to default number of players
default_game_players = {
    "Splish Splash": 4,
    "Relic Recovery": 4,
    "Rover Ruckus": 4,
    "Skystone": 4,
    "Infinite Recharge": 6,
    "Change Up": 4,
    "Bot Royale": 6,
    "Ultimate Goal": 4,
    "Tipping Point": 4,
    "Freight Frenzy": 4,
    "Rapid React": 6,
    "Spin Up": 4,
    "Power Play": 4,
    "Charged Up": 6,
}

# dictionary mapping game name to game logo url
game_logos = {
    "Skystone": "https://i.redd.it/iblf4hi92vt21.png",
    "Infinite Recharge": "https://upload.wikimedia.org/wikipedia/en/2/2b/Infinite_Recharge_Logo.png",
    "Rapid React": "https://upload.wikimedia.org/wikipedia/en/thumb/0/08/Rapid_React_Logo.svg/1200px-Rapid_React_Logo.svg.png",
    "Spin Up": "https://www.roboticseducation.org/app/uploads/2022/05/Spin-Up-Logo.png",
    "Charged Up": "https://upload.wikimedia.org/wikipedia/en/thumb/b/b7/Charged_Up_Logo.svg/1024px-Charged_Up_Logo.svg.png",
}

server_games_choices = [
    Choice(name=game, value=server_games[game]) for game in server_games.keys()
]

# dictionary mapping game number string to game settings string
server_game_settings = {
    "4": "0:1:0:1:25:5:5100:0:1:1:1:1:1:1:1:14:7:1:1:1:0:15:100:0:1:2021:25",
    "7": "30:1:0:0:10:0",
    "9": "1:1:1:1:30:10",
    "13": "1:5:1:4:0:5:2:0:1:1:1:1:1:1:1:14:7:1:1:1:0:15:100",
}

# dictionary mapping game number string to game restart mode number
server_restart_modes = {
    "3": 3,
    "4": 2,
}


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
        try:
            self.game_icon = game_logos[game]
        except:
            self.game_icon = None


async def remove_roles(guild: discord.Guild, qdata: XrcGame):
    # Remove any current roles

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

    # Remove selected players from all other queues
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


def start_server_process(game: str, comment: str, password: str = "", admin: str = "Admin",
                         restart_mode: int = -1, frame_rate: int = 120, update_time: int = 10,
                         tournament_mode: bool = True, start_when_ready: bool = True,
                         register: bool = True, spectators: int = 4, min_players: int = -1,
                         ):
    server_path = "./server/xRC Simulator.x86_64"

    if not os.path.exists(server_path):
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

    game_settings = server_game_settings[game] if game in server_game_settings else ""
    if restart_mode == -1:
        restart_mode = server_restart_modes[game] if game in server_restart_modes else 1

    if min_players == -1:
        min_players = default_game_players[game] if game in default_game_players else 4

    servers_active[port] = subprocess.Popen(
        [server_path, "-batchmode", "-nographics", f"RouterPort={port}", f"Port={port}", f"Game={game}",
         f"GameOption={restart_mode}", f"FrameRate={frame_rate}", f"Tmode={'On' if tournament_mode else 'Off'}",
         f"Register={'On' if register else 'Off'}", f"Spectators={spectators}", f"UpdateTime={update_time}",
         f"MaxData=10000", f"StartWhenReady={'On' if start_when_ready else 'Off'}", f"Comment={comment}",
         f"Password={password}", f"Admin={admin}", f"GameSettings={game_settings}", f"MinPlayers={min_players}"]
    )

    logger.info(f"Server launched on port {port}: '{comment}'")
    return f"✅ Launched server '{comment}' on port {port}", port


def stop_server_process(port: int):
    if port not in servers_active:
        return f"⚠ Server on port {port} not found"

    logger.info(f"Shutting down server on port {port}")

    servers_active[port].terminate()
    del servers_active[port]

    logger.info(f"Server on port {port} shut down")
    return f"✅ Server on port {port} shut down"


class Ranked(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ranked_display = None
        self.check_queue_joins.start()
        self.check_empty_servers.start()

    async def update_ranked_display(self):
        if self.ranked_display is None:
            logger.info("Finding Ranked Queue Display")

            qstatus_channel = get(
                self.bot.get_all_channels(), id=1009630461393379438)
            async for msg in qstatus_channel.history(limit=None):
                if msg.author.id == self.bot.user.id:
                    self.ranked_display = msg
                    logger.info("Found Ranked Queue Display")
                    break

        if self.ranked_display is None:
            return

        embed = discord.Embed(title="xRC Sim Ranked Queues",
                              description="Ranked queues are open!", color=0x00ff00)
        embed.set_thumbnail(
            url="https://secondrobotics.org/logos/xRC%20Logo.png")
        active_queues = 0
        for qdata in game_queues.values():
            if qdata.queue.qsize() > 0:
                active_queues += 1
                embed.add_field(name=qdata.full_game_name, value=f"*{qdata.queue.qsize()}/{qdata.game_size}*"
                                                                 f" players in queue", inline=False)
        if active_queues == 0:
            embed.add_field(name="No current queues",
                            value="Queue to get a match started!", inline=False)
        await self.ranked_display.edit(embed=embed)

    @app_commands.command(description="Updates to the latest release version of xRC Sim")
    @app_commands.checks.has_any_role("Event Staff")
    async def update(self, interaction: discord.Interaction):
        logger.info(f"{interaction.user.name} called /update")
        await interaction.response.defer(thinking=True)

        zip_path = "./xRC_Linux_Server.zip"

        if os.path.exists(zip_path):
            os.remove(zip_path)

        url = "https://xrcsimulator.org/Downloads/xRC_Linux_Server.zip"
        try:
            file = download_file(url)
        except Exception as e:
            logger.error(e)
            await interaction.followup.send("⚠ Update failed: Could not download file")
            return

        if os.path.exists("./server/"):
            shutil.rmtree("./server/")

        with zipfile.ZipFile(file, 'r') as zip_ref:
            zip_ref.extractall("./server")

        os.chmod("./server/xRC Simulator.x86_64", 0o777)
        os.remove(zip_path)

        await interaction.followup.send("✅ Updated to the latest release version of xRC Sim!")
        logger.info("Updated successfully")

    @app_commands.command(description="Launches a new instance of xRC Sim server", name="launchserver")
    @app_commands.checks.has_any_role("Event Staff")
    @app_commands.choices(game=server_games_choices)
    async def launch_server(self, interaction: discord.Interaction,
                            game: str, comment: str, password: str = "", admin: str = "Admin",
                            restart_mode: int = -1, frame_rate: int = 120, update_time: int = 10,
                            tournament_mode: bool = True, start_when_ready: bool = True,
                            register: bool = True, spectators: int = 4, min_players: int = -1
                            ):
        logger.info(f"{interaction.user.name} called /launchserver")

        result, _ = start_server_process(game, comment, password, admin, restart_mode, frame_rate, update_time,
                                         tournament_mode, start_when_ready, register, spectators, min_players)

        await interaction.response.send_message(result)

    @app_commands.command(description="Shutdown a running xRC Sim server", name="landserver")
    @app_commands.checks.has_any_role("Event Staff")
    @app_commands.choices(port=ports_choices)
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

    @app_commands.command(description="memes")
    @app_commands.checks.has_any_role("Event Staff")
    async def test(self, interaction: discord.Interaction):
        logger.info(f"{interaction.user.name} called /test")

        await self.update_ranked_display()
        await interaction.response.send_message(f"Done", ephemeral=True)

    # FIXME

    # @commands.command(pass_context=True)
    # async def autoq(self, ctx, command=None, command_ctx=None):
    #     if command is not None:
    #         if 699094822132121662 in [y.id for y in ctx.message.author.roles]:
    #             if command.lower() == "kick":
    #                 if command_ctx is not None:
    #                     self.autoq.remove(int(command_ctx))
    #                     await ctx.channel.send(f"Removed <@{command_ctx}> to the autoq list")
    #                     logger.info(command_ctx)
    #                     return
    #     if ctx.channel.id != 824691989366046750:
    #         return
    #     privs = {637411162203619350, 824727390873452634}
    #     roles = set([y.id for y in ctx.message.author.roles])
    #     if roles.intersection(privs):
    #         if ctx.author.id in self.autoq:
    #             await self.leave(ctx)
    #             self.autoq.remove(ctx.author.id)
    #             await ctx.channel.send(f"Removed {ctx.author.mention} from the autoq list")
    #         else:
    #             await self.q(ctx)
    #             self.autoq.append(ctx.author.id)
    #             await ctx.channel.send(f"Added {ctx.author.mention} to the autoq list")
    #     else:
    #         await ctx.channel.send(
    #             f"Autoqing is only available to patreons. To become a patreon check out this link! https://www.patreon.com/BrennanB ")
    #     logger.info(self.autoq)

    # async def queue_auto(self, ctx):
    #
    #     logger.info(qdata)
    #     for id in self.autoq:
    #         member = ctx.guild.get_member(id)
    #         qdata['queue'].put(member)
    #         await ctx.channel.send(
    #             "{} was autoqed. ({:d}/{:d})".format(member.display_name, qdata['queue'].qsize(),
    #                                                  qdata['team_size']))

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
        if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator:
            for member in members_clean:
                qdata.queue.put(member)
                added_players += f"{member.display_name}\n"
            await interaction.response.send_message(f"Successfully added\n{added_players} to the queue.",
                                                    ephemeral=True)
        else:
            await interaction.response.send_message("Nerd.", ephemeral=True)
        await self.update_ranked_display()

    # @commands.command(pass_context=True)
    # async def seriestest(self, ctx):
    #     await ctx.channel.send(f"{self.red_series} {self.blue_series}")
    @app_commands.choices(game=games_choices)
    @app_commands.command(name="queue", description="Add yourself to the queue")
    async def q(self, interaction: discord.Interaction, game: str):
        await self.queue_player(interaction, game)

    async def queue_player(self, interaction: discord.Interaction, game: str):
        """Enter's player into queue for upcoming matches"""
        logger.info(f"{interaction.user.name} called /q")

        url = f'https://secondrobotics.org/api/ranked/player/{interaction.user.id}'

        x = requests.get(url, headers=HEADER)
        res = x.json()

        if not res["exists"]:
            await interaction.response.send_message(
                "You must register for an account at <https://www.secondrobotics.org/login> before you can queue.",
                ephemeral=True)
            return

        qdata = game_queues[game]

        if (isinstance(interaction.channel, discord.TextChannel) and
                interaction.channel.id == QUEUE_CHANNEL and
                isinstance(interaction.user, discord.Member)):
            player = interaction.user
            channel = interaction.channel
            if player in qdata.queue:
                await interaction.response.send_message("You are already in this queue.", ephemeral=True)
                return

            roles = [y.id for y in interaction.user.roles]
            if qdata.red_role is None or qdata.blue_role is None:
                pass
            else:
                ranked_roles = [qdata.red_role.id, qdata.blue_role.id]
                # Returns false if not in a game currently. Looks for duplicates between roles and ranked_roles
                queue_check = bool(set(roles).intersection(ranked_roles))
                if queue_check:
                    await interaction.response.send_message("You are already playing in a game!", ephemeral=True)
                    return

            qdata.queue.put(player)
            await self.update_ranked_display()
            await interaction.response.send_message(
                f"🟢 **{player.display_name}** 🟢\nadded to queue for __{qdata.full_game_name}__."
                f" *({qdata.queue.qsize()}/{qdata.game_size})*", ephemeral=True)
            if qdata.queue.qsize() >= qdata.game_size:
                if qdata.red_series == 2 or qdata.blue_series == 2:
                    await interaction.channel.send(f"Queue for {qdata.full_game_name} is now full! Type /startmatch")
                else:
                    await interaction.channel.send(
                        f"Queue for {qdata.full_game_name} is now full! You can start as soon as the current match concludes.")
        else:
            await interaction.response.send_message(f"<#{QUEUE_CHANNEL}> >:(", ephemeral=True)

    #
    @app_commands.choices(game=games_choices)
    @app_commands.checks.has_any_role("Event Staff")
    @app_commands.command()
    async def queuestatus(self, interaction: discord.Interaction, game: str):
        """View who is currently in the queue"""
        logger.info(f"{interaction.user.name} called /queuestatus")
        qdata = game_queues[game]
        try:
            players = []
            for _ in range(0, 2):  # loop to not reverse order
                players = [qdata.queue.get()
                           for _ in range(qdata.queue.qsize())]
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
        except:
            await interaction.response.send_message(f"Nobody is in queue for {game}!", ephemeral=True)

    @app_commands.choices(game=games_choices)
    @app_commands.command(name="leave", description="Remove yourself from the queue")
    async def leave(self, interaction: discord.Interaction, game: str):
        logger.info(f"{interaction.user.name} called /leave")
        qdata = game_queues[game]

        if (isinstance(interaction.channel, discord.TextChannel) and
            isinstance(interaction.user, discord.Member) and
                interaction.channel.id == QUEUE_CHANNEL):
            player = interaction.user
            if player in qdata.queue:
                qdata.queue.remove(player)
                await self.update_ranked_display()
                await interaction.response.send_message(
                    f"🔴 **{player.display_name}** 🔴\nremoved from queue for __{qdata.full_game_name}__."
                    f" *({qdata.queue.qsize()}/{qdata.game_size})*", ephemeral=True)
                return
            else:
                await interaction.response.send_message("You aren't in this queue.", ephemeral=True)
                return
        else:
            await interaction.response.send_message(f"<#{QUEUE_CHANNEL}> >:(", ephemeral=True)

    @app_commands.choices(game=games_choices)
    @app_commands.command(description="Remove someone else from the queue")
    @app_commands.checks.has_any_role("Event Staff")
    async def kick(self, interaction: discord.Interaction, player: discord.Member, game: str):
        logger.info(f"{interaction.user.name} called /kick")
        qdata = game_queues[game]
        if isinstance(interaction.channel, discord.TextChannel) and interaction.channel.id == QUEUE_CHANNEL:
            if player in qdata.queue:
                qdata.queue.remove(player)
                await self.update_ranked_display()
                await interaction.response.send_message(
                    f"**{player.display_name}**\nremoved to queue for __{game}__. *({qdata.queue.qsize()}/{qdata.game_size})*")
                return
            else:
                await interaction.response.send_message("{} is not in queue.".format(player.display_name),
                                                        ephemeral=True)
                return

    # def check_red_first_pick_command(self, message):
    #     qdata = self.get_queue(message)
    #     if not message.content.startswith("{prefix}pick".format(prefix=self.bot.command_prefix)):
    #         return False
    #     if not len(message.mentions) == 1:
    #         return False
    #     if not message.author == qdata['red_captain']:
    #         return False
    #     return True
    #
    # def check_blue_picks_command(self, message):
    #     qdata = self.get_queue(message)
    #     if not message.content.startswith("{prefix}pick".format(prefix=self.bot.command_prefix)):
    #         return False
    #     if not len(message.mentions) == 2:
    #         return False
    #     if not message.author == qdata['blue_captain']:
    #         return False
    #     return True

    # @app_commands.command(description="Number of matches played")
    # async def numplayed(self, interaction: discord.Interaction, user: str):
    #     logger.info(self.elo_results)
    #     await interaction.response.send_message(
    #         len(self.elo_results[self.elo_results[1] == user]) +
    #         len(self.elo_results[self.elo_results[2] == user]) +
    #         len(self.elo_results[self.elo_results[3] == user]) +
    #         len(self.elo_results[self.elo_results[4] == user]) +
    #         len(self.elo_results[self.elo_results[5] == user]) +
    #         len(self.elo_results[self.elo_results[6] == user]))

    @app_commands.choices(game=games_choices)
    @app_commands.command(description="Start a game")
    async def startmatch(self, interaction: discord.Interaction, game: str):
        logger.info(f"{interaction.user.name} called /startmatch")

        qdata = game_queues[game]
        logger.info(qdata.red_series)
        if not qdata.queue.qsize() >= qdata.game_size:
            await interaction.followup.send("Queue is not full.", ephemeral=True)
            return
        if qdata.red_series == 2 or qdata.blue_series == 2:
            qdata.red_series = 0
            qdata.blue_series = 0
        else:
            await interaction.followup.send("Current match incomplete.", ephemeral=True)
            return

        if interaction.channel is None or interaction.channel.id != QUEUE_CHANNEL:
            await interaction.followup.send(f"<#{QUEUE_CHANNEL}> >:(", ephemeral=True)
            return

        await interaction.response.defer()

        password = str(random.randint(100, 999))
        min_players = games_players[game]
        message, port = start_server_process(
            qdata.server_game, f"Ranked{game}", password, min_players=min_players)
        if port == -1:
            logger.warning("Server couldn't auto-start for ranked: " + message)
        else:
            qdata.server_port = port
            qdata.server_password = password
        await self.update_ranked_display()
        await self.random(interaction, game)

    # async def captains(self, ctx):
    #     qdata = self.get_queue(ctx)
    #     channel = ctx.channel
    #     qdata = create_game(ctx)
    #
    #     self.set_queue(ctx, qdata)
    #     await self.do_picks(ctx)

    # async def do_picks(self, ctx):
    #     qdata = self.get_queue(ctx)
    #     channel = ctx.channel
    #     embed = discord.Embed(color=0xfa0000, title="Red Captain's pick!")
    #
    #     await channel.send("Captains: {} and {}".format(*[captain.mention for captain in qdata['game'].captains]))
    #     qdata['red_captain'] = qdata['game'].captains[0]
    #     qdata['game'].add_to_red(qdata['red_captain'])
    #     qdata['blue_captain'] = qdata['game'].captains[1]
    #     qdata['game'].add_to_blue(qdata['blue_captain'])
    #
    #     embed.add_field(name='🟥 RED 🟥',
    #                     value="{}".format("\n".join([player.mention for player in qdata['game'].red])),
    #                     inline=False)
    #     embed.add_field(name='🟦 BLUE 🟦',
    #                     value="{}".format("\n".join([player.mention for player in qdata['game'].blue])),
    #                     inline=False)
    #     embed.add_field(name='Picking Process...',
    #                     value="{mention} Use {prefix}pick [user] to pick 1 player.".format(
    #                         mention=qdata['red_captain'].mention,
    #                         prefix=self.bot.command_prefix),
    #                     inline=False)
    #     embed.add_field(name='Available players:',
    #                     value="{}".format("\n".join([player.mention for player in qdata['game'].players])),
    #                     inline=False)
    #     self.set_queue(ctx, qdata)
    #     # red Pick
    #     await channel.send(embed=embed)
    #     red_pick = None
    #     while not red_pick:
    #         red_pick = await self.pick_red(ctx)
    #     qdata['game'].add_to_red(red_pick)
    #
    #     # Blue Picks
    #     embed = discord.Embed(color=0x00affa, title="Blue Alliance Captain's Picks!")
    #     embed.add_field(name='🟥 RED 🟥',
    #                     value="{}".format("\n".join([player.mention for player in qdata['game'].red])),
    #                     inline=False)
    #     embed.add_field(name='🟦 BLUE 🟦',
    #                     value="{}".format("\n".join([player.mention for player in qdata['game'].blue])),
    #                     inline=False)
    #     embed.add_field(name='Picking Process...',
    #                     value="{mention} Use {prefix}pick [user1] [user2] to pick 2 players.".format(
    #                         mention=qdata['blue_captain'].mention,
    #                         prefix=self.bot.command_prefix),
    #                     inline=False)
    #     embed.add_field(name='Available players:',
    #                     value="{}".format("\n".join([player.mention for player in qdata['game'].players])),
    #                     inline=False)
    #     await channel.send(embed=embed)
    #     blue_picks = None
    #     self.set_queue(ctx, qdata)
    #     while not blue_picks:
    #         blue_picks = await self.pick_blue(ctx)
    #     for blue_pick in blue_picks:
    #         qdata['game'].add_to_blue(blue_pick)
    #
    #     # red Player
    #     last_player = next(iter(qdata['game'].players))
    #     qdata['game'].add_to_red(last_player)
    #     await channel.send("{} added to 🟥 RED 🟥 team.".format(last_player.mention))
    #     await self.display_teams(ctx, qdata)

    # async def pick_red(self, ctx):
    #
    #     channel = ctx.channel
    #     try:
    #         msg = await self.bot.wait_for('message', timeout=45, check=self.check_red_first_pick_command)
    #         if msg:
    #             pick = msg.mentions[0]
    #             if pick not in qdata['game'].players:
    #                 await channel.send("{} not available to pick.".format(pick.display_name))
    #                 return None
    #             await channel.send("Picked {} for 🟥 RED 🟥 team.".format(pick.mention))
    #     except asyncio.TimeoutError:
    #         pick = random.choice(tuple(qdata['game'].players))
    #         await channel.send("Timed out. Randomly picked {} for 🟥 RED 🟥 team.".format(pick.mention))
    #     return pick

    # async def pick_blue(self, ctx):
    #     qdata = self.get_queue(ctx)
    #     channel = ctx.channel
    #     try:
    #         msg = await self.bot.wait_for('message', timeout=45, check=self.check_blue_picks_command)
    #         logger.info(msg)
    #
    #         if msg:
    #             picks = msg.mentions
    #             for pick in picks:
    #                 if pick not in qdata['game'].players:
    #                     await channel.send("{} not available to pick.".format(pick.display_name))
    #                     return None
    #             await channel.send("Picked {} and {} for 🔷 BLUE 🔷 team.".format(*[pick.mention for pick in picks]))
    #             return picks
    #     except asyncio.TimeoutError:
    #         picks = random.sample(qdata['game'].players, 2)
    #         await channel.send(
    #             "Timed out. Randomly picked {} and {} for 🔷 BLUE 🔷 team.".format(*[pick.mention for pick in picks]))
    #         return picks

    # @commands.command(description="pingtest")
    # async def pingtest(self, ctx):
    #     red_check = get(ctx.message.author.guild.roles, name="6 Mans Red")
    #     blue_check = get(ctx.message.author.guild.roles, name="6 Mans Blue")
    #     await ctx.channel.send(f"{red_check.mention} {blue_check.mention}")

    @app_commands.choices(game=games_choices)
    @app_commands.command(description="Submit Score")
    @app_commands.checks.cooldown(1, 20.0, key=lambda i: i.guild_id)
    async def submit(self, interaction: discord.Interaction, game: str, red_score: int, blue_score: int):
        logger.info(f"{interaction.user.name} called /submit")
        await interaction.response.defer()
        logger.info(game)
        qdata = game_queues[game]
        if (isinstance(interaction.channel, discord.TextChannel) and
                interaction.channel.id == QUEUE_CHANNEL and
                isinstance(interaction.user, discord.Member)):
            roles = [y.id for y in interaction.user.roles]

            if qdata.red_role and qdata.blue_role:
                ranked_roles = [699094822132121662,
                                qdata.red_role.id, qdata.blue_role.id]
            else:
                ranked_roles = [699094822132121662]
            # Returns false if not in a game currently. Looks for duplicates between roles and ranked_roles
            submit_check = bool(set(roles).intersection(ranked_roles))
            if submit_check:
                pass
            else:
                await interaction.followup.send("You are ineligible to submit!", ephemeral=True)
                return

            logger.info(qdata.red_series)
            logger.info(qdata.blue_series)
            if qdata.red_series == 2 or qdata.blue_series == 2:
                logger.info("INSIDE")
                logger.info(qdata.red_series)
                logger.info(qdata.blue_series)
                logger.info(interaction)
                await interaction.followup.send("Series is complete already!", ephemeral=True)
                return
        else:
            await interaction.followup.send(f"<#{QUEUE_CHANNEL}> >:(", ephemeral=True)
            return
        logger.info("Checking ")
        # Red wins
        if int(red_score) > int(blue_score):
            qdata.red_series += 1

        # Blue wins
        elif int(red_score) < int(blue_score):
            qdata.blue_series += 1

        logger.info(f"Red {qdata.red_series}")
        logger.info(f"Blue {qdata.blue_series}")
        gg = True
        if qdata.red_series == 2:
            # await self.queue_auto(interaction)
            await interaction.followup.send("🟥 Red Wins! 🟥")
            await remove_roles(interaction.user.guild, qdata)

            if qdata.server_port:
                stop_server_process(qdata.server_port)

            # Kick players back to main lobby
            lobby = self.bot.get_channel(824692700364275743)
            if qdata.red_channel:
                for member in qdata.red_channel.members:
                    await member.move_to(lobby)
                await qdata.red_channel.delete()
            if qdata.blue_channel:
                for member in qdata.blue_channel.members:
                    await member.move_to(lobby)
                await qdata.blue_channel.delete()

        elif qdata.blue_series == 2:
            # await self.queue_auto(interaction)
            await interaction.followup.send("🟦 Blue Wins! 🟦")
            await remove_roles(interaction.user.guild, qdata)

            if qdata.server_port:
                stop_server_process(qdata.server_port)

            # Kick players back to lobby
            lobby = self.bot.get_channel(824692700364275743)
            if qdata.red_channel:
                for member in qdata.red_channel.members:
                    await member.move_to(lobby)
                await qdata.red_channel.delete()
            if qdata.blue_channel:
                for member in qdata.blue_channel.members:
                    await member.move_to(lobby)
                await qdata.blue_channel.delete()
        else:
            logger.info(interaction)
            await interaction.followup.send("Score Submitted")
            logger.info("got here")
            gg = False

        logger.info("Blah")
        # Finding player ids
        red_ids = []
        blue_ids = []
        if qdata.game:
            for player in qdata.game.red:
                red_ids.append(player.id)
            for player in qdata.game.blue:
                blue_ids.append(player.id)

        url = f'https://secondrobotics.org/api/ranked/{qdata.api_short}/match/'
        json = {
            "red_alliance": red_ids,
            "blue_alliance": blue_ids,
            "red_score": red_score,
            "blue_score": blue_score
        }
        x = requests.post(url, json=json, headers=HEADER)
        logger.info(x.json())
        response = x.json()
        # Getting match Number

        embed = discord.Embed(
            color=0x34eb3d, title=f"**[{qdata.full_game_name}]** "
                                  f"Score submitted | 🟥 {qdata.red_series}-{qdata.blue_series}  🟦 |")
        embed.set_thumbnail(url=qdata.game_icon)
        red_out = "```diff\n"
        blue_out = "```diff\n"
        i = 0
        for player in response['red_player_elos']:
            red_out += f"{response['red_display_names'][i]} [{round(player['elo'], 2)}]\n" \
                       f"{'%+d' % (round(response['red_elo_changes'][i], 2))}\n"
            i += 1
        i = 0
        for player in response['blue_player_elos']:
            blue_out += f"{response['blue_display_names'][i]} [{round(player['elo'], 2)}]\n" \
                        f"{'%+d' % (round(response['blue_elo_changes'][i], 2))}\n"
            i += 1
        red_out += "```"
        blue_out += "```"

        embed.add_field(name=f'🟥 RED 🟥 *({red_score})*',
                        value=f"{red_out}",
                        inline=True)
        embed.add_field(name=f'🟦 BLUE 🟦 *({blue_score})*',
                        value=f"{blue_out}",
                        inline=True)

        class RejoinQueueView(discord.ui.View):
            def __init__(self, qdata: XrcGame, cog: Ranked):
                super().__init__()
                self.qdata = qdata
                self.cog = cog

            @discord.ui.button(label="Rejoin Queue", style=discord.ButtonStyle.blurple)
            async def rejoin_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
                await self.cog.queue_player(interaction, self.qdata.api_short)

        if gg:
            await interaction.channel.send(embed=embed, view=RejoinQueueView(qdata, self))
        else:
            await interaction.channel.send(embed=embed)

    async def random(self, interaction, game_type):
        logger.info("randomizing")
        qdata = create_game(game_type)

        if not qdata.game:
            await interaction.followup.send("No game found", ephemeral=True)
            return

        logger.info(f"players: {qdata.game.players}")
        logger.info(f"Team size {qdata.team_size}")
        red = random.sample(qdata.game.players, int(qdata.team_size))
        logger.info(red)
        for player in red:
            logger.info(player)
            qdata.game.add_to_red(player)

        blue = list(qdata.game.players)
        logger.info(blue)
        for player in blue:
            logger.info(player)
            qdata.game.add_to_blue(player)

        await self.display_teams(interaction, qdata)

    # @commands.command(description="Shows your current elo/ranking stats", aliases=["elocheck"])
    # async def checkelo(self, ctx):
    #     privs = {699094822132121662, 637411162203619350}
    #     wks = self.open_sheet("6-man Rankings + Elos", "Leaderboard")
    #     self.ranks = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)
    #     new_ranks = self.ranks[["Player", "#", "MMR", "Rank", "Wins", "Losses", "Ties"]]
    #     colors = {"Challenger": 0xc7ffff, "Grandmaster": 0xeb8686, "Master": 0xf985cb, "Diamond": 0xc6d2ff,
    #               "Platinum": 0x54eac1, "Gold": 0xebce75, "Silver": 0xd9d9d9, "Bronze": 0xb8a25e, "Iron": 0xffffff,
    #               "Stone": 0x000000}
    #
    #     text_id = f"#{ctx.author.id}"
    #     try:
    #         player = self.user_index.loc[text_id]["Name"]
    #     except:
    #         await ctx.channel.send("Unable to find your data!")
    #
    #     # sets all matches to True
    #     matches = self.elo_results.isin([player])
    #     # Find locations of all Trues
    #     outlist = [[i, matches.columns.tolist()[j]]
    #                for i, r in enumerate(matches.values)
    #                for j, c in enumerate(r)
    #                if c]
    #     # Get values of elos
    #     column_to_label = {1: "fElo1", 2: "fElo2", 3: "fElo3", 4: "fElo4", 5: "fElo5", 6: "fElo6"}
    #     elo_history = []
    #     for match in outlist:
    #         elo_history.append(self.elo_results.loc[match[0], column_to_label[match[1]]])
    #
    #     player_data = new_ranks.loc[new_ranks['Player'] == player]
    #     elo_history.reverse()
    #     plt.style.use('dark_background')
    #
    #     roles = set([y.id for y in ctx.message.author.roles])
    #     if roles.intersection(privs):
    #         plt.plot(elo_history, label=player, color='black')
    #         ax = plt.gca()
    #         ax.set_facecolor("white")
    #     else:
    #         plt.plot(elo_history, label=player, color='white')
    #     plt.title(f"Elo history of {player}")
    #     plt.legend()
    #     plt.ylabel('ELO')
    #     plt.xlabel('Match Number')
    #     plt.savefig("Elo.png")
    #     plt.close()
    #     file = discord.File('Elo.png')
    #
    #     embed = discord.Embed(title=f"#{player_data.iloc[0]['#']} - {player}",
    #                           color=colors[player_data.iloc[0]['Rank']],
    #                           url="https://docs.google.com/spreadsheets/d/1Oz7PRidqPPe_aC6ApHA4xo9XTpuTmgj6z9z2sy3U6ds/edit#gid=1261790407")
    #     embed.set_thumbnail(url=f"https://cdn.discordapp.com/avatars/{ctx.author.id}/{ctx.author.avatar}.png?size=1024")
    #     if 715286195612942356 in [y.id for y in ctx.message.author.roles]:
    #         embed.add_field(name="BETA TESTER", value=f"Thank you for your support!", inline=False)
    #     embed.add_field(name="Placement", value=f"#{player_data.iloc[0]['#']}/{len(new_ranks.index)}", inline=True)
    #     embed.add_field(name="Rank", value=f"{player_data.iloc[0]['Rank']}", inline=True)
    #     embed.add_field(name="MMR", value=f"{round(player_data.iloc[0]['MMR'], 1)}", inline=True)
    #     embed.add_field(name="Record",
    #                     value=f"{round(player_data.iloc[0]['Wins'])}-{round(player_data.iloc[0]['Losses'])}-{round(player_data.iloc[0]['Ties'])}",
    #                     inline=False)
    #     embed.add_field(name="Win Rate",
    #                     value=f"{round((player_data.iloc[0]['Wins'] / (player_data.iloc[0]['Wins'] + player_data.iloc[0]['Losses'])) * 100, 2)}%",
    #                     inline=True)
    #     embed.set_image(url="attachment://Elo.png")
    #     await ctx.channel.send(file=file, embed=embed)

    # @commands.command(description="Updates names")
    # async def namecheck(self, ctx):
    #
    #     wks = self.open_sheet("6-man Rankings + Elos", "ELO raw")
    #     self.elo_results = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)
    #
    #     wks = self.open_sheet("6-man Rankings + Elos", "User Index")
    #     self.user_index = gspread_dataframe.get_as_dataframe(wks)
    #     self.user_index.set_index("Id", inplace=True)
    #     self.names_to_ids = {}
    #     for index, row in self.user_index.iterrows():
    #         self.names_to_ids.update({row["Name"]: str(index)[1:]})
    #     await asyncio.sleep(.1)
    #     wks = self.open_sheet("6-man Rankings + Elos", "Leaderboard")
    #     ranks = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)
    #     new_ranks = ranks[["Player", "MMR", "Rank"]]
    #     for member in self.names_to_ids.values():
    #         try:
    #             user = ctx.message.guild.get_member(int(member))
    #             ranks_to_check = ["Challenger", "Grandmaster", "Master", "Diamond", "Platinum", "Gold", "Silver",
    #                               "Bronze", "Iron", "Stone"]
    #             for rank in ranks_to_check:
    #                 role2 = get(ctx.message.author.guild.roles, name=rank)
    #                 if role2 in user.roles:
    #                     await user.remove_roles(role2)
    #         except:
    #             pass
    #     for index, row in new_ranks.iterrows():
    #         await asyncio.sleep(.1)
    #         try:
    #             user = ctx.message.guild.get_member(int(self.names_to_ids[row['Player']]))
    #             role = get(ctx.message.author.guild.roles, name=row["Rank"])
    #             # logger.info(role)
    #             if role in user.roles:
    #                 pass
    #                 # logger.info(f"{user} already has correct role")
    #             else:
    #                 ranks_to_check = ["Challenger", "Grandmaster", "Master", "Diamond", "Platinum", "Gold", "Silver",
    #                                   "Bronze", "Iron", "Stone"]
    #                 for rank in ranks_to_check:
    #                     role2 = get(ctx.message.author.guild.roles, name=rank)
    #                     if role2 in user.roles:
    #                         await user.remove_roles(role2)
    #                 await user.add_roles(role)
    #                 # logger.info(f"{user} updated")
    #         except Exception as e:
    #             try:
    #                 user = ctx.message.guild.get_member(int(self.names_to_ids[row['Player']]))
    #                 ranks_to_check = ["Challenger", "Grandmaster", "Master", "Diamond", "Platinum", "Gold", "Silver",
    #                                   "Bronze", "Iron", "Stone"]
    #                 for rank in ranks_to_check:
    #                     role2 = get(ctx.message.author.guild.roles, name=rank)
    #                     if role2 in user.roles:
    #                         await user.remove_roles(role2)
    #             except:
    #                 logger.info(f"Passed over {row['Player']} - {e}")
    #     # logger.info(new_ranks)
    #     all_members = ctx.message.guild.members
    #     await ctx.channel.send("Names updated")

    async def display_teams(self, ctx, qdata):
        channel = ctx.channel
        category = get(ctx.guild.categories, id=824691912371470367)
        staff = get(ctx.guild.roles, id=699094822132121662)

        qdata.red_role = await ctx.guild.create_role(name=f"Red {qdata.full_game_name}",
                                                     colour=discord.Color(0xFF0000))
        qdata.blue_role = await ctx.guild.create_role(name=f"Blue {qdata.full_game_name}",
                                                      colour=discord.Color(0x0000FF))
        overwrites_red = {ctx.guild.default_role: discord.PermissionOverwrite(connect=False),
                          qdata.red_role: discord.PermissionOverwrite(connect=True),
                          staff: discord.PermissionOverwrite(connect=True)}
        overwrites_blue = {ctx.guild.default_role: discord.PermissionOverwrite(connect=False),
                           qdata.blue_role: discord.PermissionOverwrite(connect=True),
                           staff: discord.PermissionOverwrite(connect=True)}

        qdata.red_channel = await ctx.guild.create_voice_channel(name=f"🟥{qdata.full_game_name}🟥",
                                                                 category=category, overwrites=overwrites_red)
        qdata.blue_channel = await ctx.guild.create_voice_channel(name=f"🟦{qdata.full_game_name}🟦",
                                                                  category=category, overwrites=overwrites_blue)
        logger.info(qdata.blue_role)
        logger.info(qdata.red_role)

        for player in qdata.game.red:
            await player.add_roles(discord.utils.get(ctx.guild.roles, id=qdata.red_role.id))
            try:
                await player.move_to(qdata.red_channel)
            except Exception as e:
                logger.info(e)
                pass
        for player in qdata.game.blue:
            await player.add_roles(discord.utils.get(ctx.guild.roles, id=qdata.blue_role.id))
            try:
                await player.move_to(qdata.blue_channel)
            except Exception as e:
                logger.info(e)
                pass
        logger.info("Roles Created")

        description = f"Server started for you on port {qdata.server_port} with password {qdata.server_password}" if qdata.server_port else None

        logger.info(qdata.game.red)
        embed = discord.Embed(
            color=0x34dceb, title=f"Teams have been picked for __{qdata.full_game_name}__!", description=description)
        embed.set_thumbnail(url=qdata.game_icon)
        embed.add_field(name='🟥 RED 🟥',
                        value="{}".format(
                            "\n".join([player.mention for player in qdata.game.red])),
                        inline=True)
        embed.add_field(name='🟦 BLUE 🟦',
                        value="{}".format(
                            "\n".join([player.mention for player in qdata.game.blue])),
                        inline=True)

        await ctx.followup.send(embed=embed)

        msg = await channel.send(f"{qdata.red_role.mention} {qdata.blue_role.mention}")
        await msg.delete(delay=30)
        await self.update_ranked_display()

    # @commands.command(description="Submit Score (WIP)")
    # async def matchnum(self, ctx):
    #     wks = self.open_sheet("6-man Rankings + Elos", "To Add")
    #     df = gspread_dataframe.get_as_dataframe(wks)
    #     logger.info(df["Match Number"].iloc[0])

    @ app_commands.choices(game=games_choices)
    @ app_commands.command(name="clearmatch", description="Clears current running match")
    async def clearmatch(self, interaction: discord.Interaction, game: str):
        logger.info(f"{interaction.user.name} called /clearmatch")
        qdata = game_queues[game]

        if (isinstance(interaction.user, discord.Member) and
                699094822132121662 in [y.id for y in interaction.user.roles]):
            await self.do_clear_match(interaction.user.guild, qdata)
            await interaction.response.send_message("Cleared successfully!")
        else:
            await interaction.response.send_message("You don't have permission to do that!", ephemeral=True)

    async def do_clear_match(self, guild: discord.Guild, qdata: XrcGame):
        if qdata.server_port:
            stop_server_process(qdata.server_port)

        qdata.red_series = 2
        qdata.blue_series = 2

        await remove_roles(guild, qdata)

        # kick to lobby
        lobby = self.bot.get_channel(824692700364275743)
        if qdata.red_channel:
            for member in qdata.red_channel.members:
                await member.move_to(lobby)
            await qdata.red_channel.delete()
        if qdata.blue_channel:
            for member in qdata.blue_channel.members:
                await member.move_to(lobby)
            await qdata.blue_channel.delete()

    @app_commands.command(name="rules", description="Posts a link the the rules")
    async def rules(self, interaction: discord.Interaction):
        logger.info(f"{interaction.user.name} called /rules")
        await interaction.response.send_message("The rules can be found here: <#700411727430418464>")

    @tasks.loop(minutes=10)
    async def check_queue_joins(self):
        """every hour, check if any queue_joins are older than 2 hours
        if they are, remove them from the queue
        if they are not, do nothing"""
        for (queue, player), timestamp in queue_joins.copy().items():
            if (datetime.now() - timestamp).total_seconds() > 60 * 60 * 2:
                if player in queue:
                    queue.remove(player)
                    # send a message to the player
                    await player.send(
                        "You have been removed from a queue because you have been in the queue for more than 2 hours.")
                else:
                    queue_joins.pop((queue, player))
        await self.update_ranked_display()

    @check_queue_joins.before_loop
    async def before_check_queue_joins(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=10)
    async def check_empty_servers(self):
        """every 10 minutes, check if any servers are empty
        if it is empty, add it to the list of empty servers
        if it was empty last time we checked, stop the server
        if it is not empty, remove it from the list of empty servers"""

        # remove servers that have closed
        for server in empty_servers.copy():
            if server not in servers_active:
                empty_servers.remove(server)

        for server in servers_active:
            if server not in empty_servers:
                if not server_has_players(server):
                    empty_servers.append(server)
                    warn_server_inactivity(server)

            else:
                if not server_has_players(server):
                    shutdown_server_inactivity(server)
                empty_servers.remove(server)

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
        end += [None, end, end]  # sentinel node for doubly linked list
        self.map = {}  # key --> [key, prev, next]
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
            key, prev, next = self.map.pop(key)
            prev[2] = next
            next[1] = prev

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


# dict of tuple of queue and player to timestamp when joined queue
queue_joins = {}  # type: dict[tuple[PlayerQueue, discord.Member], datetime]
# list of servers (port numbers) that were empty last time we checked
empty_servers: list[int] = []


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

cog = None  # type: Ranked | None
guild = None  # type: discord.Guild | None


async def setup(bot: commands.Bot) -> None:
    cog = Ranked(bot)
    guild = bot.get_guild(GUILD_ID)
    assert guild is not None

    await bot.add_cog(
        cog,
        guilds=[guild]
    )


def shutdown_server_inactivity(server: int):
    # if server is in a ranked queue, clear the match
    for queue in game_queues.values():
        if queue.server_port == server:
            if cog and guild:
                task = asyncio.create_task(cog.do_clear_match(guild, queue))
                task.add_done_callback(lambda _: logger.info(
                    f"Match cleared for server {server} due to inactivity"))

            if queue.game:
                for player in queue.game.players:
                    # send a message to the players
                    asyncio.create_task(player.send(
                        "Your ranked match has been cancelled due to inactivity."))

            # TODO: punish players that dodged
            return

    # otherwise, just stop the process
    stop_server_process(server)


def server_has_players(server: int) -> bool:
    """
    Check if the server has players on it
    For casual matches, this is just if at least one player is present
    For ranked matches, this is if the match is full
    """
    needed_players = 1
    for queue in game_queues.values():
        if queue.server_port == server:
            needed_players = queue.game_size
            break

    # TODO: read players from xrc server stdout

    return True


def warn_server_inactivity(server: int):
    # if server is in a ranked queue, send a message to the players
    for queue in game_queues.values():
        if queue.server_port == server:
            if queue.game:
                for player in queue.game.players:
                    # send a message to the players
                    asyncio.create_task(player.send(
                        "Your ranked match has been inactive - if all players are not present within 10 minutes, the match will be cancelled."))
                    pass
            return
