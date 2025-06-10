import asyncio
import logging
from aiohttp import web
import stripe
from datetime import datetime

from config import STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET
from database import DatabaseManager

logger = logging.getLogger('stripe_webhook')
stripe.api_key = STRIPE_API_KEY

class StripeWebhookServer:
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager()
        self.app = web.Application()
        self.app.router.add_post('/stripe/webhook', self.handle_webhook)
        
    async def start(self, port=8000):
        """Start the webhook server"""
        await self.db.init_db()
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', port)
        await site.start()
        logger.info(f"Stripe webhook server started on port {port}")
        
    async def handle_webhook(self, request):
        """Handle incoming Stripe webhooks"""
        payload = await request.read()
        sig_header = request.headers.get('Stripe-Signature')
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            logger.error("Invalid webhook payload")
            return web.Response(status=400)
        except stripe.error.SignatureVerificationError:
            logger.error("Invalid webhook signature")
            return web.Response(status=400)
        
        # Handle different event types
        if event['type'] == 'checkout.session.completed':
            await self._handle_checkout_completed(event['data']['object'])
        elif event['type'] == 'customer.subscription.updated':
            await self._handle_subscription_updated(event['data']['object'])
        elif event['type'] == 'customer.subscription.deleted':
            await self._handle_subscription_deleted(event['data']['object'])
        elif event['type'] == 'invoice.payment_succeeded':
            await self._handle_payment_succeeded(event['data']['object'])
        
        return web.Response(text='OK', status=200)
    
    async def _handle_checkout_completed(self, session):
        """Handle successful checkout session"""
        logger.info(f"Checkout completed for customer {session['customer']}")
        
        # Get subscription details
        subscription = stripe.Subscription.retrieve(session['subscription'])
        discord_id = int(session['metadata']['discord_id'])
        tier = session['metadata']['tier']
        
        # Create subscription in database
        await self.db.create_subscription(
            user_id=discord_id,
            stripe_subscription_id=subscription.id,
            stripe_price_id=subscription['items']['data'][0]['price']['id'],
            tier=tier,
            current_period_end=datetime.fromtimestamp(subscription['current_period_end'])
        )
        
        # Grant Discord role
        await self._grant_subscription_role(discord_id, tier)
        
        # Send confirmation DM
        try:
            user = await self.bot.fetch_user(discord_id)
            await user.send(
                f"✅ Your {tier} subscription is now active! You have {SERVER_TIERS[tier]} minutes of server time per day.\n"
                f"Use `/subscription` to check your status."
            )
        except Exception as e:
            logger.error(f"Failed to send confirmation DM: {e}")
    
    async def _handle_subscription_updated(self, subscription):
        """Handle subscription updates"""
        await self.db.update_subscription_status(
            subscription.id,
            subscription['status']
        )
        
        if subscription['status'] != 'active':
            # Get user from metadata
            customer = stripe.Customer.retrieve(subscription['customer'])
            discord_id = int(customer['metadata'].get('discord_id', 0))
            if discord_id:
                await self._revoke_subscription_role(discord_id)
    
    async def _handle_subscription_deleted(self, subscription):
        """Handle subscription cancellation/deletion"""
        await self.db.update_subscription_status(
            subscription.id,
            'cancelled'
        )
        
        # Revoke Discord role
        customer = stripe.Customer.retrieve(subscription['customer'])
        discord_id = int(customer['metadata'].get('discord_id', 0))
        if discord_id:
            await self._revoke_subscription_role(discord_id)
    
    async def _handle_payment_succeeded(self, invoice):
        """Track successful payments"""
        if invoice['billing_reason'] == 'subscription_create':
            return  # Skip initial payment (handled by checkout.completed)
        
        customer = stripe.Customer.retrieve(invoice['customer'])
        discord_id = int(customer['metadata'].get('discord_id', 0))
        
        if discord_id:
            await self.db.create_payment(
                user_id=discord_id,
                stripe_payment_intent_id=invoice['payment_intent'],
                amount=invoice['amount_paid'],
                currency=invoice['currency']
            )
    
    async def _grant_subscription_role(self, discord_id: int, tier: str):
        """Grant subscription role to user"""
        try:
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                return
            
            member = guild.get_member(discord_id)
            if not member:
                return
            
            # Create/get subscription roles
            role_name = f"Subscriber {tier.title()}"
            role = discord.utils.get(guild.roles, name=role_name)
            
            if not role:
                role = await guild.create_role(
                    name=role_name,
                    color=discord.Color.gold() if tier == 'premium' else discord.Color.green(),
                    reason="Subscription role"
                )
            
            await member.add_roles(role, reason="Subscription activated")
            logger.info(f"Granted {role_name} role to {member}")
            
        except Exception as e:
            logger.error(f"Failed to grant subscription role: {e}")
    
    async def _revoke_subscription_role(self, discord_id: int):
        """Revoke subscription roles from user"""
        try:
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                return
            
            member = guild.get_member(discord_id)
            if not member:
                return
            
            # Remove all subscription roles
            for role in member.roles:
                if role.name.startswith("Subscriber"):
                    await member.remove_roles(role, reason="Subscription ended")
                    logger.info(f"Revoked {role.name} role from {member}")
            
        except Exception as e:
            logger.error(f"Failed to revoke subscription role: {e}")


# Import required for role management
import discord
from config import GUILD_ID, SERVER_TIERS