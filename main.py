from discord import app_commands
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.all()
intents.message_content = True


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

bot.run(os.getenv("DISCORD_BOT_TOKEN"))
