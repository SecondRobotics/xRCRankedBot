import discord
from discord import app_commands
from discord.ext import commands

GUILD_ID = 637407041048281098

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(description="Ping the bot")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message("Pong!")

async def setup(bot: commands.Bot) -> None:
    cog = General(bot)
    guild = await bot.fetch_guild(GUILD_ID)
    assert guild is not None

    await bot.add_cog(
        cog,
        guilds=[guild]
    )
