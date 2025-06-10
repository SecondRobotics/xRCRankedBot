import asyncio
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy import and_, func
from typing import Optional, List
import logging

from .models import Base, User, Subscription, Payment, ServerUsage
from config import DATABASE_URL

logger = logging.getLogger('discord')

class DatabaseManager:
    def __init__(self):
        self.engine = create_async_engine(DATABASE_URL, echo=False)
        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
    
    async def init_db(self):
        """Initialize database tables"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized")
    
    async def close(self):
        """Close database connection"""
        await self.engine.dispose()
    
    # User management
    async def get_or_create_user(self, discord_id: int) -> User:
        async with self.async_session() as session:
            result = await session.execute(
                select(User).where(User.discord_id == discord_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                user = User(discord_id=discord_id)
                session.add(user)
                await session.commit()
                await session.refresh(user)
            
            return user
    
    async def update_user_stripe_customer(self, discord_id: int, stripe_customer_id: str):
        async with self.async_session() as session:
            user = await self.get_or_create_user(discord_id)
            result = await session.execute(
                select(User).where(User.discord_id == discord_id)
            )
            user = result.scalar_one()
            user.stripe_customer_id = stripe_customer_id
            await session.commit()
    
    # Subscription management
    async def create_subscription(self, user_id: int, stripe_subscription_id: str, 
                                stripe_price_id: str, tier: str, current_period_end: datetime) -> Subscription:
        async with self.async_session() as session:
            subscription = Subscription(
                user_id=user_id,
                stripe_subscription_id=stripe_subscription_id,
                stripe_price_id=stripe_price_id,
                status='active',
                tier=tier,
                current_period_end=current_period_end
            )
            session.add(subscription)
            await session.commit()
            return subscription
    
    async def get_active_subscription(self, discord_id: int) -> Optional[Subscription]:
        async with self.async_session() as session:
            result = await session.execute(
                select(Subscription).where(
                    and_(
                        Subscription.user_id == discord_id,
                        Subscription.status == 'active'
                    )
                )
            )
            return result.scalar_one_or_none()
    
    async def update_subscription_status(self, stripe_subscription_id: str, status: str):
        async with self.async_session() as session:
            result = await session.execute(
                select(Subscription).where(
                    Subscription.stripe_subscription_id == stripe_subscription_id
                )
            )
            subscription = result.scalar_one_or_none()
            if subscription:
                subscription.status = status
                subscription.updated_at = datetime.utcnow()
                await session.commit()
    
    # Server usage tracking
    async def start_server_usage(self, user_id: int, port: int, game: str) -> ServerUsage:
        async with self.async_session() as session:
            usage = ServerUsage(
                user_id=user_id,
                port=port,
                game=game,
                started_at=datetime.utcnow()
            )
            session.add(usage)
            await session.commit()
            return usage
    
    async def end_server_usage(self, user_id: int, port: int):
        async with self.async_session() as session:
            result = await session.execute(
                select(ServerUsage).where(
                    and_(
                        ServerUsage.user_id == user_id,
                        ServerUsage.port == port,
                        ServerUsage.ended_at.is_(None)
                    )
                )
            )
            usage = result.scalar_one_or_none()
            if usage:
                usage.ended_at = datetime.utcnow()
                usage.duration_minutes = (usage.ended_at - usage.started_at).total_seconds() / 60
                await session.commit()
    
    async def get_daily_usage_minutes(self, user_id: int) -> float:
        """Get total server usage minutes for today"""
        async with self.async_session() as session:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            
            result = await session.execute(
                select(func.sum(ServerUsage.duration_minutes)).where(
                    and_(
                        ServerUsage.user_id == user_id,
                        ServerUsage.started_at >= today_start,
                        ServerUsage.ended_at.isnot(None)
                    )
                )
            )
            total_minutes = result.scalar() or 0
            
            # Add current active sessions
            active_result = await session.execute(
                select(ServerUsage).where(
                    and_(
                        ServerUsage.user_id == user_id,
                        ServerUsage.started_at >= today_start,
                        ServerUsage.ended_at.is_(None)
                    )
                )
            )
            active_sessions = active_result.scalars().all()
            
            for session_usage in active_sessions:
                duration = (datetime.utcnow() - session_usage.started_at).total_seconds() / 60
                total_minutes += duration
            
            return total_minutes
    
    async def get_remaining_minutes(self, user_id: int) -> Optional[float]:
        """Get remaining server minutes for today based on subscription tier"""
        subscription = await self.get_active_subscription(user_id)
        if not subscription:
            return None
        
        from config import SERVER_TIERS
        daily_limit = SERVER_TIERS.get(subscription.tier, 0)
        used_minutes = await self.get_daily_usage_minutes(user_id)
        
        return max(0, daily_limit - used_minutes)
    
    # Payment tracking
    async def create_payment(self, user_id: int, stripe_payment_intent_id: str, 
                           amount: int, currency: str = 'usd', status: str = 'succeeded') -> Payment:
        async with self.async_session() as session:
            payment = Payment(
                user_id=user_id,
                stripe_payment_intent_id=stripe_payment_intent_id,
                amount=amount,
                currency=currency,
                status=status
            )
            session.add(payment)
            await session.commit()
            return payment