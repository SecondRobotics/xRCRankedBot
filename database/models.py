from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, ForeignKey, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    discord_id = Column(BigInteger, primary_key=True)
    stripe_customer_id = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    subscriptions = relationship("Subscription", back_populates="user")
    payments = relationship("Payment", back_populates="user")
    server_usage = relationship("ServerUsage", back_populates="user")

class Subscription(Base):
    __tablename__ = 'subscriptions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.discord_id'))
    stripe_subscription_id = Column(String, unique=True)
    stripe_price_id = Column(String)
    status = Column(String)  # active, cancelled, past_due, etc.
    tier = Column(String)  # basic, premium
    current_period_end = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="subscriptions")

class Payment(Base):
    __tablename__ = 'payments'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.discord_id'))
    stripe_payment_intent_id = Column(String, unique=True)
    amount = Column(Integer)  # Amount in cents
    currency = Column(String, default='usd')
    status = Column(String)  # succeeded, failed, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="payments")

class ServerUsage(Base):
    __tablename__ = 'server_usage'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.discord_id'))
    port = Column(Integer)
    game = Column(String)
    duration_minutes = Column(Float)
    started_at = Column(DateTime)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="server_usage")
    
    @property
    def is_active(self):
        return self.ended_at is None