import os
import logging
from dotenv import load_dotenv
from discord.app_commands import Choice

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

QUEUE_CHANNEL_ID = int(os.getenv('QUEUE_CHANNEL_ID'))
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

RANKED_ADMIN_USERNAME = os.getenv('RANKED_ADMIN_USERNAME')
if not RANKED_ADMIN_USERNAME:
    logger.fatal('RANKED_ADMIN_USERNAME not found')
    raise RuntimeError('RANKED_ADMIN_USERNAME not found')

server_games = {
    "Test": "-1",
    "Splish Splash": "0",
    "Relic Recovery": "1",
    "Rover Ruckus": "2",
    "Skystone": "3",
    "Infinite Recharge": "4",
    "Change Up": "5",
    "Bot Royale": "6",
    "Ultimate Goal": "7",
    "Tipping Point": "8",
    "Freight Frenzy": "9",
    "Rapid React": "10",
    "Spin Up": "11",
    "Power Play": "12",
    "Charged Up": "13",
    "Over Under": "14",
    "Centerstage": "15",
    "Crescendo": "16",
    "High Stakes": "17",
    "Into The Deep": "18",
    "Reefscape": "19",
}

server_games_choices = [
    Choice(name=game, value=server_games[game]) for game in server_games.keys()
]

PORTS = [11115, 11116, 11117, 11118, 11119, 11120]

server_game_settings = {
    "4": "0:1:0:1:25:5:5100:0:1:1:1:1:1:1:1:14:7:1:1:1:0:15:100:0:1:2021:25",
    "7": "30:1:0:0:10:0",
    "9": "1:1:1:1:30:10",
    "13": "0:5:1:4:0:5:2:0:1:1:1:1:1:1:1:14:7:1:1:1:0:15:100",
    "16": "0:5:1:2:1:5:1:20:5:20:0:1:1:1:1:1:1:1:1:14:7:1:1:1:0:15:100:1",
    "19": "0:5:1:4:1:5:0:45:2:1:1:5"
}


short_codes = {
    "Test": "Test",
    "Splish Splash": "S",
    "Relic Recovery": "",
    "Rover Ruckus": "RoRu",
    "Skystone": "SS",
    "Infinite Recharge": "IR",
    "Change Up": "CU",
    "Bot Royale": "",
    "Ultimate Goal": "UG",
    "Tipping Point": "TP",
    "Freight Frenzy": "FF",
    "Rapid React": "RR",
    "Spin Up": "SU",
    "Power Play": "PP",
    "Charged Up": "Charge",
    "Over Under": "OU",
    "Centerstage": "CS",
    "Crescendo": "CR",
    "High Stakes": "HS",
    "Into The Deep": "ITD",
    "Reefscape": "RS",
}

default_game_players = {
    "-1": 6,
    "0": 4,
    "1": 4,
    "2": 4,
    "3": 4,
    "4": 6,
    "5": 4,
    "6": 6,
    "7": 4,
    "8": 4,
    "9": 4,
    "10": 6,
    "11": 4,
    "12": 4,
    "13": 6,
    "14": 4,
    "15": 4,
    "16": 6,
    "17": 4,
    "18": 4,
    "19": 6,
}

server_restart_modes = {
    "3": 3,
    "4": 2,
}

game_logos = {
    "Skystone": "https://i.redd.it/iblf4hi92vt21.png",
    "Infinite Recharge": "https://upload.wikimedia.org/wikipedia/en/2/2b/Infinite_Recharge_Logo.png",
    "Rapid React": "https://upload.wikimedia.org/wikipedia/en/thumb/0/08/Rapid_React_Logo.svg/1200px-Rapid_React_Logo.svg.png",
    "Spin Up": "https://www.roboticseducation.org/app/uploads/2022/05/Spin-Up-Logo.png",
    "Charged Up": "https://upload.wikimedia.org/wikipedia/en/thumb/b/b7/Charged_Up_Logo.svg/1024px-Charged_Up_Logo.svg.png",
    "Centerstage": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQS-ziPQP3hKuX2qk5YBkLFIfv3wWNkNCf6QLBHaF9JPw&s",
    "Over Under": "https://roboticseducation.org/wp-content/uploads/2023/04/VRC-Over-Under.png",
    "Crescendo": "https://i.imgur.com/St3EoqP.png",
    "High Stakes": "https://i.imgur.com/jWu3NHB.png",
    "Power Play": "https://i.imgur.com/tuC6s0P.png",
    "Into The Deep": "https://i.imgur.com/YqT31M8.png",
    "Reefscape": "https://i.imgur.com/LlLfz4z.gif",
}
