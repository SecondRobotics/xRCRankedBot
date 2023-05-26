import discord
from discord import app_commands
from discord.ext import commands
import requests
from dotenv import load_dotenv
import logging
import os

GUILD_ID = 637407041048281098

logger = logging.getLogger('discord')

SRC_API_TOKEN = os.getenv('SRC_API_TOKEN')
if not SRC_API_TOKEN:
    logger.fatal('SRC_API_TOKEN not found')
    raise RuntimeError('SRC_API_TOKEN not found')

HEADER = {"x-api-key": SRC_API_TOKEN}

games = requests.get("https://secondrobotics.org/api/ranked/").json()

short_codes = [games['short_code'] for games in games]
short_codes_sorted = sorted(short_codes)


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(description="Ping the bot")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000, 2)
        await interaction.response.send_message(f"Pong! Latency: {latency}ms")

    @app_commands.command(description="Player Info")
    async def playerinfo(self, interaction: discord.Interaction, user: discord.Member = None):

        await interaction.response.defer()
        if user is None:
            user = interaction.user
        user_id = user.id

        url = f'https://secondrobotics.org/api/ranked/player/{user_id}'
        x = requests.get(url, headers=HEADER)
        res = x.json()
        logger.info(res)
        if not res["exists"]:
            await interaction.followup.send(
                "You must register for an account at <https://www.secondrobotics.org/login> before you can queue.",
                ephemeral=True)
            return
        embed = discord.Embed(title="Player Information", color=0x34eb3d)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url)
        embed.set_thumbnail(url=res['avatar'])
        embed.add_field(name="Display Name", value=res['display_name'], inline=False)

        total_wins = 0
        total_losses = 0
        total_ties = 0
        total_points = 0

        for game in short_codes_sorted:
            url = f'https://secondrobotics.org/api/ranked/{game}/player/{user_id}'
            x = requests.get(url, headers=HEADER)
            gamedata = x.json()
            logger.info(gamedata)

            if "error" not in gamedata:
                total_score = "{:,}".format(gamedata['total_score'])
                record = f"{gamedata['matches_won']}-{gamedata['matches_lost']}-{gamedata['matches_drawn']}"
                embed.add_field(name=f"{gamedata['name']} [{round(gamedata['elo'], 2)}]",
                                value=f"Record: {record} [{gamedata['matches_played']}]\n"
                                      f"Total Points Scored: {total_score}", inline=True)

                total_wins += gamedata['matches_won']
                total_losses += gamedata['matches_lost']
                total_ties += gamedata['matches_drawn']
                total_points += gamedata['total_score']

        total_matches = total_wins + total_losses + total_ties
        win_rate = (total_wins / total_matches) * 100 if total_matches > 0 else 0
        win_rate = round(win_rate, 2)

        summary = f"Record: {total_wins}-{total_losses}-{total_ties}\n" \
                  f"Total Points Scored: {total_points:,}\n" \
                  f"Win Rate: {win_rate}%"
        embed.add_field(name="Summary", value=summary, inline=False)

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    cog = General(bot)
    guild = await bot.fetch_guild(GUILD_ID)
    assert guild is not None

    await bot.add_cog(
        cog,
        guilds=[guild]
    )
