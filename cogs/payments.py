import discord
from discord.ext import commands
from discord import app_commands
import stripe
import logging
from typing import Optional
from datetime import datetime

from config import STRIPE_API_KEY, STRIPE_PRICE_ID_BASIC, STRIPE_PRICE_ID_PREMIUM, SERVER_TIERS
from database import DatabaseManager

logger = logging.getLogger('discord')

# Initialize Stripe
stripe.api_key = STRIPE_API_KEY

class PaymentsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager()
    
    async def cog_load(self):
        await self.db.init_db()
        logger.info("Payments cog loaded and database initialized")
    
    async def cog_unload(self):
        await self.db.close()
    
    @app_commands.command(name='subscribe', description='Subscribe to a server access plan')
    @app_commands.describe(
        tier='Choose your subscription tier'
    )
    @app_commands.choices(tier=[
        app_commands.Choice(name='Basic (30 mins/day) - $4.99/month', value='basic'),
        app_commands.Choice(name='Premium (60 mins/day) - $9.99/month', value='premium')
    ])
    async def subscribe(self, interaction: discord.Interaction, tier: str):
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Check if user already has an active subscription
            existing_sub = await self.db.get_active_subscription(interaction.user.id)
            if existing_sub:
                await interaction.followup.send(
                    f"You already have an active {existing_sub.tier} subscription. "
                    "Please cancel it first using `/subscription cancel` before subscribing to a new plan.",
                    ephemeral=True
                )
                return
            
            # Get or create user in database
            user = await self.db.get_or_create_user(interaction.user.id)
            
            # Create or retrieve Stripe customer
            if user.stripe_customer_id:
                customer = stripe.Customer.retrieve(user.stripe_customer_id)
            else:
                customer = stripe.Customer.create(
                    metadata={
                        'discord_id': str(interaction.user.id),
                        'discord_username': str(interaction.user)
                    }
                )
                await self.db.update_user_stripe_customer(interaction.user.id, customer.id)
            
            # Determine price ID based on tier
            price_id = STRIPE_PRICE_ID_BASIC if tier == 'basic' else STRIPE_PRICE_ID_PREMIUM
            
            # Create checkout session
            checkout_session = stripe.checkout.Session.create(
                customer=customer.id,
                payment_method_types=['card'],
                line_items=[{
                    'price': price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url='https://discord.com/channels/@me',  # Redirect to Discord DMs
                cancel_url='https://discord.com/channels/@me',
                metadata={
                    'discord_id': str(interaction.user.id),
                    'tier': tier
                }
            )
            
            # Create embed with checkout link
            embed = discord.Embed(
                title="Subscribe to Server Access",
                description=f"Click the link below to subscribe to the **{tier.title()}** plan:",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Plan Details",
                value=f"**Tier:** {tier.title()}\n"
                      f"**Daily Server Time:** {SERVER_TIERS[tier]} minutes\n"
                      f"**Price:** {'$4.99' if tier == 'basic' else '$9.99'}/month",
                inline=False
            )
            embed.add_field(
                name="Payment Link",
                value=f"[Click here to complete payment]({checkout_session.url})",
                inline=False
            )
            embed.set_footer(text="Link expires in 24 hours")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error creating subscription checkout: {e}")
            await interaction.followup.send(
                "An error occurred while creating your subscription. Please try again later.",
                ephemeral=True
            )
    
    @app_commands.command(name='subscription', description='View your subscription status')
    async def subscription_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        subscription = await self.db.get_active_subscription(interaction.user.id)
        
        if not subscription:
            embed = discord.Embed(
                title="No Active Subscription",
                description="You don't have an active server access subscription.\n"
                           "Use `/subscribe` to get started!",
                color=discord.Color.red()
            )
        else:
            # Calculate remaining time today
            remaining_minutes = await self.db.get_remaining_minutes(interaction.user.id)
            daily_limit = SERVER_TIERS[subscription.tier]
            used_minutes = daily_limit - remaining_minutes
            
            embed = discord.Embed(
                title="Subscription Status",
                color=discord.Color.green()
            )
            embed.add_field(name="Tier", value=subscription.tier.title(), inline=True)
            embed.add_field(name="Status", value=subscription.status.title(), inline=True)
            embed.add_field(name="Daily Limit", value=f"{daily_limit} minutes", inline=True)
            embed.add_field(
                name="Today's Usage",
                value=f"{used_minutes:.1f} / {daily_limit} minutes",
                inline=True
            )
            embed.add_field(
                name="Remaining Today",
                value=f"{remaining_minutes:.1f} minutes",
                inline=True
            )
            embed.add_field(
                name="Renews",
                value=f"<t:{int(subscription.current_period_end.timestamp())}:R>",
                inline=True
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name='cancel_subscription', description='Cancel your active subscription')
    async def cancel_subscription(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        subscription = await self.db.get_active_subscription(interaction.user.id)
        
        if not subscription:
            await interaction.followup.send(
                "You don't have an active subscription to cancel.",
                ephemeral=True
            )
            return
        
        try:
            # Cancel the subscription in Stripe
            stripe_sub = stripe.Subscription.modify(
                subscription.stripe_subscription_id,
                cancel_at_period_end=True
            )
            
            embed = discord.Embed(
                title="Subscription Cancelled",
                description="Your subscription has been cancelled and will not renew.",
                color=discord.Color.orange()
            )
            embed.add_field(
                name="Access Until",
                value=f"<t:{int(subscription.current_period_end.timestamp())}:F>",
                inline=False
            )
            embed.set_footer(text="You can resubscribe at any time using /subscribe")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error cancelling subscription: {e}")
            await interaction.followup.send(
                "An error occurred while cancelling your subscription. Please try again later.",
                ephemeral=True
            )
    
    async def check_server_access(self, user_id: int) -> tuple[bool, Optional[float], Optional[str]]:
        """
        Check if a user has server access.
        Returns: (has_access, remaining_minutes, tier)
        """
        subscription = await self.db.get_active_subscription(user_id)
        
        if not subscription:
            return False, None, None
        
        remaining = await self.db.get_remaining_minutes(user_id)
        
        if remaining <= 0:
            return False, 0, subscription.tier
        
        return True, remaining, subscription.tier

async def setup(bot):
    await bot.add_cog(PaymentsCog(bot))