from discord import app_commands
import collections
import operator
import random
import time
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
import matplotlib as mpl
import math
from threading import Thread
from collections.abc import MutableSet
import sys

team_size = 6
team_size_alt = 4
approved_channels = [824691989366046750, 712297302857089025, 650967104933330947, 754569102873460776, 754569222260129832]

listener = commands.Cog.listener


async def remove_roles(ctx):
    # Remove any current roles

    if ctx.channel.id == 824691989366046750:  # 6 FRC
        red_check = get(ctx.user.guild.roles, name="Ranked Red")
        blue_check = get(ctx.user.guild.roles, name="Ranked Blue")
        for player in red_check.members:
            to_change = get(ctx.user.guild.roles, name="Ranked Red")
            await player.remove_roles(to_change)
        for player in blue_check.members:
            to_change = get(ctx.user.guild.roles, name="Ranked Blue")
            await player.remove_roles(to_change)


class Ranked(commands.Cog):
    def __init__(self, bot):
        self.n = 256
        self.k = 16
        self.r = 0.002
        self.b = 10
        self.c = 100
        self.d = 1.1
        self.a = (((self.b - 1) / (self.d - 1)) ** (1 / self.c))
        self.bot = bot
        self.queue = PlayerQueue()
        self.game = None
        self.busy = False
        self.red_series = 2
        self.blue_series = 2
        self.red_captain = None
        self.blue_captain = None
        self.last_match_msg = None
        self.clearmatch_message = None
        self.autoq = []
        self.players_current_elo = {}

        self.queue2 = PlayerQueue()
        self.game2 = None
        self.busy2 = False
        self.red_series2 = 2
        self.blue_series2 = 2
        self.red_captain2 = None
        self.blue_captain2 = None
        self.last_match_msg2 = None
        self.clearmatch_message2 = None
        self.past_winner2 = ""

        self.queue3 = PlayerQueue()
        self.game3 = None
        self.busy3 = False
        self.red_series3 = 2
        self.blue_series3 = 2
        self.red_captain3 = None
        self.blue_captain3 = None
        self.last_match_msg3 = None
        self.clearmatch_message3 = None
        self.past_winner3 = ""

        self.queue4 = PlayerQueue()
        self.game4 = None
        self.busy4 = False
        self.red_series4 = 2
        self.blue_series4 = 2
        self.red_captain4 = None
        self.blue_captain4 = None
        self.last_match_msg4 = None
        self.clearmatch_message4 = None
        self.past_winner4 = ""

        self.rejected_matches = []
        wks = self.open_sheet("6-man Rankings + Elos", "User Index")
        self.user_index = gspread_dataframe.get_as_dataframe(wks)
        self.user_index.set_index("Id", inplace=True)
        self.past_winner = ""

        wks = self.open_sheet("6-man Rankings + Elos", "User Index")
        self.user_index = gspread_dataframe.get_as_dataframe(wks)
        self.user_index.set_index("Id", inplace=True)
        self.names_to_ids = {}
        self.ids_to_names = {}
        for index, row in self.user_index.iterrows():
            self.names_to_ids.update({row["Name"]: str(index)[1:]})

        wks = self.open_sheet("6-man Rankings + Elos", "Leaderboard")
        self.ranks = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)

        wks = self.open_sheet("6-man Rankings + Elos", "ELO raw")
        self.elo_results = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)

        wks = self.open_sheet("6-man Rankings + Elos", "VEX ELO Raw")
        self.elo_results2 = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)

    def set_queue(self, ctx, qdata):
        if ctx.channel.id == 824691989366046750:  # 6 FRC
            self.queue = qdata['queue']
            self.game = qdata['game']
            self.busy = qdata['busy']
            self.red_series = qdata['red_series']
            self.blue_series = qdata['blue_series']
            self.red_captain = qdata['red_captain']
            self.blue_captain = qdata['blue_captain']
            self.last_match_msg = qdata['last_match_msg']
            self.past_winner = qdata['past_winner']
        elif ctx.channel.id == 712297302857089025:  # VEX
            self.queue2 = qdata['queue']
            self.game2 = qdata['game']
            self.busy2 = qdata['busy']
            self.red_series2 = qdata['red_series']
            self.blue_series2 = qdata['blue_series']
            self.red_captain2 = qdata['red_captain']
            self.blue_captain2 = qdata['blue_captain']
            self.last_match_msg2 = qdata['last_match_msg']
            self.past_winner2 = qdata['past_winner']
        elif ctx.channel.id == 754569222260129832:  # FTC
            self.queue3 = qdata['queue']
            self.game3 = qdata['game']
            self.busy3 = qdata['busy']
            self.red_series3 = qdata['red_series']
            self.blue_series3 = qdata['blue_series']
            self.red_captain3 = qdata['red_captain']
            self.blue_captain3 = qdata['blue_captain']
            self.last_match_msg3 = qdata['last_match_msg']
            self.past_winner3 = qdata['past_winner']
        elif ctx.channel.id == 754569102873460776:  # FRC4
            self.queue4 = qdata['queue']
            self.game4 = qdata['game']
            self.busy4 = qdata['busy']
            self.red_series4 = qdata['red_series']
            self.blue_series4 = qdata['blue_series']
            self.red_captain4 = qdata['red_captain']
            self.blue_captain4 = qdata['blue_captain']
            self.last_match_msg4 = qdata['last_match_msg']
            self.past_winner4 = qdata['past_winner']

    def get_queue(self, ctx):
        if ctx.channel.id == 824691989366046750:  # 6 FRC
            queue = self.queue
            game = self.game
            busy = self.busy
            red_series = self.red_series
            blue_series = self.blue_series
            red_captain = self.red_captain
            blue_captain = self.blue_captain
            last_match_msg = self.last_match_msg
            past_winner = self.past_winner
            size = team_size
        elif ctx.channel.id == 712297302857089025:  # VEX
            queue = self.queue2
            game = self.game2
            busy = self.busy2
            red_series = self.red_series2
            blue_series = self.blue_series2
            red_captain = self.red_captain2
            blue_captain = self.blue_captain2
            last_match_msg = self.last_match_msg2
            past_winner = self.past_winner2
            size = team_size_alt
        else:
            return None
        return {"queue": queue, "game": game, "busy": busy, "red_series": red_series, "blue_series": blue_series,
                "red_captain": red_captain, "blue_captain": blue_captain, "last_match_msg": last_match_msg,
                "past_winner": past_winner,
                "team_size": size}

    @commands.command(pass_context=True)
    async def autoq(self, ctx, command=None, command_ctx=None):
        if command is not None:
            if 699094822132121662 in [y.id for y in ctx.message.author.roles]:
                print("trueee")
                if command.lower() == "kick":
                    if command_ctx is not None:
                        self.autoq.remove(int(command_ctx))
                        await ctx.channel.send(f"Removed <@{command_ctx}> to the autoq list")
                        print(command_ctx)
                        return
        if ctx.channel.id != 824691989366046750:
            return
        privs = {637411162203619350, 824727390873452634}
        roles = set([y.id for y in ctx.message.author.roles])
        if roles.intersection(privs):
            if ctx.author.id in self.autoq:
                await self.leave(ctx)
                self.autoq.remove(ctx.author.id)
                await ctx.channel.send(f"Removed {ctx.author.mention} from the autoq list")
            else:
                await self.q(ctx)
                self.autoq.append(ctx.author.id)
                await ctx.channel.send(f"Added {ctx.author.mention} to the autoq list")
        else:
            await ctx.channel.send(f"Autoqing is only available to patreons. To become a patreon check out this link! https://www.patreon.com/BrennanB ")
        print(self.autoq)

    async def queue_auto(self, ctx):
        qdata = self.get_queue(ctx)
        print(qdata)
        for id in self.autoq:
            member = ctx.guild.get_member(id)
            qdata['queue'].put(member)
            await ctx.channel.send(
                "{} was autoqed. ({:d}/{:d})".format(member.display_name, qdata['queue'].qsize(),
                                                        qdata['team_size']))

    @app_commands.command(description="Force queue players")
    async def queueall(self, interaction: discord.Interaction,
                       member1: discord.Member = None,
                       member2: discord.Member = None,
                       member3: discord.Member = None,
                       member4: discord.Member = None,
                       member5: discord.Member = None,
                       member6: discord.Member = None):
        qdata = self.get_queue(interaction)
        print(qdata)
        members = [member1, member2, member3, member4, member5, member6]
        added_players = ""
        if interaction.user.id == 118000175816900615:
            for member in members:
                qdata['queue'].put(member)
                added_players += f"{member.display_name}\n"
            await interaction.response.send_message(f"Successfully added\n{added_players} to the queue.", ephemeral=True)
        else:
            await interaction.response.send_message("Nerd.", ephemeral=True)

    # @commands.command(pass_context=True)
    # async def seriestest(self, ctx):
    #     await ctx.channel.send(f"{self.red_series} {self.blue_series}")

    @app_commands.command(name="queue", description="Add yourself to the queue")
    async def q(self, interaction: discord.Interaction):
        """Enter's player into queue for upcoming matches"""
        qdata = self.get_queue(interaction)
        print(qdata)

        if interaction.channel.id in approved_channels:
            player = interaction.user
            channel = interaction.channel
            if channel.id == 824691989366046750:  # FRC
                print(interaction.user)
                roles = [y.id for y in interaction.user.roles]
                ranked_roles = [824711734069297152, 824711824011427841]
                # Returns false if not in a game currently. Looks for duplicates between roles and ranked_roles
                queue_check = bool(set(roles).intersection(ranked_roles))
                if queue_check:
                    await channel.send("You are already playing in a game!")
                    return
            else:
                await interaction.response.send_message("You can't queue in this channel.", ephemeral=True)
            if player in qdata['queue']:
                await interaction.response.send("You are already in queue.", ephemeral=True)
                return
            if qdata['busy'] and player in qdata['game']:
                await interaction.response.send_message("You are already in a game.", ephemeral=True)
                return

            qdata['queue'].put(player)

            await interaction.response.send_message(
                "**{}** added to queue. ({:d}/{:d})".format(player.display_name, qdata['queue'].qsize(), qdata['team_size']))
            if self.queue_full(interaction):
                if qdata['red_series'] == 2 or qdata['blue_series']== 2:
                    await interaction.response.send_message("Queue is now full! Type {prefix}startmatch".format(
                        prefix=self.bot.command_prefix))
                else:
                    await interaction.response.send_message("Queue is now full! You can start as soon as the current match concludes.")
    #
    @app_commands.command()
    async def queuestatus(self, interaction: discord.Interaction):
        """View who is currently in the queue"""
        qdata = self.get_queue(interaction)
        channel = interaction.channel
        try:
            for _ in range(0, 2): #loop to not reverse order
                players = [qdata['queue'].get() for _ in range(qdata['queue'].qsize())]
                for player in players:
                    qdata['queue'].put(player)
            embed = discord.Embed(color=0xcda03f, title="Signed up players")
            embed.add_field(name='Players',
                            value="{}".format("\n".join([player.mention for player in players])),
                            inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except:
            await interaction.response.send_message("Nobody is in queue!", ephemeral=True)

    @app_commands.command(name="leave", description="Remove yourself from the queue")
    async def leave(self, interaction: discord.Interaction):
        qdata = self.get_queue(interaction)
        if interaction.channel.id in approved_channels:
            player = interaction.user
            channel = interaction.channel

            if player in qdata['queue']:
                qdata['queue'].remove(player)
                await interaction.response.send_message(
                    "**{}** removed from queue. ({:d}/{:d})".format(player.display_name, qdata['queue'].qsize(), qdata['team_size']))
            else:
                await interaction.response.send_message("You aren't in queue.", ephemeral=True)
        self.set_queue(interaction, qdata)

    @app_commands.command(description="Remove someone else from the queue")
    @app_commands.checks.has_any_role("Event Staff")
    async def kick(self, interaction: discord.Interaction, player: discord.Member):
        qdata = self.get_queue(interaction)
        if interaction.channel.id in approved_channels:
            if player in qdata['queue']:
                qdata['queue'].remove(player)
                await interaction.response.send_message(
                    "{} removed from queue. ({:d}/{:d})".format(player.display_name, qdata['queue'].qsize(), qdata['team_size']))
            else:
                await interaction.response.send_message("{} is not in queue.".format(player.display_name), ephemeral=True)

    def queue_full(self, ctx):
        if ctx.channel.id == 824691989366046750: # 6 FRC
            return self.queue.qsize() >= team_size
        elif ctx.channel.id == 712297302857089025: #VEX
            return self.queue2.qsize() >= team_size_alt
        elif ctx.channel.id == 754569222260129832: #FTC
            return self.queue3.qsize() >= team_size_alt
        elif ctx.channel.id == 754569102873460776: #FRC 4
            return self.queue4.qsize() >= team_size_alt
        else:
            return False

    # def check_vote_command(self, message):
    #     if not message.content.startswith("{prefix}vote".format(prefix=self.bot.command_prefix)):
    #         return False
    #     if not len(message.mentions) == 1:
    #         return False
    #     return True

    # @commands.command(description="Start a game by voting for captains")
    # async def voting(self, ctx):
    #     channel = ctx.channel
    #     if not self.queue_full():
    #         await channel.send("Queue is not full.")
    #         return
    #     if self.busy:
    #         await channel.send("Bot is busy. Please wait until picking is done.")
    #         return
    #     self.busy = True
    #     self.create_game()
    #
    #     await channel.send(
    #         "Captain voting initiated. Use {prefix}vote [user] to vote for a captain (cannot be yourself).".format(
    #             prefix=self.bot.command_prefix))
    #     await channel.send("Available: {}".format(", ".join([player.display_name for player in self.game.players])))
    #
    #     votes = {}
    #     timeout = 90
    #     end_time = time.time() + timeout
    #     while len(votes) < team_size and time.time() < end_time:
    #         msg = await self.bot.wait_for('message', timeout=1, check=self.check_vote_command)
    #         if not msg:
    #             continue
    #         if msg.author not in self.game.players:
    #             return
    #
    #         vote = msg.mentions[0]
    #         if vote == msg.author:
    #             await channel.send("Cannot vote for yourself.")
    #         elif vote in self.game.players:
    #             votes[msg.author] = msg.mentions[0]
    #             await channel.send("Vote added for {}.".format(vote.display_name))
    #         else:
    #             await channel.send("{} not available to pick.".format(vote.display_name))
    #     if len(votes) < team_size:
    #         await channel.send("Timed out.")
    #         msg = ""
    #         for player in self.game.players:
    #             if player not in votes:
    #                 vote = player
    #                 while vote == player:
    #                     vote = random.choice(tuple(self.game.players))
    #                 votes[player] = vote
    #                 msg += "Random vote added for {} from {}.\n".format(vote.display_name, player.display_name)
    #         await channel.send(msg)
    #
    #     vote_nums = {}
    #     for vote in votes.values():
    #         vote_nums[vote] = vote_nums.get(vote, 0) + 1
    #     sorted_vote_nums = sorted(vote_nums.items(), key=operator.itemgetter(1), reverse=True)
    #     top_votes = [key for key, value in sorted_vote_nums if value == sorted_vote_nums[0][1]]
    #     if len(top_votes) < 2:
    #         self.game.captains = top_votes
    #         secondary_votes = [key for key, value in sorted_vote_nums if value == sorted_vote_nums[1][1]]
    #         if len(secondary_votes) > 1:
    #             await channel.send("{:d}-way tie for 2nd captain. Shuffling picks...".format(len(secondary_votes)))
    #             random.shuffle(secondary_votes)
    #         self.game.captains.append(secondary_votes[0])
    #     else:
    #         if len(top_votes) > 2:
    #             await channel.send("{:d}-way tie for captains. Shuffling picks...".format(len(top_votes)))
    #         random.shuffle(top_votes)
    #         self.game.captains = top_votes[:2]
    #
    #     await self.do_picks(ctx)
    #
    #     self.busy = False

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

    @app_commands.command(description="Number of matches played")
    async def numplayed(self, interaction: discord.Interaction, user: str):
        print(self.elo_results)
        await interaction.response.send_message(
            len(self.elo_results[self.elo_results[1] == user]) +
            len(self.elo_results[self.elo_results[2] == user]) +
            len(self.elo_results[self.elo_results[3] == user]) +
            len(self.elo_results[self.elo_results[4] == user]) +
            len(self.elo_results[self.elo_results[5] == user]) +
            len(self.elo_results[self.elo_results[6] == user]))

    @app_commands.command(description="Start a game")
    async def startmatch(self, interaction: discord.Interaction):
        qdata = self.get_queue(interaction)
        print(qdata)
        if not self.queue_full(interaction):
            await interaction.response.send_message("Queue is not full.", ephemeral=True)
            return
        if qdata['red_series'] == 2 or qdata['blue_series'] == 2:
            qdata['red_series'] = 0
            qdata['blue_series'] = 0
            qdata['past_winner'] = ""
            self.set_queue(interaction, qdata)
            pass
        else:
            await interaction.response.send_message("Current match incomplete.", ephemeral=True)
            return
        if interaction.channel.id == 712297302857089025 or \
                interaction.channel.id == 754569222260129832 or \
                interaction.channel.id == 754569102873460776:
            return await self.random(interaction.channel.id)
        chooser = random.randint(1, 10)
        if chooser < 0:  # 6
            print("Captains")
            await self.captains(interaction)
        else:
            print("Randoms")
            await self.random(interaction)

    async def captains(self, ctx):
        qdata = self.get_queue(ctx)
        channel = ctx.channel
        if qdata['busy']:
            await channel.send("Bot is busy. Please wait until picking is done.")
            return
        qdata = self.create_game(ctx)

        self.set_queue(ctx, qdata)
        await self.do_picks(ctx)

    async def do_picks(self, ctx):
        qdata = self.get_queue(ctx)
        channel = ctx.channel
        embed = discord.Embed(color=0xfa0000, title="Red Captain's pick!")

        await channel.send("Captains: {} and {}".format(*[captain.mention for captain in qdata['game'].captains]))
        qdata['red_captain'] = qdata['game'].captains[0]
        qdata['game'].add_to_red(qdata['red_captain'])
        qdata['blue_captain'] = qdata['game'].captains[1]
        qdata['game'].add_to_blue(qdata['blue_captain'])

        embed.add_field(name='🟥 RED 🟥',
                        value="{}".format("\n".join([player.mention for player in qdata['game'].red])),
                        inline=False)
        embed.add_field(name='🟦 BLUE 🟦',
                        value="{}".format("\n".join([player.mention for player in qdata['game'].blue])),
                        inline=False)
        embed.add_field(name='Picking Process...',
                        value="{mention} Use {prefix}pick [user] to pick 1 player.".format(
                            mention=qdata['red_captain'].mention,
                            prefix=self.bot.command_prefix),
                        inline=False)
        embed.add_field(name='Available players:',
                        value="{}".format("\n".join([player.mention for player in qdata['game'].players])),
                        inline=False)
        self.set_queue(ctx, qdata)
        # red Pick
        await channel.send(embed=embed)
        red_pick = None
        while not red_pick:
            red_pick = await self.pick_red(ctx)
        qdata['game'].add_to_red(red_pick)

        # Blue Picks
        embed = discord.Embed(color=0x00affa, title="Blue Alliance Captain's Picks!")
        embed.add_field(name='🟥 RED 🟥',
                        value="{}".format("\n".join([player.mention for player in qdata['game'].red])),
                        inline=False)
        embed.add_field(name='🟦 BLUE 🟦',
                        value="{}".format("\n".join([player.mention for player in qdata['game'].blue])),
                        inline=False)
        embed.add_field(name='Picking Process...',
                        value="{mention} Use {prefix}pick [user1] [user2] to pick 2 players.".format(
                            mention=qdata['blue_captain'].mention,
                            prefix=self.bot.command_prefix),
                        inline=False)
        embed.add_field(name='Available players:',
                        value="{}".format("\n".join([player.mention for player in qdata['game'].players])),
                        inline=False)
        await channel.send(embed=embed)
        blue_picks = None
        self.set_queue(ctx, qdata)
        while not blue_picks:
            blue_picks = await self.pick_blue(ctx)
        for blue_pick in blue_picks:
            qdata['game'].add_to_blue(blue_pick)

        # red Player
        last_player = next(iter(qdata['game'].players))
        qdata['game'].add_to_red(last_player)
        await channel.send("{} added to 🟥 RED 🟥 team.".format(last_player.mention))
        self.set_queue(ctx, qdata)
        await self.display_teams(ctx)

    async def pick_red(self, ctx):
        qdata = self.get_queue(ctx)
        channel = ctx.channel
        try:
            msg = await self.bot.wait_for('message', timeout=45, check=self.check_red_first_pick_command)
            if msg:
                pick = msg.mentions[0]
                if pick not in qdata['game'].players:
                    await channel.send("{} not available to pick.".format(pick.display_name))
                    return None
                await channel.send("Picked {} for 🟥 RED 🟥 team.".format(pick.mention))
        except asyncio.TimeoutError:
            pick = random.choice(tuple(qdata['game'].players))
            await channel.send("Timed out. Randomly picked {} for 🟥 RED 🟥 team.".format(pick.mention))
        return pick

    async def pick_blue(self, ctx):
        qdata = self.get_queue(ctx)
        channel = ctx.channel
        try:
            msg = await self.bot.wait_for('message', timeout=45, check=self.check_blue_picks_command)
            print(msg)

            if msg:
                picks = msg.mentions
                for pick in picks:
                    if pick not in qdata['game'].players:
                        await channel.send("{} not available to pick.".format(pick.display_name))
                        return None
                await channel.send("Picked {} and {} for 🔷 BLUE 🔷 team.".format(*[pick.mention for pick in picks]))
                return picks
        except asyncio.TimeoutError:
            picks = random.sample(qdata['game'].players, 2)
            await channel.send(
                "Timed out. Randomly picked {} and {} for 🔷 BLUE 🔷 team.".format(*[pick.mention for pick in picks]))
            return picks

    # @commands.command(description="pingtest")
    # async def pingtest(self, ctx):
    #     red_check = get(ctx.message.author.guild.roles, name="6 Mans Red")
    #     blue_check = get(ctx.message.author.guild.roles, name="6 Mans Blue")
    #     await ctx.channel.send(f"{red_check.mention} {blue_check.mention}")

    def open_sheet(self, sheet_name, tab_name):
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        credentials = ServiceAccountCredentials.from_json_keyfile_name('fantasy-first-260710-7fa1a0ed0b21.json', scope)
        gc = gspread.authorize(credentials)
        stuff = gc.open(sheet_name)
        wks = stuff.worksheet(tab_name)
        return wks

    @commands.command(description="Submit Score")
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def submit(self, ctx, red_score, blue_score, edit=None):

        if ctx.channel.id == 824691989366046750:  # FRC
            headers = [1, 2, 3, 4, 5, 6, 'Match', 'rScore', 'bScore'
                , 'iElo1', 'iElo2', 'iElo3', 'iElo4', 'iElo5', 'iElo6',
                       'rElo', 'bElo', 'rOdds', 'bOdds',
                       'fElo1', 'fElo2', 'fElo3', 'fElo4', 'fElo5', 'fElo6',
                       'status1', 'status2', 'status3', 'status4', 'status5', 'status6']
        elif ctx.channel.id == 712297302857089025 or ctx.channel.id == 754569222260129832 or ctx.channel.id == 754569222260129832:  # VEX
            headers = [1, 2, 3, 4, 'Match', 'rScore', 'bScore'
                , 'iElo1', 'iElo2', 'iElo3', 'iElo4',
                       'rElo', 'bElo', 'rOdds', 'bOdds',
                       'fElo1', 'fElo2', 'fElo3', 'fElo4',
                       'status1', 'status2', 'status3', 'status4']

        try:
            red_check = int(red_score)
        except:
            await ctx.channel.send(f"{red_score} is not a number.")
            return
        try:
            blue_check = int(blue_score)
        except:
            await ctx.channel.send(f"{blue_score} is not a number.")
            return
        if ctx.channel.id == 824691989366046750:  # FRC
            if 699094822132121662 in [y.id for y in ctx.message.author.roles] or \
                    824711734069297152 in [y.id for y in ctx.message.author.roles] or \
                    824711824011427841 in [y.id for y in ctx.message.author.roles]:
                pass
            else:
                await ctx.channel.send("You are ineligible to submit!")
                return
        elif ctx.channel.id == 699094822132121662 or ctx.channel.id == 824711824011427841 or ctx.channel.id == 824711734069297152:  # VEX
            print("Vex Verification")
            if 693160987125350466 in [y.id for y in ctx.message.author.roles] or \
                    824711824011427841 in [y.id for y in ctx.message.author.roles] or \
                    824711734069297152 in [y.id for y in ctx.message.author.roles]:
                pass
            else:
                await ctx.channel.send("You are ineligible to submit!")
                return
        if edit is None:
            if ctx.channel.id == 824691989366046750:  # FRC
                if self.red_series == 2 or self.blue_series == 2:
                    await ctx.channel.send("Series is complete already!")
                    return
            elif ctx.channel.id == 712297302857089025:  # VEX
                if self.red_series2 == 2 or self.blue_series2 == 2:
                    await ctx.channel.send("Series is complete already!")
                    return

        if ctx.channel.id == 824691989366046750:  # FRC
            current_red = self.red_series
            current_blue = self.blue_series
        elif ctx.channel.id == 712297302857089025:  # VEX
            current_red = self.red_series2
            current_blue = self.blue_series2
        elif ctx.channel.id == 754569222260129832:  # FTC
            current_red = self.red_series3
            current_blue = self.blue_series3
        elif ctx.channel.id == 754569102873460776:  # FRC 4
            current_red = self.red_series4
            current_blue = self.blue_series4
        else:
            return
        print("Checking ")
        # Red wins
        if int(red_score) > int(blue_score):
            if edit is None:
                current_red += 1
            elif edit.lower() == "edit":
                if self.past_winner == "Blue":
                    current_red += 1
                    current_blue -= 1
            else:
                current_red += 1
            self.past_winner = "Red"

        # Blue wins
        elif int(red_score) < int(blue_score):
            if edit is None:
                current_blue += 1
            elif edit.lower() == "edit":
                if self.past_winner == "Red":
                    current_blue += 1
                    current_red -= 1
            else:
                current_blue += 1
            self.past_winner = "Blue"
        red_log = current_red
        blue_log = current_blue
        print(f"Red {current_red}")
        print(f"Blue {current_blue}")
        if current_red == 2:
            await self.queue_auto(ctx)
            await ctx.channel.send("🟥 Red Wins! 🟥")
            await remove_roles(ctx)
            curMembers = []
            channel = self.bot.get_channel(824692157142269963)
            lobby = self.bot.get_channel(824692700364275743)
            for member in channel.members:
                await member.move_to(lobby)
                curMembers.append(member)
            channel = self.bot.get_channel(824692212528840724)
            for member in channel.members:
                await member.move_to(lobby)
                curMembers.append(member)
            print(curMembers)

        if current_blue == 2:
            await self.queue_auto(ctx)
            await ctx.channel.send("🟦 Blue Wins! 🟦")
            await remove_roles(ctx)
            curMembers = []
            channel = self.bot.get_channel(824692157142269963)
            lobby = self.bot.get_channel(824692700364275743)
            for member in channel.members:
                await member.move_to(lobby)
                curMembers.append(member)
            channel = self.bot.get_channel(824692212528840724)
            for member in channel.members:
                await member.move_to(lobby)
                curMembers.append(member)
            print(curMembers)
        if ctx.channel.id == 824691989366046750:  # FRC
            self.red_series = current_red
            self.blue_series = current_blue
        elif ctx.channel.id == 712297302857089025:  # VEX
            self.red_series2 = current_red
            self.blue_series2 = current_blue
        elif ctx.channel.id == 754569222260129832:  # ftc
            self.red_series3 = current_red
            self.blue_series3 = current_blue
        elif ctx.channel.id == 754569102873460776:  # frc 4
            self.red_series3 = current_red
            self.blue_series3 = current_blue
        else:
            return
        print("Blah")
        qdata = self.get_queue(ctx)
        # Finding player ids
        red_players = []
        for player in qdata['game'].red:
            player_id = player.id
            text_id = f"#{player_id}"
            try:
                player = self.user_index.loc[text_id]
                red_players.append(player["Name"])
            except:
                red_players.append(player.display_name)
        # red_players = [player.display_name for player in self.game.red]
        # blue_players = [player.display_name for player in self.game.blue]
        blue_players = []
        for player in qdata['game'].blue:
            player_id = player.id
            text_id = f"#{player_id}"
            try:
                player = self.user_index.loc[text_id]
                blue_players.append(player["Name"])
            except:
                blue_players.append(player.display_name)

        print(f"Red {current_red}")
        print(f"Blue {current_blue}")
        # Getting match Number

        if ctx.channel.id == 824691989366046750:  # FRC
            wks = self.open_sheet("6-man Rankings + Elos", "ELO raw")
            self.elo_results = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)
            if edit == "edit":
                self.elo_results = self.elo_results.iloc[1:]
            elo_current = self.elo_results
            print(elo_current)
        elif ctx.channel.id == 712297302857089025:  # VEX
            wks = self.open_sheet("6-man Rankings + Elos", "VEX ELO Raw")
            self.elo_results2 = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)
            elo_current = self.elo_results2
        elif ctx.channel.id == 754569222260129832:  # FTC
            wks = self.open_sheet("6-man Rankings + Elos", "FTC 4 Mans Raw")
            self.elo_results3 = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)
            elo_current = self.elo_results3
        elif ctx.channel.id == 754569102873460776:  # FRC 4
            wks = self.open_sheet("6-man Rankings + Elos", "FRC 4 Mans Raw")
            self.elo_results4 = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)
            elo_current = self.elo_results4
        else:
            return

        matchnum = elo_current["Match"].iloc[0]

        print(f"Red {current_red}")
        print(f"Blue {current_blue}")
        # Calculating elo
        elo_calc_players = red_players + blue_players

        elo_player_pairs = {}
        print(elo_calc_players)
        for player in elo_calc_players:
            try:
                try:
                    elo_player_pairs.update({player: self.players_current_elo[player]})
                except:
                    # sets all matches to True
                    matches = elo_current.isin([player])
                    # Find locations of all Trues
                    outlist = [[i, matches.columns.tolist()[j]]
                               for i, r in enumerate(matches.values)
                               for j, c in enumerate(r)
                               if c]
                    # Get values of elos
                    print(player)
                    print(outlist)
                    match = outlist[0]

                    if ctx.channel.id == 824691989366046750:  # FRC
                        column_to_label = {1: "fElo1", 2: "fElo2", 3: "fElo3", 4: "fElo4", 5: "fElo5", 6: "fElo6"}
                    elif ctx.channel.id == 712297302857089025 or ctx.channel.id == 754569222260129832 or ctx.channel.id == 754569102873460776:  # VEX
                        column_to_label = {1: "fElo1", 2: "fElo2", 3: "fElo3", 4: "fElo4"}
                    else:
                        return

                    elo_player_pairs.update({player: elo_current.loc[match[0], column_to_label[match[1]]]})
            except:
                elo_player_pairs.update({player: 1200})
        result = self.calculate_elo(elo_calc_players, elo_player_pairs, int(red_score), int(blue_score))
        final_elos = result[0]

        # Set wins/losses

        if ctx.channel.id == 824691989366046750:  # FRC
            if self.past_winner == "Red":
                statuses = [f"{elo_calc_players[0]}_W", f"{elo_calc_players[1]}_W", f"{elo_calc_players[2]}_W",
                            f"{elo_calc_players[3]}_L", f"{elo_calc_players[4]}_L", f"{elo_calc_players[5]}_L"]
            elif self.past_winner == "Blue":
                statuses = [f"{elo_calc_players[0]}_L", f"{elo_calc_players[1]}_L", f"{elo_calc_players[2]}_L",
                            f"{elo_calc_players[3]}_W", f"{elo_calc_players[4]}_W", f"{elo_calc_players[5]}_W"]
            else:
                statuses = [f"{elo_calc_players[0]}_T", f"{elo_calc_players[1]}_T", f"{elo_calc_players[2]}_T",
                            f"{elo_calc_players[3]}_T", f"{elo_calc_players[4]}_T", f"{elo_calc_players[5]}_T"]
        elif ctx.channel.id == 712297302857089025 or ctx.channel.id == 754569222260129832 or ctx.channel.id == 754569222260129832:  # VEX
            if self.past_winner == "Red":
                statuses = [f"{elo_calc_players[0]}_W", f"{elo_calc_players[1]}_W",
                            f"{elo_calc_players[2]}_L", f"{elo_calc_players[3]}_L"]
            elif self.past_winner == "Blue":
                statuses = [f"{elo_calc_players[0]}_L", f"{elo_calc_players[1]}_L",
                            f"{elo_calc_players[2]}_W", f"{elo_calc_players[3]}_W"]
            else:
                statuses = [f"{elo_calc_players[0]}_T", f"{elo_calc_players[1]}_T",
                            f"{elo_calc_players[2]}_T", f"{elo_calc_players[3]}_T"]
        else:
            return

        if edit == "edit":
            data = [elo_calc_players[0], elo_calc_players[1], elo_calc_players[2], elo_calc_players[3],
                    elo_calc_players[4], elo_calc_players[5],
                    matchnum, int(red_score), int(blue_score),
                    elo_player_pairs[elo_calc_players[0]], elo_player_pairs[elo_calc_players[1]],
                    elo_player_pairs[elo_calc_players[2]],
                    elo_player_pairs[elo_calc_players[3]], elo_player_pairs[elo_calc_players[4]],
                    elo_player_pairs[elo_calc_players[5]],
                    result[3], result[4], result[1], result[2],
                    final_elos[elo_calc_players[0]], final_elos[elo_calc_players[1]],
                    final_elos[elo_calc_players[2]],
                    final_elos[elo_calc_players[3]], final_elos[elo_calc_players[4]],
                    final_elos[elo_calc_players[5]]]
            df2 = pd.DataFrame(data=[red_players + blue_players + [matchnum, red_score, blue_score]],
                               columns=["Red1", "Red2", "Red3", "Blue1", "Blue2", "Blue3", "Match Number",
                                        "Red Score",
                                        "Blue Score"])
        else:
            if ctx.channel.id == 824691989366046750:  # FRC
                data = [elo_calc_players[0], elo_calc_players[1], elo_calc_players[2], elo_calc_players[3],
                        elo_calc_players[4], elo_calc_players[5],
                        matchnum + 1, int(red_score), int(blue_score),
                        elo_player_pairs[elo_calc_players[0]], elo_player_pairs[elo_calc_players[1]],
                        elo_player_pairs[elo_calc_players[2]],
                        elo_player_pairs[elo_calc_players[3]], elo_player_pairs[elo_calc_players[4]],
                        elo_player_pairs[elo_calc_players[5]],
                        result[3], result[4], result[1], result[2],
                        final_elos[elo_calc_players[0]], final_elos[elo_calc_players[1]],
                        final_elos[elo_calc_players[2]],
                        final_elos[elo_calc_players[3]], final_elos[elo_calc_players[4]],
                        final_elos[elo_calc_players[5]]]
                df2 = pd.DataFrame(data=[red_players + blue_players + [matchnum + 1, red_score, blue_score]],
                                   columns=["Red1", "Red2", "Red3", "Blue1", "Blue2", "Blue3", "Match Number",
                                            "Red Score",
                                            "Blue Score"])
            elif ctx.channel.id == 712297302857089025 or ctx.channel.id == 754569222260129832 or ctx.channel.id == 754569222260129832:  # VEX
                headers = [1, 2, 3, 4, 'Match', 'rScore', 'bScore'
                    , 'iElo1', 'iElo2', 'iElo3', 'iElo4',
                           'rElo', 'bElo', 'rOdds', 'bOdds',
                           'fElo1', 'fElo2', 'fElo3', 'fElo4',
                           'status1', 'status2', 'status3', 'status4']
                data = [elo_calc_players[0], elo_calc_players[1], elo_calc_players[2], elo_calc_players[3],
                        matchnum + 1, int(red_score), int(blue_score),
                        elo_player_pairs[elo_calc_players[0]], elo_player_pairs[elo_calc_players[1]],
                        elo_player_pairs[elo_calc_players[2]],
                        elo_player_pairs[elo_calc_players[3]],
                        result[3], result[4], result[1], result[2],
                        final_elos[elo_calc_players[0]], final_elos[elo_calc_players[1]],
                        final_elos[elo_calc_players[2]],
                        final_elos[elo_calc_players[3]]]
                df2 = pd.DataFrame(data=[red_players + blue_players + [matchnum + 1, red_score, blue_score]],
                                   columns=["Red1", "Red2", "Blue1", "Blue2", "Match Number",
                                            "Red Score",
                                            "Blue Score"])
            else:
                return
            print(f"Red {current_red}")
            print(f"Blue {current_blue}")
            print("-----------")

        # Merge Data
        data.extend(statuses)
        dfInt = pd.DataFrame(columns=headers, data=[data])
        self.elo_results = dfInt.append(elo_current, ignore_index=True)
        print(self.elo_results)

        # Submit Data
        if ctx.channel.id == 824691989366046750:  # FRC
            self.elo_results.to_csv('matches.csv', index=False)
        elif ctx.channel.id == 712297302857089025:  # VEX
            self.elo_results.to_csv('matches2.csv', index=False)
        elif ctx.channel.id == 754569222260129832:  # FTC
            self.elo_results.to_csv('matches3.csv', index=False)
        elif ctx.channel.id == 754569222260129832:  # FRC 4
            self.elo_results.to_csv('matches4.csv', index=False)
        else:
            return

        Thread(target=self.submit_match, daemon=True, args=(ctx,)).start()

        embed = discord.Embed(color=0xcda03f, title=f"Score submitted | 🟥 {red_log}-{blue_log}  🟦 |")
        red_out = "```diff\n"
        blue_out = "```diff\n"
        i = 0
        for player in qdata['game'].red:
            red_out += f"{elo_calc_players[i]} [{round(final_elos[elo_calc_players[i]], 1)}]\n" \
                       f"{'%+d' % (round(final_elos[elo_calc_players[i]] - elo_player_pairs[elo_calc_players[i]], 2))}\n"
            i += 1
        for player in qdata['game'].blue:
            blue_out += f"{elo_calc_players[i]} [{round(final_elos[elo_calc_players[i]], 1)}]\n" \
                        f"{'%+d' % (round(final_elos[elo_calc_players[i]] - elo_player_pairs[elo_calc_players[i]], 2))}\n"
            i += 1
        red_out += "```"
        blue_out += "```"

        embed.add_field(name=f'🟥 RED 🟥 *({red_score})*',
                        value=f"{red_out}",
                        inline=True)
        embed.add_field(name=f'🟦 BLUE 🟦 *({blue_score})*',
                        value=f"{blue_out}",
                        inline=True)

        message = await ctx.channel.send(embed=embed)
        self.last_match_msg = message
        emoji = "❌"
        await message.add_reaction(emoji)
        if edit is None:
            pass
        elif edit == "edit":
            await ctx.channel.send("Edited score successfully.")
        self.set_queue(ctx, qdata)

    def submit_match(self, ctx):
        sheet_name = "6-man Rankings + Elos"

        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        credentials = ServiceAccountCredentials.from_json_keyfile_name('fantasy-first-260710-7fa1a0ed0b21.json', scope)

        gc = gspread.authorize(credentials)
        sheet = gc.open(sheet_name)

        if ctx.channel.id == 824691989366046750:  # FRC
            data = pd.read_csv("matches.csv")
            wks = sheet.worksheet("ELO raw")
        elif ctx.channel.id == 712297302857089025:  # VEX
            data = pd.read_csv("matches2.csv")
            wks = sheet.worksheet("VEX ELO Raw")
        elif ctx.channel.id == 754569222260129832:  # FTC
            data = pd.read_csv("matches3.csv")
            wks = sheet.worksheet("FTC 4 Mans Raw")
        elif ctx.channel.id == 754569102873460776:  # FRC 4
            data = pd.read_csv("matches4.csv")
            wks = sheet.worksheet("FRC 4 Mans Raw")
        else:
            return
        print(data)
        gspread_dataframe.set_with_dataframe(wks, data)
        # sys.exit()

    async def random(self, ctx):
        qdata = self.get_queue(ctx)
        channel = ctx.channel
        if qdata['busy']:
            await channel.send("Bot is busy. Please wait until picking is done.")
            return
        qdata['busy'] = True
        qdata = self.create_game(ctx)
        red = random.sample(qdata['game'].players, int(int(qdata['team_size']) / 2))
        for player in red:
            qdata['game'].add_to_red(player)

        blue = list(qdata['game'].players)
        for player in blue:
            qdata['game'].add_to_blue(player)

        self.set_queue(ctx, qdata)
        await self.display_teams(ctx)

        qdata['busy'] = False

    def calculate_elo(self, elo_calc_players, elo_player_pairs, r_score, b_score):
        # Generate team elo averages

        r_elo = 0
        for i in range(0, int((len(elo_calc_players) / 2))):
            r_elo += elo_player_pairs[elo_calc_players[i]]
        r_elo = r_elo / int((len(elo_calc_players) / 2))
        # print(f"Red elo is: {r_elo}")

        b_elo = 0
        for i in range(int((len(elo_calc_players) / 2)), len(elo_calc_players)):
            b_elo += elo_player_pairs[elo_calc_players[i]]
        b_elo = b_elo / int((len(elo_calc_players) / 2))
        # print(f"Blue elo is: {b_elo}")

        r_odds = 1 / (1 + 10 ** ((b_elo - r_elo) / self.n))
        b_odds = 1 - r_odds
        # print(f"Red odds: {r_odds}")
        # print(f"Blue odds: {b_odds}")

        new_elo_player_pairs = {}
        i = 1
        for player in elo_calc_players:
            num_played = len(self.elo_results[self.elo_results[1] == player]) + len(
                self.elo_results[self.elo_results[2] == player]) + len(
                self.elo_results[self.elo_results[3] == player]) + len(
                self.elo_results[self.elo_results[4] == player]) + len(
                self.elo_results[self.elo_results[5] == player]) + len(self.elo_results[self.elo_results[6] == player])

            if i < int((len(elo_calc_players) / 2) + 1):
                if r_score > b_score:
                    new_elo = elo_player_pairs[player] + ((
                                                                  self.k / (1 + 0) + 2 * math.log(
                                                              math.fabs(r_score - b_score) + 1, 8)) * (
                                                                  1 - r_odds)) * (((self.b - 1) / (
                            self.a ** num_played)) + 1)  # + self.r * (1200 - elo_player_pairs[player])
                elif b_score > r_score:
                    new_elo = elo_player_pairs[player] + ((
                                                                  self.k / (1 + 0) + 2 * math.log(
                                                              math.fabs(r_score - b_score) + 1, 8)) * (
                                                                  0 - r_odds)) * (((self.b - 1) / (
                            self.a ** num_played)) + 1)  # + self.r * (1200 - elo_player_pairs[player])
                else:
                    new_elo = elo_player_pairs[player] + ((
                                                                  self.k / (1 + 0) + 2 * math.log(
                                                              math.fabs(r_score - b_score) + 1, 8)) * (
                                                                  0.5 - r_odds)) * (((self.b - 1) / (
                            self.a ** num_played)) + 1)  # + self.r * (1200 - elo_player_pairs[player])

            else:
                if b_score > r_score:
                    new_elo = elo_player_pairs[player] + ((
                                                                  self.k / (1 + 0) + 2 * math.log(
                                                              math.fabs(b_score - r_score) + 1, 8)) * (
                                                                  1 - b_odds)) * (((self.b - 1) / (
                            self.a ** num_played)) + 1)  # + self.r * (1200 - elo_player_pairs[player])
                elif r_score > b_score:
                    new_elo = elo_player_pairs[player] + ((
                                                                  self.k / (1 + 0) + 2 * math.log(
                                                              math.fabs(b_score - r_score) + 1, 8)) * (
                                                                  0 - b_odds)) * (((self.b - 1) / (
                            self.a ** num_played)) + 1)  # + self.r * (1200 - elo_player_pairs[player])
                else:
                    new_elo = elo_player_pairs[player] + ((
                                                                  self.k / (1 + 0) + 2 * math.log(
                                                              math.fabs(b_score - r_score) + 1, 8)) * (
                                                                  0.5 - b_odds)) * (((self.b - 1) / (
                            self.a ** num_played)) + 1)  # + self.r * (1200 - elo_player_pairs[player])

            new_elo_player_pairs.update({player: new_elo})
            self.players_current_elo.update({player: new_elo})
            i += 1
        # print(new_elo_player_pairs)
        return new_elo_player_pairs, r_odds, b_odds, r_elo, b_elo

    # @commands.command(description="recent elo")
    # async def calctest(self, ctx):
    #     wks = self.open_sheet("6-man Rankings + Elos", "ELO raw")
    #     self.elo_results = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)
    #
    #     r_score = self.elo_results.iloc[0, 7]
    #     b_score = self.elo_results.iloc[0, 8]
    #
    #     print(f"Red Score:{r_score}")
    #     print(f"Blue Score:{b_score}")
    #
    #     # Find all players in match
    #
    #     elo_calc_players = []
    #     for i in range(0, 6):
    #         elo_calc_players.append(self.elo_results.iloc[0, i])
    #
    #     print(elo_calc_players)
    #
    #     # Find most recent ELO for each players
    #
    #     elo_player_pairs = {}
    #
    #     for player in elo_calc_players:
    #         # sets all matches to True
    #         matches = self.elo_results.isin([player])
    #         # Find locations of all Trues
    #         outlist = [[i, matches.columns.tolist()[j]]
    #                    for i, r in enumerate(matches.values)
    #                    for j, c in enumerate(r)
    #                    if c]
    #         # Get values of elos
    #         column_to_label = {1: "fElo1", 2: "fElo2", 3: "fElo3", 4: "fElo4", 5: "fElo5", 6: "fElo6"}
    #
    #         # For retroactive calcs, use 1, for current calcs use 0
    #         match = outlist[1]
    #         elo_player_pairs.update({player: self.elo_results.loc[match[0], column_to_label[match[1]]]})
    #
    #     print(elo_player_pairs)
    #
    #     result = self.calculate_elo(elo_calc_players, elo_player_pairs, r_score, b_score)
    #     print(result)

    @commands.command(description="recent elo")
    async def elolog(self, ctx, *players):
        plt.style.use('dark_background')
        for player in players:
            # sets all matches to True
            matches = self.elo_results.isin([player])
            # Find locations of all Trues
            outlist = [[i, matches.columns.tolist()[j]]
                       for i, r in enumerate(matches.values)
                       for j, c in enumerate(r)
                       if c]
            # Get values of elos
            column_to_label = {1: "fElo1", 2: "fElo2", 3: "fElo3", 4: "fElo4", 5: "fElo5", 6: "fElo6"}
            elo_history = []
            for match in outlist:
                elo_history.append(self.elo_results.loc[match[0], column_to_label[match[1]]])
            elo_history.reverse()
            plt.plot(elo_history, label=player, )
        plt.title(f"Elo history of {', '.join([player for player in players])}")
        plt.legend()
        plt.ylabel('ELO')
        plt.xlabel('Match Number')
        plt.savefig("Elo.png")
        plt.close()
        await ctx.channel.send(file=discord.File('Elo.png'))

    @commands.command(description="Shows your current elo/ranking stats", aliases=["elocheck"])
    async def checkelo(self, ctx):
        privs = {699094822132121662, 637411162203619350}
        wks = self.open_sheet("6-man Rankings + Elos", "Leaderboard")
        self.ranks = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)
        new_ranks = self.ranks[["Player", "#", "MMR", "Rank", "Wins", "Losses", "Ties"]]
        colors = {"Challenger": 0xc7ffff, "Grandmaster": 0xeb8686, "Master": 0xf985cb, "Diamond": 0xc6d2ff,
                  "Platinum": 0x54eac1, "Gold": 0xebce75, "Silver": 0xd9d9d9, "Bronze": 0xb8a25e, "Iron": 0xffffff,
                  "Stone": 0x000000}

        text_id = f"#{ctx.author.id}"
        try:
            player = self.user_index.loc[text_id]["Name"]
        except:
            await ctx.channel.send("Unable to find your data!")

        # sets all matches to True
        matches = self.elo_results.isin([player])
        # Find locations of all Trues
        outlist = [[i, matches.columns.tolist()[j]]
                   for i, r in enumerate(matches.values)
                   for j, c in enumerate(r)
                   if c]
        # Get values of elos
        column_to_label = {1: "fElo1", 2: "fElo2", 3: "fElo3", 4: "fElo4", 5: "fElo5", 6: "fElo6"}
        elo_history = []
        for match in outlist:
            elo_history.append(self.elo_results.loc[match[0], column_to_label[match[1]]])

        player_data = new_ranks.loc[new_ranks['Player'] == player]
        elo_history.reverse()
        plt.style.use('dark_background')

        roles = set([y.id for y in ctx.message.author.roles])
        if roles.intersection(privs):
            plt.plot(elo_history, label=player, color='black')
            ax = plt.gca()
            ax.set_facecolor("white")
        else:
            plt.plot(elo_history, label=player, color='white')
        plt.title(f"Elo history of {player}")
        plt.legend()
        plt.ylabel('ELO')
        plt.xlabel('Match Number')
        plt.savefig("Elo.png")
        plt.close()
        file = discord.File('Elo.png')

        embed = discord.Embed(title=f"#{player_data.iloc[0]['#']} - {player}",
                              color=colors[player_data.iloc[0]['Rank']],
                              url="https://docs.google.com/spreadsheets/d/1Oz7PRidqPPe_aC6ApHA4xo9XTpuTmgj6z9z2sy3U6ds/edit#gid=1261790407")
        embed.set_thumbnail(url=f"https://cdn.discordapp.com/avatars/{ctx.author.id}/{ctx.author.avatar}.png?size=1024")
        if 715286195612942356 in [y.id for y in ctx.message.author.roles]:
            embed.add_field(name="BETA TESTER", value=f"Thank you for your support!", inline=False)
        embed.add_field(name="Placement", value=f"#{player_data.iloc[0]['#']}/{len(new_ranks.index)}", inline=True)
        embed.add_field(name="Rank", value=f"{player_data.iloc[0]['Rank']}", inline=True)
        embed.add_field(name="MMR", value=f"{round(player_data.iloc[0]['MMR'], 1)}", inline=True)
        embed.add_field(name="Record",
                        value=f"{round(player_data.iloc[0]['Wins'])}-{round(player_data.iloc[0]['Losses'])}-{round(player_data.iloc[0]['Ties'])}",
                        inline=False)
        embed.add_field(name="Win Rate",
                        value=f"{round((player_data.iloc[0]['Wins'] / (player_data.iloc[0]['Wins'] + player_data.iloc[0]['Losses'])) * 100, 2)}%",
                        inline=True)
        embed.set_image(url="attachment://Elo.png")
        await ctx.channel.send(file=file, embed=embed)

    @commands.command(description="Updates names")
    async def namecheck(self, ctx):

        wks = self.open_sheet("6-man Rankings + Elos", "ELO raw")
        self.elo_results = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)

        wks = self.open_sheet("6-man Rankings + Elos", "User Index")
        self.user_index = gspread_dataframe.get_as_dataframe(wks)
        self.user_index.set_index("Id", inplace=True)
        self.names_to_ids = {}
        for index, row in self.user_index.iterrows():
            self.names_to_ids.update({row["Name"]: str(index)[1:]})
        await asyncio.sleep(.1)
        wks = self.open_sheet("6-man Rankings + Elos", "Leaderboard")
        ranks = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)
        new_ranks = ranks[["Player", "MMR", "Rank"]]
        for member in self.names_to_ids.values():
            try:
                user = ctx.message.guild.get_member(int(member))
                ranks_to_check = ["Challenger", "Grandmaster", "Master", "Diamond", "Platinum", "Gold", "Silver",
                                  "Bronze", "Iron", "Stone"]
                for rank in ranks_to_check:
                    role2 = get(ctx.message.author.guild.roles, name=rank)
                    if role2 in user.roles:
                        await user.remove_roles(role2)
            except:
                pass
        for index, row in new_ranks.iterrows():
            await asyncio.sleep(.1)
            try:
                user = ctx.message.guild.get_member(int(self.names_to_ids[row['Player']]))
                role = get(ctx.message.author.guild.roles, name=row["Rank"])
                # print(role)
                if role in user.roles:
                    pass
                    # print(f"{user} already has correct role")
                else:
                    ranks_to_check = ["Challenger", "Grandmaster", "Master", "Diamond", "Platinum", "Gold", "Silver",
                                      "Bronze", "Iron", "Stone"]
                    for rank in ranks_to_check:
                        role2 = get(ctx.message.author.guild.roles, name=rank)
                        if role2 in user.roles:
                            await user.remove_roles(role2)
                    await user.add_roles(role)
                    # print(f"{user} updated")
            except Exception as e:
                try:
                    user = ctx.message.guild.get_member(int(self.names_to_ids[row['Player']]))
                    ranks_to_check = ["Challenger", "Grandmaster", "Master", "Diamond", "Platinum", "Gold", "Silver",
                                      "Bronze", "Iron", "Stone"]
                    for rank in ranks_to_check:
                        role2 = get(ctx.message.author.guild.roles, name=rank)
                        if role2 in user.roles:
                            await user.remove_roles(role2)
                except:
                    print(f"Passed over {row['Player']} - {e}")
        # print(new_ranks)
        all_members = ctx.message.guild.members
        await ctx.channel.send("Names updated")

    # @commands.command(description="Updates names")
    # async def namechecktest(self, ctx):
    #     user = ctx.message.guild.get_member(236205925709512714)
    #     role = get(ctx.message.author.guild.roles, name="Bronze")
    #     if role in user.roles:
    #         pass
    #     else:
    #         ranks_to_check = ["Challenger", "Grandmaster", "Master", "Diamond", "Platinum", "Gold", "Silver",
    #                           "Bronze", "Iron"]
    #         for rank in ranks_to_check:
    #             role2 = get(ctx.message.author.guild.roles, name=rank)
    #             if role2 in user.roles:
    #                 await user.remove_roles(role2)
    #     await user.add_roles(role)
    #     print(user)

    async def display_teams(self, ctx):
        qdata = self.get_queue(ctx)
        channel = ctx.channel
        if ctx.channel.id == 824691989366046750:  # 6 FRC
            red_check = get(ctx.user.guild.roles, name="Ranked Red")
            blue_check = get(ctx.user.guild.roles, name="Ranked Blue")
            red_lobby = self.bot.get_channel(824692157142269963)
            for player in qdata['game'].red:
                to_change = get(ctx.user.guild.roles, name="Ranked Red")
                await player.add_roles(to_change)
                try:
                    await player.move_to(red_lobby)
                except Exception as e:
                    print(e)
                    pass
            blue_lobby = self.bot.get_channel(824692212528840724)
            for player in qdata['game'].blue:
                to_change = get(ctx.user.guild.roles, name="Ranked Blue")
                await player.add_roles(to_change)
                try:
                    await player.move_to(blue_lobby)
                except Exception as e:
                    print(e)
                    pass

        embed = discord.Embed(color=0xcda03f, title="Teams have been picked!")
        embed.add_field(name='🟥 RED 🟥',
                        value="{}".format("\n".join([player.mention for player in qdata['game'].red])),
                        inline=True)
        embed.add_field(name='🟦 BLUE 🟦',
                        value="{}".format("\n".join([player.mention for player in qdata['game'].blue])),
                        inline=True)

        await ctx.response.send_message(embed=embed)

        await channel.send(f"{red_check.mention} {blue_check.mention}")

    def create_game(self, ctx):
        qdata = self.get_queue(ctx)
        offset = qdata['queue'].qsize() - qdata['team_size']
        qsize = qdata['queue'].qsize()
        players = [qdata['queue'].get() for _ in range(qsize)]
        qdata['game'] = Game(players[0 + offset:team_size + offset])
        for player in players[0:offset]:
            qdata['queue'].put(player)
        players = [qdata['queue'].get() for _ in range(qdata['queue'].qsize())]
        for player in players:
            qdata['queue'].put(player)
        return qdata

    # @commands.command(description="Submit Score (WIP)")
    # async def matchnum(self, ctx):
    #     wks = self.open_sheet("6-man Rankings + Elos", "To Add")
    #     df = gspread_dataframe.get_as_dataframe(wks)
    #     print(df["Match Number"].iloc[0])
    @commands.command(description="Recalculate all Elos")
    async def fastcalcelo(self, ctx):
        if 693160987125350466 in [y.id for y in ctx.message.author.roles]:
            wks = self.open_sheet("6-man Rankings + Elos", "ELO raw")
            self.elo_results = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)
            headers = [1, 2, 3, 4, 5, 6, 'Match', 'rScore', 'bScore'
                , 'iElo1', 'iElo2', 'iElo3', 'iElo4', 'iElo5', 'iElo6',
                       'rElo', 'bElo', 'rOdds', 'bOdds',
                       'fElo1', 'fElo2', 'fElo3', 'fElo4', 'fElo5', 'fElo6',
                       'status1', 'status2', 'status3', 'status4', 'status5', 'status6']
            match_num = self.elo_results["Match"].iloc[100]
            dfFinal = pd.DataFrame(columns=headers)

            for z in range(100, -1, -1):
                r_score = self.elo_results.iloc[z, 7]
                if pd.isnull(r_score):
                    continue

                b_score = self.elo_results.iloc[z, 8]

                # Find all players in match

                elo_calc_players = []
                for i in range(0, 6):
                    elo_calc_players.append(self.elo_results.iloc[z, i])

                # Find most recent ELO for each players

                elo_player_pairs = {}

                for player in elo_calc_players:
                    try:
                        # sets all matches to True
                        matches = dfFinal.isin([player])
                        # Find locations of all Trues
                        outlist = [[i, matches.columns.tolist()[j]]
                                   for i, r in enumerate(matches.values)
                                   for j, c in enumerate(r)
                                   if c]
                        # Get values of elos
                        match = outlist[0]

                        column_to_label = {1: "fElo1", 2: "fElo2", 3: "fElo3", 4: "fElo4", 5: "fElo5", 6: "fElo6"}
                        elo_player_pairs.update({player: dfFinal.loc[match[0], column_to_label[match[1]]]})
                    except Exception as e:
                        print(e)
                        elo_player_pairs.update({player: 1200})
                result = self.calculate_elo(elo_calc_players, elo_player_pairs, r_score, b_score)
                final_elos = result[0]
                data = [elo_calc_players[0], elo_calc_players[1], elo_calc_players[2], elo_calc_players[3],
                        elo_calc_players[4], elo_calc_players[5],
                        match_num, r_score, b_score,
                        elo_player_pairs[elo_calc_players[0]], elo_player_pairs[elo_calc_players[1]],
                        elo_player_pairs[elo_calc_players[2]],
                        elo_player_pairs[elo_calc_players[3]], elo_player_pairs[elo_calc_players[4]],
                        elo_player_pairs[elo_calc_players[5]],
                        result[3], result[4], result[1], result[2],
                        final_elos[elo_calc_players[0]], final_elos[elo_calc_players[1]],
                        final_elos[elo_calc_players[2]],
                        final_elos[elo_calc_players[3]], final_elos[elo_calc_players[4]],
                        final_elos[elo_calc_players[5]]]
                if r_score > b_score:
                    statuses = [f"{elo_calc_players[0]}_W", f"{elo_calc_players[1]}_W", f"{elo_calc_players[2]}_W",
                                f"{elo_calc_players[3]}_L", f"{elo_calc_players[4]}_L", f"{elo_calc_players[5]}_L"]
                elif b_score > r_score:
                    statuses = [f"{elo_calc_players[0]}_L", f"{elo_calc_players[1]}_L", f"{elo_calc_players[2]}_L",
                                f"{elo_calc_players[3]}_W", f"{elo_calc_players[4]}_W", f"{elo_calc_players[5]}_W"]
                else:
                    statuses = [f"{elo_calc_players[0]}_T", f"{elo_calc_players[1]}_T", f"{elo_calc_players[2]}_T",
                                f"{elo_calc_players[3]}_T", f"{elo_calc_players[4]}_T", f"{elo_calc_players[5]}_T"]

                data.extend(statuses)
                dfInt = pd.DataFrame(columns=headers, data=[data])

                dfFinal = dfInt.append(dfFinal, ignore_index=True)

                match_num += 1

                await asyncio.sleep(.001)
            wks = self.open_sheet("6-man Rankings + Elos", "ELO raw")
            gspread_dataframe.set_with_dataframe(wks, dfFinal)

    @commands.command(description="Recalculate all Elos")
    async def calcelo(self, ctx):
        if 693160987125350466 in [y.id for y in ctx.message.author.roles]:
            wks = self.open_sheet("6-man Rankings + Elos", "ELO raw")
            self.elo_results = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)
            print(self.elo_results)
            headers = [1, 2, 3, 4, 5, 6, 'Match', 'rScore', 'bScore'
                , 'iElo1', 'iElo2', 'iElo3', 'iElo4', 'iElo5', 'iElo6',
                       'rElo', 'bElo', 'rOdds', 'bOdds',
                       'fElo1', 'fElo2', 'fElo3', 'fElo4', 'fElo5', 'fElo6',
                       'status1', 'status2', 'status3', 'status4', 'status5', 'status6']
            match_num = 1
            dfFinal = pd.DataFrame(columns=headers)
            print(dfFinal)
            status = await ctx.channel.send("Calculating Elo...")
            for z in range(len(self.elo_results.index) - 1, -1, -1):
                r_score = self.elo_results.iloc[z, 7]
                if pd.isnull(r_score):
                    continue

                b_score = self.elo_results.iloc[z, 8]

                # Find all players in match

                elo_calc_players = []
                for i in range(0, 6):
                    elo_calc_players.append(self.elo_results.iloc[z, i])

                # Find most recent ELO for each players

                elo_player_pairs = {}

                for player in elo_calc_players:
                    try:
                        # sets all matches to True
                        matches = dfFinal.isin([player])
                        # Find locations of all Trues
                        outlist = [[i, matches.columns.tolist()[j]]
                                   for i, r in enumerate(matches.values)
                                   for j, c in enumerate(r)
                                   if c]
                        # Get values of elos
                        match = outlist[0]

                        column_to_label = {1: "fElo1", 2: "fElo2", 3: "fElo3", 4: "fElo4", 5: "fElo5", 6: "fElo6"}
                        elo_player_pairs.update({player: dfFinal.loc[match[0], column_to_label[match[1]]]})
                    except Exception as e:
                        print(e)
                        elo_player_pairs.update({player: 1200})
                result = self.calculate_elo(elo_calc_players, elo_player_pairs, r_score, b_score)
                final_elos = result[0]
                data = [elo_calc_players[0], elo_calc_players[1], elo_calc_players[2], elo_calc_players[3],
                        elo_calc_players[4], elo_calc_players[5],
                        match_num, r_score, b_score,
                        elo_player_pairs[elo_calc_players[0]], elo_player_pairs[elo_calc_players[1]],
                        elo_player_pairs[elo_calc_players[2]],
                        elo_player_pairs[elo_calc_players[3]], elo_player_pairs[elo_calc_players[4]],
                        elo_player_pairs[elo_calc_players[5]],
                        result[3], result[4], result[1], result[2],
                        final_elos[elo_calc_players[0]], final_elos[elo_calc_players[1]],
                        final_elos[elo_calc_players[2]],
                        final_elos[elo_calc_players[3]], final_elos[elo_calc_players[4]],
                        final_elos[elo_calc_players[5]]]
                if r_score > b_score:
                    statuses = [f"{elo_calc_players[0]}_W", f"{elo_calc_players[1]}_W", f"{elo_calc_players[2]}_W",
                                f"{elo_calc_players[3]}_L", f"{elo_calc_players[4]}_L", f"{elo_calc_players[5]}_L"]
                elif b_score > r_score:
                    statuses = [f"{elo_calc_players[0]}_L", f"{elo_calc_players[1]}_L", f"{elo_calc_players[2]}_L",
                                f"{elo_calc_players[3]}_W", f"{elo_calc_players[4]}_W", f"{elo_calc_players[5]}_W"]
                else:
                    statuses = [f"{elo_calc_players[0]}_T", f"{elo_calc_players[1]}_T", f"{elo_calc_players[2]}_T",
                                f"{elo_calc_players[3]}_T", f"{elo_calc_players[4]}_T", f"{elo_calc_players[5]}_T"]

                data.extend(statuses)
                dfInt = pd.DataFrame(columns=headers, data=[data])

                dfFinal = dfInt.append(dfFinal, ignore_index=True)
                print(dfInt)

                match_num += 1
                if z % 20 == 0:
                    await status.edit(
                        content=f"Calculating Elo... [{len(self.elo_results.index) - z}/{len(self.elo_results.index)}]")
                await asyncio.sleep(.001)
            wks = self.open_sheet("6-man Rankings + Elos", "ELO raw")
            gspread_dataframe.set_with_dataframe(wks, dfFinal)

    @commands.command(description="Recalculate all Elos")
    async def fcalcelo(self, ctx):
        if 693160987125350466 in [y.id for y in ctx.message.author.roles]:
            wks = self.open_sheet("6-man Rankings + Elos", "FTC 4 Mans Raw")
            self.elo_results = gspread_dataframe.get_as_dataframe(wks, evaluate_formulas=True)
            headers = [1, 2, 3, 4, 'Match', 'rScore', 'bScore'
                , 'iElo1', 'iElo2', 'iElo3', 'iElo4',
                       'rElo', 'bElo', 'rOdds', 'bOdds',
                       'fElo1', 'fElo2', 'fElo3', 'fElo4',
                       'status1', 'status2', 'status3', 'status4']
            match_num = 1
            dfFinal = pd.DataFrame(columns=headers)

            for z in range(len(self.elo_results.index) - 1, -1, -1):
                r_score = self.elo_results.iloc[z, 5]
                if pd.isnull(r_score):
                    continue

                b_score = self.elo_results.iloc[z, 6]

                # Find all players in match

                elo_calc_players = []
                for i in range(0, 4):
                    elo_calc_players.append(self.elo_results.iloc[z, i])

                # Find most recent ELO for each players

                elo_player_pairs = {}

                for player in elo_calc_players:
                    try:
                        # sets all matches to True
                        matches = dfFinal.isin([player])
                        # Find locations of all Trues
                        outlist = [[i, matches.columns.tolist()[j]]
                                   for i, r in enumerate(matches.values)
                                   for j, c in enumerate(r)
                                   if c]
                        # Get values of elos
                        match = outlist[0]

                        column_to_label = {1: "fElo1", 2: "fElo2", 3: "fElo3", 4: "fElo4"}
                        elo_player_pairs.update({player: dfFinal.loc[match[0], column_to_label[match[1]]]})
                    except Exception as e:
                        print(e)
                        elo_player_pairs.update({player: 1200})
                result = self.calculate_elo(elo_calc_players, elo_player_pairs, r_score, b_score)
                final_elos = result[0]
                data = [elo_calc_players[0], elo_calc_players[1], elo_calc_players[2], elo_calc_players[3],
                        match_num, r_score, b_score,
                        elo_player_pairs[elo_calc_players[0]], elo_player_pairs[elo_calc_players[1]],
                        elo_player_pairs[elo_calc_players[2]],
                        elo_player_pairs[elo_calc_players[3]],
                        result[3], result[4], result[1], result[2],
                        final_elos[elo_calc_players[0]], final_elos[elo_calc_players[1]],
                        final_elos[elo_calc_players[2]],
                        final_elos[elo_calc_players[3]]]
                if r_score > b_score:
                    statuses = [f"{elo_calc_players[0]}_W", f"{elo_calc_players[1]}_W", f"{elo_calc_players[2]}_L",
                                f"{elo_calc_players[3]}_L"]
                elif b_score > r_score:
                    statuses = [f"{elo_calc_players[0]}_L", f"{elo_calc_players[1]}_L", f"{elo_calc_players[2]}_W",
                                f"{elo_calc_players[3]}_W"]
                else:
                    statuses = [f"{elo_calc_players[0]}_T", f"{elo_calc_players[1]}_T", f"{elo_calc_players[2]}_T",
                                f"{elo_calc_players[3]}_T"]

                data.extend(statuses)
                dfInt = pd.DataFrame(columns=headers, data=[data])

                dfFinal = dfInt.append(dfFinal, ignore_index=True)

                match_num += 1

                await asyncio.sleep(.001)
            wks = self.open_sheet("6-man Rankings + Elos", "FTC 4 Mans Raw")
            gspread_dataframe.set_with_dataframe(wks, dfFinal)

    @app_commands.command(name="clearmatch", description="Clears current running match")
    async def clearmatch(self, interaction: discord.Interaction):
        qdata = self.get_queue(interaction)

        if 699094822132121662 in [y.id for y in interaction.user.roles]:
            qdata['red_series'] = 2
            qdata['blue_series'] = 2
            self.set_queue(interaction, qdata)
            await remove_roles(interaction)
            await interaction.response.send_message("Cleared successfully!")

    @app_commands.command(name="rules", description="Posts a link the the rules")
    async def rules(self, interaction: discord.Interaction):
        await interaction.response.send_message("The rules can be found here: https://bit.ly/SRCrules.")


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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        Ranked(bot),
        guilds=[discord.Object(id=637407041048281098)]
    )
