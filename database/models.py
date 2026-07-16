from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, JSON, Text, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from pgvector.sqlalchemy import Vector
import uuid
from datetime import datetime

Base = declarative_base()

class Client(Base):
    __tablename__ = "clients"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fanvue_id = Column(String(100), unique=True, nullable=False)
    username = Column(String(100))
    join_date = Column(DateTime, default=datetime.utcnow)
    total_spent = Column(Numeric(10, 2), default=0.00)
    total_messages = Column(Integer, default=0)
    last_interaction = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="new")  # new, active, hot, whale, dormant, lost
    preferred_tone = Column(String(20), default="bratty")
    rejection_count = Column(Integer, default=0)
    last_offer_rejected = Column(Boolean, default=False)
    last_offer_price = Column(Numeric(10, 2))
    avg_response_time_seconds = Column(Integer, default=5)
    score = Column(Integer, default=50)  # Overall internal score

class Conversation(Base):
    __tablename__ = "conversations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(UUID(as_uuid=True))
    message = Column(Text)
    response = Column(Text)
    sentiment_score = Column(Float)
    arousal_level = Column(Integer)  # 1-10
    manipulation_tactic_used = Column(String(50))
    content_sent_id = Column(UUID(as_uuid=True), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    embedding = Column(Vector(1536))  # For semantic search

class ContentCatalog(Base):
    __tablename__ = "content_catalog"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(200))
    description = Column(Text)
    file_url = Column(String(500))
    price_base = Column(Numeric(10, 2))
    price_whale = Column(Numeric(10, 2))
    duration_seconds = Column(Integer, default=0)
    type = Column(String(20))  # video, photo, audio
    tags = Column(JSONB)  # Array of strings
    explicitness_score = Column(Integer, default=5)  # 1-10, 10 = hardest
    softness_score = Column(Integer, default=5)  # 1-10, 10 = softest/romantic
    times_sent = Column(Integer, default=0)
    last_sent = Column(DateTime, nullable=True)
    embedding = Column(Vector(1536))

class PsychProfile(Base):
    __tablename__ = "psych_profiles"
    
    client_id = Column(UUID(as_uuid=True), primary_key=True)
    primary_trigger = Column(String(50), default="validation")
    secondary_trigger = Column(String(50))
    spending_trigger = Column(String(50), default="desire")
    resistance_level = Column(Integer, default=5)  # 1-10
    manipulation_success_rate = Column(Float, default=0.0)
    weak_points = Column(JSONB, default=[])  # e.g., ["loneliness", "need for validation"]
    emotional_state = Column(String(20), default="neutral")
    current_arousal = Column(Integer, default=3)  # 1-10
    preferred_content_type = Column(String(20), default="video")
    spending_capacity = Column(String(10), default="medium")  # low, medium, high, whale
    last_manipulation_tactic = Column(String(50))
    manipulation_sensitivity = Column(Integer, default=50)  # 0-100
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PriceHistory(Base):
    __tablename__ = "price_history"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(UUID(as_uuid=True))
    content_id = Column(UUID(as_uuid=True))
    calculated_price = Column(Numeric(10, 2))
    factors = Column(JSONB)  # Store the multipliers used
    purchased = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
