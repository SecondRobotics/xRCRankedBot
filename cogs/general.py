import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import requests
from dotenv import load_dotenv
import logging
import os
import threading
import aiohttp
from PIL import Image
import random
from io import BytesIO
from config import *

FALLBACK_AVATAR_URL = 'https://i0.wp.com/sbcf.fr/wp-content/uploads/2018/03/sbcf-default-avatar.png'  # Replace with your fallback avatar URL

logger = logging.getLogger('discord')

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
        logger.info(f"/playerinfo by {interaction.user.display_name}")
        if user is None:
            user = interaction.user
        user_id = user.id

        async with aiohttp.ClientSession(headers=HEADER, timeout=aiohttp.ClientTimeout(total=10)) as session:
            # Fetch player profile and avatar concurrently
            async with session.get(f'https://secondrobotics.org/api/ranked/player/{user_id}') as response:
                res = await response.json()

            if not res["exists"]:
                await interaction.followup.send(
                    "That player needs to register at <https://www.secondrobotics.org/login> first.",
                    ephemeral=True)
                return

            # Fetch avatar for embed color
            random_color = discord.Color.blue()
            try:
                async with session.get(res['avatar']) as response:
                    thumbnail_bytes = await response.read()
                thumbnail_image = Image.open(BytesIO(thumbnail_bytes))
                w, h = thumbnail_image.size
                random_pixel = thumbnail_image.getpixel((random.randint(0, w - 1), random.randint(0, h - 1)))
                random_color = discord.Color.from_rgb(*random_pixel[:3])
            except Exception as e:
                logger.error(f"Failed to fetch avatar: {e}")

            # Fetch all game stats concurrently
            async def fetch_game(game):
                try:
                    async with session.get(f'https://secondrobotics.org/api/ranked/{game}/player/{user_id}') as r:
                        return await r.json()
                except Exception as e:
                    logger.error(f"Failed to fetch game {game} for {user_id}: {e}")
                    return None

            game_results = await asyncio.gather(*[fetch_game(g) for g in short_codes_sorted])

        total_wins = total_losses = total_ties = total_points = 0
        best_elo = 0
        best_game = favorite_game = None
        favorite_game_matches = 0
        played_games = []

        for gamedata in game_results:
            if gamedata is None or "error" in gamedata or gamedata.get('matches_played', 0) == 0:
                continue

            total_wins += gamedata['matches_won']
            total_losses += gamedata['matches_lost']
            total_ties += gamedata['matches_drawn']
            total_points += gamedata['total_score']

            if gamedata['elo'] > best_elo:
                best_elo = gamedata['elo']
                best_game = gamedata['name']

            if gamedata['matches_played'] > favorite_game_matches:
                favorite_game = gamedata['name']
                favorite_game_matches = gamedata['matches_played']

            played_games.append(gamedata)

        # Top 12 by ELO
        top_games = sorted(played_games, key=lambda g: g['elo'], reverse=True)[:12]

        embed = discord.Embed(title="Player Information", color=random_color)
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=res.get('avatar', FALLBACK_AVATAR_URL))
        embed.add_field(
            name="Display Name",
            value=f"[{res['display_name']}](https://secondrobotics.org/user/{user_id})",
            inline=False
        )

        # Build compact game list split into two columns
        col1 = top_games[:6]
        col2 = top_games[6:]
        for col in [col1, col2]:
            if not col:
                break
            lines = []
            for g in col:
                mp = g['matches_played']
                wr = round((g['matches_won'] / mp) * 100) if mp > 0 else 0
                crown = " 👑" if wr > 60 else ""
                lines.append(f"**{g['name']}** `{round(g['elo'])}` {g['matches_won']}-{g['matches_lost']}-{g['matches_drawn']} ({wr}%{crown})")
            embed.add_field(name="Top Games by ELO" if col is col1 else "​", value="\n".join(lines), inline=True)

        total_matches = total_wins + total_losses + total_ties
        overall_wr = round((total_wins / total_matches) * 100, 1) if total_matches > 0 else 0
        overall_wr_str = f"{overall_wr}%" + (" 👑" if overall_wr > 60 else "")
        avg_elo = round(sum(g['elo'] for g in played_games) / len(played_games), 1) if played_games else 0

        summary = (
            f"Record: {total_wins}-{total_losses}-{total_ties} [{total_matches}]\n"
            f"Win Rate: {overall_wr_str}\n"
            f"Total Points: {total_points:,}\n"
            f"Avg ELO: {avg_elo} | Best: {best_game} ({round(best_elo, 1)})\n"
            f"Favorite: {favorite_game} ({favorite_game_matches} matches)"
        )
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
