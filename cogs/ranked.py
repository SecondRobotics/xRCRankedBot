from discord import app_commands
import random
from queue import Queue
from discord.utils import get
from oauth2client.service_account import ServiceAccountCredentials
import gspread
import gspread_dataframe
import discord
from discord.ext import commands
import asyncio
import matplotlib.pyplot as plt
from collections.abc import MutableSet
import requests
from dotenv import load_dotenv
import os
from discord.app_commands import Choice

load_dotenv()

team_size = 6
team_size_alt = 4
approved_channels = [824691989366046750, 712297302857089025, 650967104933330947, 754569102873460776, 754569222260129832]
header = {"x-api-key": os.getenv("SRC_API_TOKEN")}

listener = commands.Cog.listener

playable_games = [
        Choice(name="Rapid React 3v3", value="RapidReact3v3"),
        Choice(name="Rapid React 2v2", value="RapidReact2v2"),
        Choice(name="Rapid React 1v1", value="RapidReact1v1")
    ]
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


class XrcGame():
    def __init__(self, game, game_size, api_short):
        self.queue = PlayerQueue()
        self.game_type = game
        self.game = None
        self.game_size = game_size
        self.red_series = 2
        self.blue_series = 2
        self.red_captain = None
        self.blue_captain = None
        self.clearmatch_message = None
        self.autoq = []
        self.team_size = int(game_size/2)
        self.api_short = api_short


def create_game(game_type):
    qdata = game_queues[game_type]
    offset = qdata.queue.qsize() - qdata.game_size
    print(offset)
    print(qdata.game_size)
    qsize = qdata.queue.qsize()
    players = [qdata.queue.get() for _ in range(qsize)]
    qdata.game = Game(players[0 + offset:qdata.game_size + offset])
    for player in players[0:offset]:
        qdata.queue.put(player)
    players = [qdata.queue.get() for _ in range(qdata.queue.qsize())]
    for player in players:
        qdata.queue.put(player)
    return qdata


class Ranked(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = PlayerQueue()
        self.game = None
        self.red_series = 2
        self.blue_series = 2
        self.red_captain = None
        self.blue_captain = None
        self.clearmatch_message = None
        self.autoq = []

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

    @app_commands.command(description="memes")
    @app_commands.checks.has_any_role("Event Staff")
    async def test(self, interaction: discord.Interaction, game: str):
        result = game_queues[game]

        await interaction.response.send_message(result.game_size, ephemeral=True)


    # borked

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
            await ctx.channel.send(
                f"Autoqing is only available to patreons. To become a patreon check out this link! https://www.patreon.com/BrennanB ")
        print(self.autoq)

    # async def queue_auto(self, ctx):
    #
    #     print(qdata)
    #     for id in self.autoq:
    #         member = ctx.guild.get_member(id)
    #         qdata['queue'].put(member)
    #         await ctx.channel.send(
    #             "{} was autoqed. ({:d}/{:d})".format(member.display_name, qdata['queue'].qsize(),
    #                                                  qdata['team_size']))

    @app_commands.choices(game=playable_games)
    @app_commands.command(description="Force queue players")
    async def queueall(self, interaction: discord.Interaction,
                       game: str,
                       member1: discord.Member = None,
                       member2: discord.Member = None,
                       member3: discord.Member = None,
                       member4: discord.Member = None,
                       member5: discord.Member = None,
                       member6: discord.Member = None):
        qdata = game_queues[game]

        members = [member1, member2, member3, member4, member5, member6]
        members_clean = [i for i in members if i]
        added_players = ""
        if interaction.user.id == 118000175816900615:
            for member in members_clean:
                qdata.queue.put(member)
                added_players += f"{member.display_name}\n"
            await interaction.response.send_message(f"Successfully added\n{added_players} to the queue.",
                                                    ephemeral=True)
        else:
            await interaction.response.send_message("Nerd.", ephemeral=True)

    # @commands.command(pass_context=True)
    # async def seriestest(self, ctx):
    #     await ctx.channel.send(f"{self.red_series} {self.blue_series}")
    @app_commands.choices(game=playable_games)
    @app_commands.command(name="queue", description="Add yourself to the queue")
    async def q(self, interaction: discord.Interaction, game: str):
        """Enter's player into queue for upcoming matches"""

        url = f'https://secondrobotics.org/api/ranked/player/{interaction.user.id}'

        x = requests.get(url, headers=header)
        thing = x.json()

        if not thing["exists"]:
            await interaction.response.send_message(
                "You must register for an account at <https://www.secondrobotics.org/login> before you can queue.",
                ephemeral=True)
            return

        qdata = game_queues[game]

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
                    await interaction.response.send_message("You are already playing in a game!", ephemeral=True)
                    return
            else:
                await interaction.response.send_message("You can't queue in this channel.", ephemeral=True)
            if player in qdata.queue:
                await interaction.response.send_message("You are already in this queue.", ephemeral=True)
                return

            qdata.queue.put(player)

            await interaction.response.send_message(
                f"**{player.display_name}**\nadded to queue for __{game}__. *({qdata.queue.qsize()}/{qdata.game_size})*")
            if qdata.queue.qsize() >= qdata.game_size:
                if qdata.red_series == 2 or qdata.blue_series == 2:
                    await interaction.channel.send("Queue is now full! Type /startmatch")
                else:
                    await interaction.channel.send(
                        "Queue is now full! You can start as soon as the current match concludes.")

    #
    @app_commands.choices(game=playable_games)
    @app_commands.command()
    async def queuestatus(self, interaction: discord.Interaction, game: str):
        """View who is currently in the queue"""
        qdata = game_queues[game]
        try:
            for _ in range(0, 2):  # loop to not reverse order
                players = [qdata.queue.get() for _ in range(qdata.queue.qsize())]
                for player in players:
                    qdata.queue.put(player)
            embed = discord.Embed(color=0xcda03f, title=f"Signed up players for {game}")
            embed.add_field(name='Players',
                            value="{}".format("\n".join([player.mention for player in players])),
                            inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except:
            await interaction.response.send_message(f"Nobody is in queue for {game}!", ephemeral=True)

    @app_commands.choices(game=playable_games)
    @app_commands.command(name="leave", description="Remove yourself from the queue")
    async def leave(self, interaction: discord.Interaction, game: str):
        qdata = game_queues[game]
        if interaction.channel.id in approved_channels:
            player = interaction.user
            print(qdata.queue)
            if player in qdata.queue:
                qdata.queue.remove(player)
                await interaction.response.send_message(
                    f"**{player.display_name}**\nremoved to queue for __{game}__. *({qdata.queue.qsize()}/{qdata.game_size})*")
                return
            else:
                await interaction.response.send_message("You aren't in this queue.", ephemeral=True)
                return

    @app_commands.choices(game=playable_games)
    @app_commands.command(description="Remove someone else from the queue")
    @app_commands.checks.has_any_role("Event Staff")
    async def kick(self, interaction: discord.Interaction, player: discord.Member, game: str):
        qdata = game_queues[game]
        if interaction.channel.id in approved_channels:
            if player in qdata.queue:
                qdata.queue.remove(player)
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

    @app_commands.choices(game=playable_games)
    @app_commands.command(description="Start a game")
    async def startmatch(self, interaction: discord.Interaction, game: str):
        qdata = game_queues[game]
        print(qdata.red_series)
        if not qdata.queue.qsize() >= qdata.game_size:
            await interaction.response.send_message("Queue is not full.", ephemeral=True)
            return
        if qdata.red_series == 2 or qdata.blue_series == 2:
            qdata.red_series = 0
            qdata.blue_series = 0
            qdata.past_winner = ""

            pass
        else:
            await interaction.response.send_message("Current match incomplete.", ephemeral=True)
            return
        if interaction.channel.id == 712297302857089025 or \
                interaction.channel.id == 754569222260129832 or \
                interaction.channel.id == 754569102873460776:
            return await self.random(interaction, game)
        chooser = random.randint(1, 10)
        if chooser < 0:  # 6
            print("Captains")
            # await self.captains(interaction)
        else:
            print("Randoms")
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
    #         print(msg)
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

    def open_sheet(self, sheet_name, tab_name):
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        credentials = ServiceAccountCredentials.from_json_keyfile_name('fantasy-first-260710-7fa1a0ed0b21.json', scope)
        gc = gspread.authorize(credentials)
        stuff = gc.open(sheet_name)
        wks = stuff.worksheet(tab_name)
        return wks

    @app_commands.choices(game=playable_games)
    @app_commands.command(description="Submit Score")
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: i.guild_id)
    async def submit(self, interaction: discord.Interaction, game: str, red_score: int, blue_score: int):
        await interaction.response.defer()
        print(game)
        qdata = game_queues[game]
        if interaction.channel.id == 824691989366046750:  # FRC
            roles = [y.id for y in interaction.user.roles]
            ranked_roles = [699094822132121662, 824711734069297152, 824711824011427841]
            # Returns false if not in a game currently. Looks for duplicates between roles and ranked_roles
            submit_check = bool(set(roles).intersection(ranked_roles))
            if submit_check:
                pass
            else:
                await interaction.followup.send("You are ineligible to submit!", ephemeral=True)
                return

        if interaction.channel.id == 824691989366046750:  # FRC
            print(qdata.red_series)
            print(qdata.blue_series)
            if qdata.red_series == 2 or qdata.blue_series == 2:
                print("INSIDE")
                print(qdata.red_series)
                print(qdata.blue_series)
                print(interaction)
                await interaction.followup.send("Series is complete already!", ephemeral=True)
                return
        else:
            return
        print("Checking ")
        # Red wins
        if int(red_score) > int(blue_score):
            qdata.red_series += 1
            qdata.past_winner = "Red"

        # Blue wins
        elif int(red_score) < int(blue_score):
            qdata.blue_series += 1
            qdata.past_winner = "Blue"
        print(f"Red {qdata.red_series}")
        print(f"Blue {qdata.blue_series}")
        if qdata.red_series == 2:
            # await self.queue_auto(interaction)
            await interaction.followup.send("🟥 Red Wins! 🟥")
            await remove_roles(interaction)

            # Kick players back to main lobby
            channel = self.bot.get_channel(824692157142269963)
            lobby = self.bot.get_channel(824692700364275743)
            for member in channel.members:
                await member.move_to(lobby)
            channel = self.bot.get_channel(824692212528840724)
            for member in channel.members:
                await member.move_to(lobby)

        elif qdata.blue_series == 2:
            # await self.queue_auto(interaction)
            await interaction.followup.send("🟦 Blue Wins! 🟦")
            await remove_roles(interaction)

            # Kick players back to lobby
            channel = self.bot.get_channel(824692157142269963)
            lobby = self.bot.get_channel(824692700364275743)
            for member in channel.members:
                await member.move_to(lobby)
            channel = self.bot.get_channel(824692212528840724)
            for member in channel.members:
                await member.move_to(lobby)
        else:
            print(interaction)
            await interaction.followup.send("Score Submitted")
            print("got here")

        print("Blah")
        # Finding player ids
        red_ids = []
        for player in qdata.game.red:
            red_ids.append(player.id)

        blue_ids = []
        for player in qdata.game.blue:
            blue_ids.append(player.id)

        url = f'https://secondrobotics.org/api/ranked/{qdata.api_short}/match/'
        json = {
            "red_alliance": red_ids,
            "blue_alliance": blue_ids,
            "red_score": red_score,
            "blue_score": blue_score
        }
        x = requests.post(url, json=json, headers=header)
        print(x.json())
        response = x.json()
        # Getting match Number


        embed = discord.Embed(color=0xcda03f, title=f"Score submitted | 🟥 {qdata.red_series}-{qdata.blue_series}  🟦 |")
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

        message = await interaction.channel.send(embed=embed)


    async def random(self, interaction, game_type):
        print("randomizing")
        qdata = create_game(game_type)
        print(f"players: {qdata.game.players}")
        print(f"Team size {qdata.team_size}")
        red = random.sample(qdata.game.players, int(qdata.team_size))
        print(red)
        for player in red:
            print(player)
            qdata.game.add_to_red(player)

        blue = list(qdata.game.players)
        print(blue)
        for player in blue:
            print(player)
            qdata.game.add_to_blue(player)

        await self.display_teams(interaction, qdata)

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

    async def display_teams(self, ctx, qdata):
        channel = ctx.channel
        if ctx.channel.id == 824691989366046750:  # 6 FRC
            red_check = get(ctx.user.guild.roles, name="Ranked Red")
            blue_check = get(ctx.user.guild.roles, name="Ranked Blue")
            red_lobby = self.bot.get_channel(824692157142269963)
            print(f"awefawfawsfe {qdata.game.red}")
            for player in qdata.game.red:
                to_change = get(ctx.user.guild.roles, name="Ranked Red")
                print(player.display_name)
                await player.add_roles(to_change)
                try:
                    await player.move_to(red_lobby)
                except Exception as e:
                    print(e)
                    pass
            blue_lobby = self.bot.get_channel(824692212528840724)
            for player in qdata.game.blue:
                print(player.display_name)
                to_change = get(ctx.user.guild.roles, name="Ranked Blue")
                await player.add_roles(to_change)
                try:
                    await player.move_to(blue_lobby)
                except Exception as e:
                    print(e)
                    pass

        print(qdata.game.red)
        embed = discord.Embed(color=0xcda03f, title="Teams have been picked!")
        embed.add_field(name='🟥 RED 🟥',
                        value="{}".format("\n".join([player.mention for player in qdata.game.red])),
                        inline=True)
        embed.add_field(name='🟦 BLUE 🟦',
                        value="{}".format("\n".join([player.mention for player in qdata.game.blue])),
                        inline=True)

        await ctx.response.send_message(embed=embed)

        await channel.send(f"{red_check.mention} {blue_check.mention}")

    # @commands.command(description="Submit Score (WIP)")
    # async def matchnum(self, ctx):
    #     wks = self.open_sheet("6-man Rankings + Elos", "To Add")
    #     df = gspread_dataframe.get_as_dataframe(wks)
    #     print(df["Match Number"].iloc[0])

    @app_commands.choices(game=playable_games)
    @app_commands.command(name="clearmatch", description="Clears current running match")
    async def clearmatch(self, interaction: discord.Interaction, game: str):
        qdata = game_queues[game]

        if 699094822132121662 in [y.id for y in interaction.user.roles]:
            qdata.red_series = 2
            qdata.blue_series = 2

            await remove_roles(interaction)
            channel = self.bot.get_channel(824692157142269963)
            lobby = self.bot.get_channel(824692700364275743)
            for member in channel.members:
                await member.move_to(lobby)
            channel = self.bot.get_channel(824692212528840724)
            for member in channel.members:
                await member.move_to(lobby)
            await interaction.response.send_message("Cleared successfully!")

    @app_commands.command(name="rules", description="Posts a link the the rules")
    async def rules(self, interaction: discord.Interaction):
        await interaction.response.send_message("The rules can be found here: https://bit.ly/SRCrules.")


class Game:
    def __init__(self, players):
        self.players = set(players)
        if len(players)>2:
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


game_queues = {
               "RapidReact3v3": XrcGame("RapidReact", 6, "RR3v3"),
               "RapidReact2v2": XrcGame("RapidReact", 4, "RR2v2"),
               "RapidReact1v1": XrcGame("RapidReact", 2, "RR1v1"),
               }


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        Ranked(bot),
        guilds=[discord.Object(id=637407041048281098)]
    )
