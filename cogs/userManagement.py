import discord
from discord.ext import commands, tasks
from datetime import datetime
import aiohttp
import logging
from config import GUILD_ID, SRC_API_TOKEN
import time

logger = logging.getLogger('discord')
HEADER = {"x-api-key": SRC_API_TOKEN}

class UserManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.update_roles_task.start()

    @tasks.loop(hours=1)
    async def update_roles_task(self):
        await self.update_player_roles()

    @update_roles_task.before_loop
    async def before_update_roles_task(self):
        await self.bot.wait_until_ready()

    async def update_player_roles(self):
        start_time = time.time()
        logger.info("Starting role update process")
        
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            logger.error("Guild not found.")
            return

        url = "https://secondrobotics.org/api/ranked/leaderboard/RS3v3/"
        leaderboard_data = await self.fetch_leaderboard_data(url)
        if not leaderboard_data:
            return

        for player_data in leaderboard_data:
            discord_id = player_data['player_id']
            rank_name = player_data['rank_name']
            member = guild.get_member(discord_id)

            if not member:
                continue

            current_roles = set(member.roles)
            rank_role = discord.utils.get(guild.roles, name=rank_name)
            if not rank_role:
                rank_role = await guild.create_role(name=rank_name)

            roles_to_remove = [role for role in current_roles if role.name in [r['rank_name'] for r in leaderboard_data]]
            if rank_role not in current_roles:
                await member.add_roles(rank_role)
            for role in roles_to_remove:
                if role != rank_role:
                    await member.remove_roles(role)

        end_time = time.time()
        duration = end_time - start_time
        logger.info(f"Role update process completed in {duration:.2f} seconds")

    async def fetch_leaderboard_data(self, url):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=HEADER) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"Failed to fetch leaderboard data: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Error fetching leaderboard data: {str(e)}")
            return None

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UserManagement(bot))
