import asyncio
import discord
from discord import app_commands, ButtonStyle
from discord.ext import commands
from discord.ui import View, Button
import random
from datetime import datetime
import logging
from config import *

logger = logging.getLogger('discord')

class JoinHangoutButton(Button):
    def __init__(self, hangout_session):
        super().__init__(style=ButtonStyle.green, label="Join Hangout", emoji="🎮")
        self.hangout_session = hangout_session

    async def callback(self, interaction: discord.Interaction):
        # Check if user is a Member (has roles)
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)
            return
            
        if interaction.user in self.hangout_session.players:
            await interaction.response.send_message("You're already in this hangout!", ephemeral=True)
            return
        
        # Defer the response first to avoid conflicts
        await interaction.response.defer()
        
        # Add player to list
        self.hangout_session.players.append(interaction.user)
        
        # Assign hangout role
        try:
            await interaction.user.add_roles(self.hangout_session.hangout_role)
            logger.info(f"Added hangout role to {interaction.user.display_name}")
        except Exception as e:
            logger.error(f"Failed to assign hangout role: {e}")
        
        # Move player to hangout VC if they're in a voice channel
        if interaction.user.voice and self.hangout_session.hangout_vc:
            try:
                await interaction.user.move_to(self.hangout_session.hangout_vc)
            except Exception as e:
                logger.error(f"Failed to move player to hangout VC: {e}")
        
        await self.hangout_session.update_embed_deferred(interaction)

class LeaveHangoutButton(Button):
    def __init__(self, hangout_session):
        super().__init__(style=ButtonStyle.red, label="Leave Hangout", emoji="👋")
        self.hangout_session = hangout_session

    async def callback(self, interaction: discord.Interaction):
        # Check if user is a Member (has roles)
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)
            return
            
        if interaction.user not in self.hangout_session.players:
            await interaction.response.send_message("You're not in this hangout!", ephemeral=True)
            return
        
        # Defer the response first to avoid conflicts
        await interaction.response.defer()
        
        # Remove player from list
        self.hangout_session.players.remove(interaction.user)
        
        # Remove hangout role
        try:
            await interaction.user.remove_roles(self.hangout_session.hangout_role)
            logger.info(f"Removed hangout role from {interaction.user.display_name}")
        except Exception as e:
            logger.error(f"Failed to remove hangout role: {e}")
        
        # Remove from any team roles if in match
        if self.hangout_session.red_role:
            try:
                await interaction.user.remove_roles(self.hangout_session.red_role)
            except:
                pass
        if self.hangout_session.blue_role:
            try:
                await interaction.user.remove_roles(self.hangout_session.blue_role)
            except:
                pass
        
        await self.hangout_session.update_embed_deferred(interaction)

class StartMatchButton(Button):
    def __init__(self, hangout_session):
        super().__init__(style=ButtonStyle.primary, label="Start Match", emoji="🚀")
        self.hangout_session = hangout_session

    async def callback(self, interaction: discord.Interaction):
        # Check if user is a Member (has roles)
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)
            return
            
        # Check if user has permission to start matches
        if not any(role_id in [role.id for role in interaction.user.roles] for role_id in [EVENT_STAFF_ID, TRIAL_STAFF_ID]):
            await interaction.response.send_message("Only staff can start matches!", ephemeral=True)
            return
        
        if len(self.hangout_session.players) < 4:
            await interaction.response.send_message("Need at least 4 players to start a match!", ephemeral=True)
            return
        
        if self.hangout_session.match_in_progress:
            await interaction.response.send_message("A match is already in progress!", ephemeral=True)
            return
        
        await self.hangout_session.start_match(interaction)

class HangoutSession:
    def __init__(self, host, game_type, guild, cog):
        self.host = host
        self.game_type = game_type
        self.guild = guild
        self.cog = cog
        self.players = []
        self.created_at = datetime.now()
        self.message = None
        self.channel = None
        
        # Roles and VCs
        self.hangout_role = None
        self.hangout_vc = None
        self.red_role = None
        self.blue_role = None
        self.red_vc = None
        self.blue_vc = None
        
        # Match tracking
        self.match_in_progress = False
        self.current_match_teams = {"red": [], "blue": [], "spectators": []}
        self.matches_played = 0
        self.server_port = None
        self.server_password = None
        
        # Player statistics for this hangout session
        self.player_stats = {}  # player_id: {matches_sat_out, teammates, opponents, wins, losses, total_matches}
        
    async def create_hangout_resources(self):
        """Create the hangout role and voice channel"""
        try:
            # Create hangout role
            role_name = f"Hangout - {self.game_type}"
            self.hangout_role = await self.guild.create_role(
                name=role_name,
                color=discord.Color.green(),
                mentionable=True,
                reason=f"Hangout session for {self.game_type}"
            )
            logger.info(f"Created hangout role: {role_name}")
            
            # Create hangout VC
            category = discord.utils.get(self.guild.categories, id=CATEGORY_ID)
            vc_name = f"🎮 Hangout - {self.game_type}"
            self.hangout_vc = await self.guild.create_voice_channel(
                vc_name,
                category=category,
                reason=f"Hangout voice channel for {self.game_type}"
            )
            logger.info(f"Created hangout VC: {vc_name}")
            
            return True
        except Exception as e:
            logger.error(f"Failed to create hangout resources: {e}")
            return False
    
    async def cleanup_hangout_resources(self):
        """Clean up hangout role and voice channel"""
        # Remove roles from all players
        for player in self.players:
            try:
                if self.hangout_role:
                    await player.remove_roles(self.hangout_role)
                if self.red_role:
                    await player.remove_roles(self.red_role)
                if self.blue_role:
                    await player.remove_roles(self.blue_role)
            except Exception as e:
                logger.error(f"Failed to remove roles from {player.display_name}: {e}")
        
        # Delete resources
        try:
            if self.hangout_role:
                await self.hangout_role.delete(reason="Hangout session ended")
            if self.hangout_vc:
                await self.hangout_vc.delete(reason="Hangout session ended")
            await self.cleanup_match_resources()
        except Exception as e:
            logger.error(f"Failed to cleanup hangout resources: {e}")
    
    async def cleanup_match_resources(self):
        """Clean up match-specific roles and VCs"""
        try:
            if self.red_role:
                await self.red_role.delete(reason="Match ended")
                self.red_role = None
            if self.blue_role:
                await self.blue_role.delete(reason="Match ended")
                self.blue_role = None
            if self.red_vc:
                await self.red_vc.delete(reason="Match ended")
                self.red_vc = None
            if self.blue_vc:
                await self.blue_vc.delete(reason="Match ended")
                self.blue_vc = None
        except Exception as e:
            logger.error(f"Failed to cleanup match resources: {e}")
        
        # Stop server if running
        if self.server_port:
            try:
                server_actions = self.cog.bot.get_cog('ServerActions')
                if server_actions:
                    server_actions.stop_server_process(self.server_port)
                self.server_port = None
                self.server_password = None
            except Exception as e:
                logger.error(f"Failed to stop server: {e}")
    
    def init_player_stats(self, player_id):
        """Initialize stats for a new player"""
        if player_id not in self.player_stats:
            self.player_stats[player_id] = {
                "matches_sat_out": 0,
                "teammates": {},
                "opponents": {},
                "wins": 0,
                "losses": 0,
                "total_matches": 0
            }
    
    def calculate_matchmaking_priority(self, available_players):
        """Calculate priority for each player based on sitting out and relationship history"""
        priorities = {}
        
        for player in available_players:
            self.init_player_stats(player.id)
            stats = self.player_stats[player.id]
            
            # Sitting out priority (exponential weight)
            sitting_priority = 2 ** stats["matches_sat_out"]
            
            # Relationship diversity bonus (prefer players who haven't played with others much)
            relationship_penalty = 0
            for other_player in available_players:
                if other_player != player:
                    teammate_count = stats["teammates"].get(str(other_player.id), 0)
                    opponent_count = stats["opponents"].get(str(other_player.id), 0)
                    relationship_penalty += (teammate_count + opponent_count) * 0.1
            
            priorities[player.id] = sitting_priority - relationship_penalty
            
        return priorities
    
    def select_match_players(self):
        """Select players for the next match using matchmaking algorithm"""
        if len(self.players) <= 6:
            # Everyone plays if 6 or fewer players
            return self.players, []
        
        # Calculate priorities
        priorities = self.calculate_matchmaking_priority(self.players)
        
        # Sort by priority (highest first)
        sorted_players = sorted(self.players, key=lambda p: priorities[p.id], reverse=True)
        
        # Select top 6 players
        match_players = sorted_players[:6]
        spectators = sorted_players[6:]
        
        return match_players, spectators
    
    def assign_teams(self, match_players):
        """Assign players to red and blue teams with balanced relationships"""
        if len(match_players) <= 4:
            # 2v2 format
            team_size = 2
        else:
            # 3v3 format
            team_size = 3
        
        # Use sophisticated team balancing based on relationship history
        best_assignment = self.find_optimal_team_assignment(match_players, team_size)
        
        red_team = best_assignment["red"]
        blue_team = best_assignment["blue"]
        spectators = best_assignment["spectators"]
        
        return red_team, blue_team, spectators
    
    def find_optimal_team_assignment(self, match_players, team_size):
        """Find the optimal team assignment that maximizes relationship diversity"""
        from itertools import combinations
        
        if len(match_players) < team_size * 2:
            # Not enough players for full teams, use simple assignment
            shuffled = match_players.copy()
            random.shuffle(shuffled)
            return {
                "red": shuffled[:team_size],
                "blue": shuffled[team_size:team_size*2],
                "spectators": shuffled[team_size*2:]
            }
        
        # Generate all possible team combinations
        all_red_combinations = list(combinations(match_players, team_size))
        best_score = float('-inf')
        best_assignment = None
        
        for red_team in all_red_combinations:
            remaining_players = [p for p in match_players if p not in red_team]
            
            if len(remaining_players) >= team_size:
                # Generate blue team combinations from remaining players
                blue_combinations = list(combinations(remaining_players, team_size))
                
                for blue_team in blue_combinations:
                    spectators = [p for p in remaining_players if p not in blue_team]
                    
                    # Calculate relationship diversity score for this assignment
                    score = self.calculate_team_balance_score(red_team, blue_team, spectators)
                    
                    if score > best_score:
                        best_score = score
                        best_assignment = {
                            "red": list(red_team),
                            "blue": list(blue_team),
                            "spectators": spectators
                        }
        
        # If no good assignment found, fall back to random
        if best_assignment is None:
            shuffled = match_players.copy()
            random.shuffle(shuffled)
            best_assignment = {
                "red": shuffled[:team_size],
                "blue": shuffled[team_size:team_size*2],
                "spectators": shuffled[team_size*2:]
            }
        
        return best_assignment
    
    def calculate_team_balance_score(self, red_team, blue_team, spectators):
        """Calculate a score for how well-balanced this team assignment is"""
        score = 0
        
        # 1. Minimize frequent teammates playing together again
        score += self.calculate_teammate_diversity_score(red_team)
        score += self.calculate_teammate_diversity_score(blue_team)
        
        # 2. Maximize variety in opponents (prefer players who haven't faced each other much)
        score += self.calculate_opponent_variety_score(red_team, blue_team)
        
        # 3. Bonus for including players who sat out recently
        score += self.calculate_sitting_balance_score(red_team + blue_team, spectators)
        
        return score
    
    def get_relationship_stats(self, all_players):
        """Get min, max, and average relationship counts for dynamic scaling"""
        teammate_counts = []
        opponent_counts = []
        sitting_counts = []
        
        for player in all_players:
            self.init_player_stats(player.id)
            stats = self.player_stats[player.id]
            
            # Collect all teammate relationship counts
            teammate_counts.extend(stats["teammates"].values())
            
            # Collect all opponent relationship counts  
            opponent_counts.extend(stats["opponents"].values())
            
            # Collect sitting counts
            sitting_counts.append(stats["matches_sat_out"])
        
        return {
            "teammate": {
                "min": min(teammate_counts) if teammate_counts else 0,
                "max": max(teammate_counts) if teammate_counts else 0,
                "avg": sum(teammate_counts) / len(teammate_counts) if teammate_counts else 0
            },
            "opponent": {
                "min": min(opponent_counts) if opponent_counts else 0,
                "max": max(opponent_counts) if opponent_counts else 0,
                "avg": sum(opponent_counts) / len(opponent_counts) if opponent_counts else 0
            },
            "sitting": {
                "min": min(sitting_counts) if sitting_counts else 0,
                "max": max(sitting_counts) if sitting_counts else 0,
                "avg": sum(sitting_counts) / len(sitting_counts) if sitting_counts else 0
            }
        }
    
    def calculate_teammate_diversity_score(self, team):
        """Calculate score based on teammate diversity using dynamic scaling"""
        if len(team) <= 1:
            return 0
        
        all_players = self.players
        stats_ranges = self.get_relationship_stats(all_players)
        
        diversity_score = 0
        
        for i, player1 in enumerate(team):
            self.init_player_stats(player1.id)
            stats1 = self.player_stats[player1.id]
            
            for j, player2 in enumerate(team):
                if i >= j:  # Avoid double counting
                    continue
                    
                # Get how many times these players have been teammates
                teammate_count = stats1["teammates"].get(str(player2.id), 0)
                
                # Dynamic scoring based on relative frequency
                if stats_ranges["teammate"]["max"] == 0:
                    # No teammate history yet, all pairings are equal
                    diversity_score += 1
                else:
                    # Score inversely proportional to how common this pairing is
                    # Range from 1.0 (most common) to 2.0 (never paired)
                    relative_frequency = teammate_count / stats_ranges["teammate"]["max"]
                    diversity_score += 2.0 - relative_frequency
        
        return diversity_score
    
    def calculate_opponent_variety_score(self, red_team, blue_team):
        """Calculate score based on opponent variety using dynamic scaling"""
        all_players = self.players
        stats_ranges = self.get_relationship_stats(all_players)
        
        variety_score = 0
        
        for red_player in red_team:
            self.init_player_stats(red_player.id)
            red_stats = self.player_stats[red_player.id]
            
            for blue_player in blue_team:
                # Get how many times these players have been opponents
                opponent_count = red_stats["opponents"].get(str(blue_player.id), 0)
                
                # Dynamic scoring based on relative frequency
                if stats_ranges["opponent"]["max"] == 0:
                    # No opponent history yet, all matchups are equal
                    variety_score += 1
                else:
                    # Score inversely proportional to how common this matchup is
                    # Range from 0.5 (most common) to 1.5 (never faced)
                    relative_frequency = opponent_count / stats_ranges["opponent"]["max"]
                    variety_score += 1.5 - relative_frequency
        
        return variety_score
    
    def calculate_sitting_balance_score(self, playing_players, spectators):
        """Calculate score that favors including players who sat out recently using dynamic scaling"""
        all_players = self.players
        stats_ranges = self.get_relationship_stats(all_players)
        
        balance_score = 0
        
        # If no sitting variation exists, treat all players equally
        if stats_ranges["sitting"]["max"] == stats_ranges["sitting"]["min"]:
            return 0
        
        sitting_range = stats_ranges["sitting"]["max"] - stats_ranges["sitting"]["min"]
        
        # Bonus for including players who sat out (scaled to sitting range)
        for player in playing_players:
            self.init_player_stats(player.id)
            sits = self.player_stats[player.id]["matches_sat_out"]
            
            # Players who sat out more get exponentially higher priority
            if sitting_range > 0:
                relative_sits = (sits - stats_ranges["sitting"]["min"]) / sitting_range
                balance_score += relative_sits ** 2 * 10  # Quadratic scaling for sitting priority
        
        # Penalty for making players sit who haven't sat much (relative to others)
        for player in spectators:
            self.init_player_stats(player.id)
            sits = self.player_stats[player.id]["matches_sat_out"]
            
            if sitting_range > 0:
                relative_sits = (sits - stats_ranges["sitting"]["min"]) / sitting_range
                # Higher penalty for making players sit who have sat less relative to others
                balance_score -= (1.0 - relative_sits) * 3
        
        return balance_score
    
    async def start_match(self, interaction):
        """Start a new match with selected players"""
        await interaction.response.defer()
        
        # Select players for match
        match_players, session_spectators = self.select_match_players()
        red_team, blue_team, match_spectators = self.assign_teams(match_players)
        
        all_spectators = session_spectators + match_spectators
        
        self.current_match_teams = {
            "red": red_team,
            "blue": blue_team, 
            "spectators": all_spectators
        }
        
        try:
            # Create team roles
            self.red_role = await self.guild.create_role(
                name=f"Hangout Red",
                color=discord.Color.red(),
                mentionable=True,
                reason=f"Red team for hangout match"
            )
            
            self.blue_role = await self.guild.create_role(
                name=f"Hangout Blue", 
                color=discord.Color.blue(),
                mentionable=True,
                reason=f"Blue team for hangout match"
            )
            
            # Create team VCs with proper permissions
            category = discord.utils.get(self.guild.categories, id=CATEGORY_ID)
            staff_role = discord.utils.get(self.guild.roles, id=EVENT_STAFF_ID)
            bots_role = discord.utils.get(self.guild.roles, id=BOTS_ROLE_ID)
            
            red_overwrites = {
                self.guild.default_role: discord.PermissionOverwrite(connect=False),
                self.red_role: discord.PermissionOverwrite(connect=True),
                staff_role: discord.PermissionOverwrite(connect=True),
                bots_role: discord.PermissionOverwrite(connect=True)
            }
            
            blue_overwrites = {
                self.guild.default_role: discord.PermissionOverwrite(connect=False),
                self.blue_role: discord.PermissionOverwrite(connect=True),
                staff_role: discord.PermissionOverwrite(connect=True),
                bots_role: discord.PermissionOverwrite(connect=True)
            }
            
            self.red_vc = await self.guild.create_voice_channel(
                f"🟥 Hangout Red",
                category=category,
                overwrites=red_overwrites
            )
            
            self.blue_vc = await self.guild.create_voice_channel(
                f"🟦 Hangout Blue",
                category=category,
                overwrites=blue_overwrites
            )
            
            # Assign team roles and move players
            move_tasks = []
            for player in red_team:
                await player.add_roles(self.red_role)
                if player.voice:
                    move_tasks.append(player.move_to(self.red_vc))
                    
            for player in blue_team:
                await player.add_roles(self.blue_role)
                if player.voice:
                    move_tasks.append(player.move_to(self.blue_vc))
            
            # Execute all moves in parallel with better error handling
            if move_tasks:
                results = await asyncio.gather(*move_tasks, return_exceptions=True)
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(f"Failed to move player to team VC: {result}")
            
            # Start server
            game_id = server_games[self.game_type]
            password = str(random.randint(100, 999))
            min_players = default_game_players.get(game_id, 4)
            
            server_actions = self.cog.bot.get_cog('ServerActions')
            if server_actions:
                message, port = server_actions.start_server_process(
                    game_id, f"Hangout{self.game_type.replace(' ', '')}", password, 
                    min_players=min_players, admin=RANKED_ADMIN_USERNAME
                )
                if port != -1:
                    self.server_port = port
                    self.server_password = password
                    logger.info(f"Started hangout server on port {port}")
                else:
                    logger.warning(f"Failed to start hangout server: {message}")
            
            self.match_in_progress = True
            
            # Create match start embed
            embed = discord.Embed(
                title=f"🚀 Match #{self.matches_played + 1} Starting!",
                description=f"**{self.game_type}** - {'2v2' if len(red_team) == 2 else '3v3'} Format",
                color=0xff9900,
                timestamp=datetime.now()
            )
            
            red_field = "\n".join([f"🟥 {player.display_name}" for player in red_team])
            blue_field = "\n".join([f"🟦 {player.display_name}" for player in blue_team])
            
            embed.add_field(name="Red Team", value=red_field, inline=True)
            embed.add_field(name="Blue Team", value=blue_field, inline=True)
            
            if all_spectators:
                spectator_field = "\n".join([f"👁️ {player.display_name}" for player in all_spectators])
                embed.add_field(name="Spectators", value=spectator_field, inline=False)
            
            if self.server_port and self.server_password:
                embed.add_field(
                    name="Server Info",
                    value=f"**Server:** Hangout{self.game_type.replace(' ', '')}\n**Password:** {self.server_password}\n**Port:** {self.server_port}",
                    inline=False
                )
            
            embed.set_footer(text="Teams have been moved to their voice channels. Good luck!")
            
            await interaction.followup.send(
                f"{self.red_role.mention} {self.blue_role.mention}",
                embed=embed
            )
            
            # Update main hangout message
            await self.update_main_embed()
            
        except Exception as e:
            logger.error(f"Failed to start match: {e}")
            await interaction.followup.send("Failed to start match. Please try again.", ephemeral=True)
    
    def create_embed(self):
        """Create the main hangout embed"""
        embed = discord.Embed(
            title=f"🎮 Game Hangout - {self.game_type}",
            description=f"Casual hangout session for **{self.game_type}**",
            color=0x00ff00 if not self.match_in_progress else 0xff9900,
            timestamp=self.created_at
        )
        
        embed.add_field(name="Host", value=self.host.display_name, inline=True)
        embed.add_field(name="Game", value=self.game_type, inline=True)
        embed.add_field(name="Players", value=str(len(self.players)), inline=True)
        embed.add_field(name="Matches Played", value=str(self.matches_played), inline=True)
        
        if self.hangout_role:
            embed.add_field(name="Hangout Role", value=self.hangout_role.mention, inline=True)
        
        if self.hangout_vc:
            embed.add_field(name="Voice Channel", value=self.hangout_vc.mention, inline=True)
        
        # Player list
        if self.players:
            player_list = "\n".join([f"• {player.display_name}" for player in self.players])
            if len(player_list) > 1024:
                player_list = player_list[:1021] + "..."
            
            embed.add_field(
                name=f"Player List ({len(self.players)})",
                value=player_list,
                inline=False
            )
        else:
            embed.add_field(
                name="Player List",
                value="No players yet - be the first to join!",
                inline=False
            )
        
        # Match status
        if self.match_in_progress:
            embed.add_field(
                name="Current Match",
                value=f"🟥 **Red:** {', '.join([p.display_name for p in self.current_match_teams['red']])}\n"
                      f"🟦 **Blue:** {', '.join([p.display_name for p in self.current_match_teams['blue']])}",
                inline=False
            )
            embed.set_footer(text="Match in progress - Use /hangout_submit to submit scores")
        else:
            embed.set_footer(text="Use the buttons to join/leave • Staff can start matches with 4+ players")
        
        return embed
    
    def create_view(self):
        """Create the interactive view with buttons"""
        view = View(timeout=7200)  # 2 hour timeout to prevent memory leaks
        view.add_item(JoinHangoutButton(self))
        view.add_item(LeaveHangoutButton(self))
        if not self.match_in_progress and len(self.players) >= 4:
            view.add_item(StartMatchButton(self))
        return view
    
    async def update_embed(self, interaction):
        """Update the main hangout embed"""
        embed = self.create_embed()
        view = self.create_view()
        await interaction.response.edit_message(embed=embed, view=view)
        
    async def update_embed_deferred(self, interaction):
        """Update the main hangout embed after deferring response"""
        embed = self.create_embed()
        view = self.create_view()
        await interaction.edit_original_response(embed=embed, view=view)
        
    async def update_main_embed(self):
        """Update the main hangout embed without interaction"""
        if self.message:
            embed = self.create_embed()
            view = self.create_view()
            try:
                await self.message.edit(embed=embed, view=view)
            except Exception as e:
                logger.error(f"Failed to update main embed: {e}")
    
    async def submit_match_result(self, red_score, blue_score):
        """Submit match result and update stats"""
        if not self.match_in_progress:
            return False, "No match is currently in progress!"
        
        red_team = self.current_match_teams["red"]
        blue_team = self.current_match_teams["blue"]
        spectators = self.current_match_teams["spectators"]
        
        # Determine winner
        red_wins = red_score > blue_score
        
        # Update player stats
        for player in red_team + blue_team:
            self.init_player_stats(player.id)
            stats = self.player_stats[player.id]
            
            # Update win/loss
            if player in red_team:
                if red_wins:
                    stats["wins"] += 1
                else:
                    stats["losses"] += 1
            else:  # blue team
                if not red_wins:
                    stats["wins"] += 1
                else:
                    stats["losses"] += 1
            
            stats["total_matches"] += 1
            stats["matches_sat_out"] = 0  # Reset sitting counter
            
            # Update teammate/opponent relationships
            for other_player in red_team + blue_team:
                if other_player != player:
                    other_id = str(other_player.id)
                    
                    if (player in red_team and other_player in red_team) or \
                       (player in blue_team and other_player in blue_team):
                        # Teammate
                        stats["teammates"][other_id] = stats["teammates"].get(other_id, 0) + 1
                    else:
                        # Opponent
                        stats["opponents"][other_id] = stats["opponents"].get(other_id, 0) + 1
        
        # Update sitting counters for spectators
        for player in spectators:
            self.init_player_stats(player.id)
            self.player_stats[player.id]["matches_sat_out"] += 1
        
        # Move players back to main VC
        move_tasks = []
        for player in red_team + blue_team:
            if player.voice and self.hangout_vc:
                move_tasks.append(player.move_to(self.hangout_vc))
        
        if move_tasks:
            results = await asyncio.gather(*move_tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Failed to move player back to hangout VC: {result}")
        
        # Clean up match resources
        await self.cleanup_match_resources()
        
        # Update counters
        self.matches_played += 1
        self.match_in_progress = False
        self.current_match_teams = {"red": [], "blue": [], "spectators": []}
        
        # Update main embed
        await self.update_main_embed()
        
        winner_team = "Red" if red_wins else "Blue"
        return True, f"🏆 {winner_team} team wins {red_score}-{blue_score}! Match #{self.matches_played} complete."
    
    def generate_final_stats(self):
        """Generate final statistics embed for the hangout session"""
        embed = discord.Embed(
            title=f"📊 Hangout Session Complete - {self.game_type}",
            description=f"**Total Matches:** {self.matches_played}",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        
        if not self.player_stats:
            embed.add_field(name="No matches played", value="No statistics to display", inline=False)
            return embed
        
        # Sort players by matches played, then by win rate
        sorted_players = []
        for player_id, stats in self.player_stats.items():
            player = self.guild.get_member(int(player_id))
            if player and stats["total_matches"] > 0:
                win_rate = (stats["wins"] / stats["total_matches"]) * 100
                sorted_players.append((player, stats, win_rate))
        
        sorted_players.sort(key=lambda x: (x[1]["total_matches"], x[2]), reverse=True)
        
        # Player stats
        stats_text = ""
        for player, stats, win_rate in sorted_players:
            stats_text += f"• **{player.display_name}**: {stats['wins']}W-{stats['losses']}L ({win_rate:.1f}%)\n"
        
        if stats_text:
            embed.add_field(name="Player Stats", value=stats_text[:1024], inline=False)
        
        # Fun stats
        if sorted_players:
            most_matches = max(sorted_players, key=lambda x: x[1]["total_matches"])
            highest_wr = max([p for p in sorted_players if p[1]["total_matches"] >= 2], 
                           key=lambda x: x[2], default=None)
            
            fun_stats = f"🏆 Most matches: **{most_matches[0].display_name}** ({most_matches[1]['total_matches']})\n"
            if highest_wr:
                fun_stats += f"🎯 Highest win rate: **{highest_wr[0].display_name}** ({highest_wr[2]:.1f}%)"
            
            embed.add_field(name="Session Highlights", value=fun_stats, inline=False)
        
        embed.set_footer(text=f"Session lasted from {self.created_at.strftime('%H:%M')} to {datetime.now().strftime('%H:%M')}")
        return embed

class GameHangout(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_hangouts = {}  # staff_user_id: HangoutSession
    
    @app_commands.command(description="Create a casual game hangout session (Staff Only)")
    @app_commands.describe(game="The game to play in the hangout")
    @app_commands.choices(game=server_games_choices)
    async def hangout_create(self, interaction: discord.Interaction, game: str):
        # Check if user is a Member and has staff permissions
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)
            return
            
        if not any(role_id in [role.id for role in interaction.user.roles] for role_id in [EVENT_STAFF_ID, TRIAL_STAFF_ID]):
            await interaction.response.send_message("Only staff members can create hangout sessions!", ephemeral=True)
            return
        
        # Check if staff already has an active hangout
        if interaction.user.id in self.active_hangouts:
            await interaction.response.send_message("You already have an active hangout session! End it first with `/hangout_end`", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        # Get game name from the choice value
        game_name = next((name for name, value in server_games.items() if value == game), "Unknown Game")
        
        # Create hangout session
        session = HangoutSession(interaction.user, game_name, interaction.guild, self)
        
        # Create hangout resources
        if not await session.create_hangout_resources():
            await interaction.followup.send("Failed to create hangout resources. Please try again.", ephemeral=True)
            return
        
        # Store the session
        self.active_hangouts[interaction.user.id] = session
        
        # Create and send the hangout message
        embed = session.create_embed()
        view = session.create_view()
        
        await interaction.followup.send(embed=embed, view=view)
        
        # Store message reference for updates
        message = await interaction.original_response()
        session.message = message
        session.channel = interaction.channel
        
        logger.info(f"Hangout session created by {interaction.user.display_name} for {game_name}")
    
    @app_commands.command(description="End your active hangout session (Staff Only)")
    async def hangout_end(self, interaction: discord.Interaction):
        # Check if user is a Member and has staff permissions
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)
            return
            
        if not any(role_id in [role.id for role in interaction.user.roles] for role_id in [EVENT_STAFF_ID, TRIAL_STAFF_ID]):
            await interaction.response.send_message("Only staff members can end hangout sessions!", ephemeral=True)
            return
        
        # Check if staff has an active hangout
        if interaction.user.id not in self.active_hangouts:
            await interaction.response.send_message("You don't have an active hangout session!", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        session = self.active_hangouts[interaction.user.id]
        
        # Generate final stats
        final_stats_embed = session.generate_final_stats()
        
        # Clean up all resources
        await session.cleanup_hangout_resources()
        
        # Remove from active hangouts
        del self.active_hangouts[interaction.user.id]
        
        await interaction.followup.send(embed=final_stats_embed)
        logger.info(f"Hangout session ended by {interaction.user.display_name}")
    
    @app_commands.command(description="Submit match result for current hangout match (Staff Only)")
    @app_commands.describe(
        red_score="Score for red team",
        blue_score="Score for blue team"
    )
    async def hangout_submit(self, interaction: discord.Interaction, red_score: int, blue_score: int):
        # Check if user is a Member
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)
            return
            
        # Check if user has staff permissions or is in the match
        staff_permission = any(role_id in [role.id for role in interaction.user.roles] for role_id in [EVENT_STAFF_ID, TRIAL_STAFF_ID])
        
        # Find the hangout session this user is involved with
        user_session = None
        for session in self.active_hangouts.values():
            if interaction.user in session.players or staff_permission:
                if session.match_in_progress:
                    # Check if user is in the current match or is staff
                    in_current_match = (interaction.user in session.current_match_teams["red"] or 
                                      interaction.user in session.current_match_teams["blue"])
                    if in_current_match or staff_permission:
                        user_session = session
                        break
        
        if not user_session:
            await interaction.response.send_message("You're not eligible to submit scores for any active match!", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        success, message = await user_session.submit_match_result(red_score, blue_score)
        
        if success:
            # Create result embed
            embed = discord.Embed(
                title=f"🏆 Match Result Submitted",
                description=message,
                color=0x00ff00,
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="Final Score",
                value=f"🟥 Red: {red_score}\n🟦 Blue: {blue_score}",
                inline=True
            )
            
            embed.add_field(
                name="Match Info",
                value=f"**Game:** {user_session.game_type}\n**Match #:** {user_session.matches_played}",
                inline=True
            )
            
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)
    
    @app_commands.command(description="Skip current hangout match due to technical issues (Staff Only)")
    @app_commands.describe(reason="Reason for skipping the match")
    async def hangout_skip_match(self, interaction: discord.Interaction, reason: str = "Technical issues"):
        # Check if user is a Member and has staff permissions
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)
            return
            
        if not any(role_id in [role.id for role in interaction.user.roles] for role_id in [EVENT_STAFF_ID, TRIAL_STAFF_ID]):
            await interaction.response.send_message("Only staff can skip matches!", ephemeral=True)
            return
        
        # Find active hangout with match in progress
        active_session = None
        for session in self.active_hangouts.values():
            if session.match_in_progress:
                active_session = session
                break
        
        if not active_session:
            await interaction.response.send_message("No match is currently in progress!", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        # Move players back to main VC
        move_tasks = []
        for player in active_session.current_match_teams["red"] + active_session.current_match_teams["blue"]:
            if player.voice and active_session.hangout_vc:
                move_tasks.append(player.move_to(active_session.hangout_vc))
        
        if move_tasks:
            results = await asyncio.gather(*move_tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Failed to move player back to hangout VC during skip: {result}")
        
        # Clean up match resources but don't update stats
        await active_session.cleanup_match_resources()
        active_session.match_in_progress = False
        active_session.current_match_teams = {"red": [], "blue": [], "spectators": []}
        
        # Update main embed
        await active_session.update_main_embed()
        
        embed = discord.Embed(
            title="⚠️ Match Skipped",
            description=f"**Reason:** {reason}",
            color=0xff9900,
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="Game", 
            value=active_session.game_type,
            inline=True
        )
        
        embed.add_field(
            name="Players Returned",
            value="All players moved back to main hangout VC",
            inline=False
        )
        
        await interaction.followup.send(embed=embed)
        logger.info(f"Match skipped by {interaction.user.display_name}: {reason}")
    
    @app_commands.command(description="List all active hangout sessions")
    async def hangout_list(self, interaction: discord.Interaction):
        if not self.active_hangouts:
            embed = discord.Embed(
                title="🎮 Active Hangouts",
                description="No active hangout sessions right now!",
                color=0x808080
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🎮 Active Hangout Sessions",
            color=0x00ff00
        )
        
        for staff_id, session in self.active_hangouts.items():
            status = "🔄 Match in progress" if session.match_in_progress else "💬 In lobby"
            
            embed.add_field(
                name=f"{session.game_type}",
                value=f"**Host:** {session.host.display_name}\n"
                      f"**Players:** {len(session.players)}\n"
                      f"**Matches:** {session.matches_played}\n"
                      f"**Status:** {status}",
                inline=True
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(GameHangout(bot))