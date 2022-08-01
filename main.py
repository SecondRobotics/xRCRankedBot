from discord import app_commands
import collections
from collections.abc import MutableSet
import random
from queue import Queue
from discord.utils import get
from oauth2client.service_account import ServiceAccountCredentials
import gspread
import gspread_dataframe
import pandas as pd
import discord
from discord.ext import commands
import asyncio
import matplotlib.pyplot as plt
import math
import os
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.all()
intents.message_content = True

team_size = 6
team_size_alt = 4
approved_channels = [824691989366046750, 712297302857089025,
                     650967104933330947, 754569102873460776, 754569222260129832]


class Game:
    def __init__(self, players):
        self.players = set(players)
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


class OrderedSet(collections.abc.MutableSet):
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


class PlayerQueue(Queue):
    def _init(self, maxsize):
        self.queue = OrderedSet()

    def _put(self, item):
        self.queue.add(item)

    def _get(self):
        return self.queue.pop()

    def remove(self, value):
        self.queue.remove(value)

    def __contains__(self, item):
        with self.mutex:
            return item in self.queue


queuelist = []
game = None
busy = False
red_series = 2
blue_series = 2
red_captain = None
blue_captain = None
last_match_msg = None
clearmatch_message = None
autoq = []
players_current_elo = {}


class RankedBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=discord.Intents.all(),
            application_id=825618483957071873)

    async def setup_hook(self):
        await self.load_extension(f"cogs.ranked")
        await bot.tree.sync(guild=discord.Object(id=637407041048281098))

    async def on_ready(self):
        print("alive")
          # Required to update all slash commands
        await bot.change_presence(activity=discord.Game(name=str("New phone who dis")))


bot = RankedBot()
#tree = app_commands.CommandTree(bot)


@app_commands.command()
async def ping(interaction: discord.Interaction):
    """Pingggg"""
    await interaction.response.send_message('Pong! {0} :ping_pong: '.format(round(bot.latency * 1000, 4)),
                                            ephemeral=False)


# @tree.command()
# async def queue(interaction: discord.Interaction):
#     """Enter's player into queue for upcoming matches"""
#
#     if interaction.channel.id in approved_channels:
#         print(queuelist)
#         print(busy)
#         player = interaction.user
#         channel = interaction.channel
#         roles = [y.id for y in interaction.user.roles]
#         ranked_roles = [824711734069297152, 824711824011427841]
#         # Returns false if not in a game currently. Looks for duplicates between roles and ranked_roles
#         queue_check = bool(set(roles).intersection(ranked_roles))
#         if queue_check:
#             await interaction.response.send_message("You are already in a game! "
#                                                     "Please complete your series before queuing again.", ephemeral=True)
#             return
#         if player in queuelist:
#             await interaction.followup.send("You are already in queue.", ephemeral=True)
#         queuelist.append(player)
#         await interaction.response.send_message(f"**{player.display_name}** added to the queue.", ephemeral=False)
#     else:
#         await interaction.response.send_message("You can't queue in this channel.", ephemeral=True)


    #     if player in qdata['queue']:
    #         await channel.send("{} is already in queue.".format(player.display_name))
    #         return
    #     if qdata['busy'] and player in qdata['game']:
    #         await channel.send("{} is already in a game.".format(player.display_name))
    #         return
    #
    #     qdata['queue'].put(player)
    #
    #     await channel.send(
    #         "{} added to queue. ({:d}/{:d})".format(player.display_name, qdata['queue'].qsize(),
    #                                                 qdata['team_size']))
    #     if self.queue_full(ctx):
    #         if qdata['red_series'] == 2 or qdata['blue_series'] == 2:
    #             await channel.send("Queue is now full! Type {prefix}startmatch".format(
    #                 prefix=self.bot.command_prefix))
    #         else:
    #             await channel.send("Queue is now full! You can start as soon as the current match concludes.")
    #


async def remove_roles(ctx):
    # Remove any current roles

    if ctx.channel.id == 824691989366046750:  # 6 FRC
        red_check = get(ctx.message.author.guild.roles, name="Ranked Red")
        blue_check = get(ctx.message.author.guild.roles, name="Ranked Blue")
        for player in red_check.members:
            to_change = get(ctx.message.author.guild.roles, name="Ranked Red")
            await player.remove_roles(to_change)
        for player in blue_check.members:
            to_change = get(ctx.message.author.guild.roles, name="Ranked Blue")
            await player.remove_roles(to_change)
    elif ctx.channel.id == 712297302857089025 or ctx.channel.id == 754569102873460776 or ctx.channel.id == 754569222260129832:  # VEX
        red_check = get(ctx.message.author.guild.roles, name="4 Mans Red")
        blue_check = get(ctx.message.author.guild.roles, name="4 Mans Blue")
        for player in red_check.members:
            to_change = get(ctx.message.author.guild.roles, name="4 Mans Red")
            await player.remove_roles(to_change)
        for player in blue_check.members:
            to_change = get(ctx.message.author.guild.roles, name="4 Mans Blue")
            await player.remove_roles(to_change)





# async def setup(bot : commands.Bot):
#     await bot.add_cog(
#         TeamMaker(bot), guilds=[discord.Object(id=637407041048281098)])


bot.run(os.getenv("DISCORD_BOT_TOKEN"))
