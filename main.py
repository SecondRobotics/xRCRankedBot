from discord import app_commands
import discord
from discord.ext import commands
import os
import logging
import logging.handlers
from dotenv import load_dotenv
from discord.utils import get
import asyncio
from config import *
from webhook_server import StripeWebhookServer

logger = logging.getLogger('discord')
load_dotenv()

intents = discord.Intents.all()
intents.message_content = True

class RankedBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!!!",
            intents=discord.Intents.all(),
            application_id=DISCORD_APPLICATION_ID)
        self.ranked_cog = None

    async def setup_hook(self):
        await self.load_extension("cogs.ranked")
        await self.load_extension("cogs.server")
        await self.load_extension("cogs.general")
        await self.load_extension("cogs.userManagement")
        await self.load_extension("cogs.payments")  # Load payments cog
        await self.tree.sync(guild=discord.Object(id=GUILD_ID))
        
        # Start webhook server if Stripe is configured
        if STRIPE_API_KEY and STRIPE_WEBHOOK_SECRET:
            self.webhook_server = StripeWebhookServer(self)
            asyncio.create_task(self.webhook_server.start())

    async def on_ready(self):
        logger.info("The bot is alive!")
        # Required to update all slash commands
        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,
                                                            name=str("xRC Sim Ranked Queue")))
        if self.ranked_cog:
            await self.ranked_cog.startup()
        
        logger.info("Bot startup complete")
    
    def set_ranked_cog_reference(self, cog):
        self.ranked_cog = cog

bot = RankedBot()

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
