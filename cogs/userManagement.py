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

        url = "https://secondrobotics.org/api/ranked/leaderboard/RB3v3/"
        leaderboard_data = await self.fetch_leaderboard_data(url)
        if not leaderboard_data:
            return

        # Build leaderboard lookup and collect all rank role names
        leaderboard = {entry['player_id']: entry['rank_name'] for entry in leaderboard_data}
        rank_role_names = {entry['rank_name'] for entry in leaderboard_data}

        # Ensure all rank roles exist
        rank_roles = {}
        for name in rank_role_names:
            role = discord.utils.get(guild.roles, name=name)
            if not role:
                role = await guild.create_role(name=name)
            rank_roles[name] = role

        # Assign correct rank roles to leaderboard players
        for player_id, rank_name in leaderboard.items():
            member = guild.get_member(player_id)
            if not member:
                continue

            correct_role = rank_roles[rank_name]
            roles_to_remove = [r for r in member.roles if r.name in rank_role_names and r != correct_role]

            if correct_role not in member.roles:
                await member.add_roles(correct_role)
            for role in roles_to_remove:
                await member.remove_roles(role)

        # Strip rank roles from anyone not on the leaderboard
        for role in rank_roles.values():
            for member in role.members:
                if member.id not in leaderboard:
                    await member.remove_roles(role)

        end_time = time.time()
        logger.info(f"Role update process completed in {end_time - start_time:.2f} seconds")

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
