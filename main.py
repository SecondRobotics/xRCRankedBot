from discord import app_commands
import discord
from discord.ext import commands
import os
import logging
import logging.handlers
from dotenv import load_dotenv
from discord.utils import get

logger = logging.getLogger('discord')
load_dotenv()

DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
if not DISCORD_BOT_TOKEN:
    logger.fatal('DISCORD_BOT_TOKEN not found')
    raise RuntimeError('DISCORD_BOT_TOKEN not found')

SRC_API_TOKEN = os.getenv('SRC_API_TOKEN')
if not SRC_API_TOKEN:
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
        await self.load_extension(f"cogs.general")
        await bot.tree.sync(guild=discord.Object(id=637407041048281098))

    async def on_ready(self):
        logger.info("The bot is alive!")
        # Required to update all slash commands
        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,
                                                            name=str("xRC Sim Ranked Queue")))
        # Purge any old messages

        qstatus_channel = get(bot.get_all_channels(), id=1009630461393379438)
        if qstatus_channel is None or not isinstance(qstatus_channel, discord.TextChannel):
            logger.fatal("Could not find queue status channel")
            raise RuntimeError("Could not find queue status channel")
        limit = 0
        async for msg in qstatus_channel.history(limit=None):
            limit += 1
        await qstatus_channel.purge(limit=limit)
        embed = discord.Embed(title="xRC Sim Ranked Queues",
                              description="Ranked queues are open!", color=0x00ff00)
        embed.set_thumbnail(
            url="https://secondrobotics.org/logos/xRC%20Logo.png")
        embed.add_field(name="No current queues",
                        value="Queue to get a match started!", inline=False)
        await qstatus_channel.send(embed=embed)


bot = RankedBot()
#tree = app_commands.CommandTree(bot)


@app_commands.command()
async def ping(interaction: discord.Interaction):
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

bot.run(DISCORD_BOT_TOKEN, log_handler=None)
