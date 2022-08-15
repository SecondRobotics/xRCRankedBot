from discord import app_commands
import discord
from discord.ext import commands
import os
import logging
import logging.handlers
from dotenv import load_dotenv

logger = logging.getLogger('discord')
load_dotenv()

if not os.getenv('DISCORD_BOT_TOKEN'):
    logger.fatal('DISCORD_BOT_TOKEN not found')
    raise RuntimeError('DISCORD_BOT_TOKEN not found')
if not os.getenv('SRC_API_TOKEN'):
    logger.fatal('SRC_API_TOKEN not found')
    raise RuntimeError('SRC_API_TOKEN not found')

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
        logger.info("The bot is alive!")
        # Required to update all slash commands
        await bot.change_presence(activity=discord.Game(name=str("xRC Sim Ranked Queue")))


bot = RankedBot()
#tree = app_commands.CommandTree(bot)


@app_commands.command()
async def ping(interaction: discord.Interaction):
    """Pingggg"""
    await interaction.response.send_message('Pong! {0} :ping_pong: '.format(round(bot.latency * 1000, 4)),
                                            ephemeral=False)

file_log_handler = logging.handlers.RotatingFileHandler(
    filename='bot.log',
    encoding='utf-8',
    maxBytes=32 * 1024 * 1024,  # 32 MiB
    backupCount=5,  # Rotate through 5 files
)
file_log_handler.setFormatter(logging.Formatter(
    '%(asctime)s : %(levelname)s : %(name)s : %(message)s'))
logger.setLevel(logging.INFO)
logger.addHandler(file_log_handler)
stdout_log_handler = logging.StreamHandler()
stdout_log_handler.setFormatter(logging.Formatter(
    '%(asctime)s : %(levelname)s : %(name)s : %(message)s'))
logger.setLevel(logging.INFO)
logger.addHandler(stdout_log_handler)

bot.run(os.getenv("DISCORD_BOT_TOKEN"), log_handler=None)
