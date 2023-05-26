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


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(description="Ping the bot")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000, 2)
        await interaction.response.send_message(f"Pong! Latency: {latency}ms")

    @app_commands.command(description="Player Info")
    async def playerinfo(self, interaction: discord.Interaction):
        url = f'https://secondrobotics.org/api/ranked/player/{interaction.user.id}'
        x = requests.get(url, headers=HEADER)
        res = x.json()
        logger.info(res)

        if not res["exists"]:
            await interaction.response.send_message(
                "You must register for an account at <https://www.secondrobotics.org/login> before you can queue.",
                ephemeral=True)
            return

        user = interaction.user
        embed = discord.Embed(title="User Information", color=0x34eb3d)
        embed.set_author(name=user.name, icon_url=res['avatar'])
        embed.add_field(name="Display Name", value=res['display_name'], inline=True)
        embed.add_field(name="Avatar", value=res['avatar'], inline=True)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    cog = General(bot)
    guild = await bot.fetch_guild(GUILD_ID)
    assert guild is not None

    await bot.add_cog(
        cog,
        guilds=[guild]
    )
