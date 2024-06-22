import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger('discord')
load_dotenv()

DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
if not DISCORD_BOT_TOKEN:
    logger.fatal('DISCORD_BOT_TOKEN not found')
    raise RuntimeError('DISCORD_BOT_TOKEN not found')

DISCORD_APPLICATION_ID = os.getenv('DISCORD_APPLICATION_ID')
if not DISCORD_APPLICATION_ID:
    logger.fatal('DISCORD_APPLICATION_ID not found')
    raise RuntimeError('DISCORD_APPLICATION_ID not found')

SRC_API_TOKEN = os.getenv('SRC_API_TOKEN')
if not SRC_API_TOKEN:
    logger.fatal('SRC_API_TOKEN not found')
    raise RuntimeError('SRC_API_TOKEN not found')

GUILD_ID = int(os.getenv('GUILD_ID'))
if not GUILD_ID:
    logger.fatal('GUILD_ID not found')
    raise RuntimeError('GUILD_ID not found')

QUEUE_STATUS_CHANNEL_ID = int(os.getenv('QUEUE_STATUS_CHANNEL_ID'))
if not QUEUE_STATUS_CHANNEL_ID:
    logger.fatal('QUEUE_STATUS_CHANNEL_ID not found')
    raise RuntimeError('QUEUE_STATUS_CHANNEL_ID not found')

QUEUE_CHANNEL_ID =int(os.getenv('QUEUE_CHANNEL_ID'))
if not QUEUE_CHANNEL_ID:
    logger.fatal('QUEUE_CHANNEL_ID not found')
    raise RuntimeError('QUEUE_CHANNEL_ID not found')

RULES_CHANNEL_ID = int(os.getenv('RULES_CHANNEL_ID'))
if not RULES_CHANNEL_ID:
    logger.fatal('RULES_CHANNEL_ID not found')
    raise RuntimeError('RULES_CHANNEL_ID not found')

CATEGORY_ID = int(os.getenv('CATEGORY_ID'))
if not CATEGORY_ID:
    logger.fatal('CATEGORY_ID not found')
    raise RuntimeError('CATEGORY_ID not found')

ALLOWED_CHANNEL_IDS = [QUEUE_CHANNEL_ID]

EVENT_STAFF_ID = int(os.getenv('EVENT_STAFF_ID'))
if not EVENT_STAFF_ID:
    logger.fatal('EVENT_STAFF_ID not found')
    raise RuntimeError('EVENT_STAFF_ID not found')

LOBBY_VC_ID = int(os.getenv('LOBBY_VC_ID'))
if not LOBBY_VC_ID:
    logger.fatal('LOBBY_VC_ID not found')
    raise RuntimeError('LOBBY_VC_ID not found')

BOTS_ROLE_ID = int(os.getenv('BOTS_ROLE_ID'))
if not BOTS_ROLE_ID:
    logger.fatal('BOTS_ROLE_ID not found')
    raise RuntimeError('BOTS_ROLE_ID not found')