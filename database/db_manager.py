from sqlalchemy import create_engine, and_, func, desc, text, cast, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import uuid
import json

from config import config
from database.models import (
    Client, Conversation, ContentCatalog, PsychProfile, PriceHistory, Base
)
from utils.embedding_utils import generate_embedding

class DBManager:
    def __init__(self):
        self.engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
        self._ensure_pgvector_extension()
        Base.metadata.create_all(self.engine)  # Ensure tables exist
        # expire_on_commit=False keeps ORM objects usable after the session is
        # closed; otherwise every returned object raises DetachedInstanceError
        # when its attributes are accessed downstream in the pipeline.
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def _ensure_pgvector_extension(self):
        """The Vector columns require the pgvector extension to exist before
        create_all() runs, otherwise table creation fails."""
        with self.engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    
    def get_session(self) -> Session:
        return self.SessionLocal()
    
    # ──────────────── CLIENTS ────────────────
    def get_or_create_client(self, fanvue_id: str) -> Client:
        session = self.get_session()
        try:
            client = session.query(Client).filter(Client.fanvue_id == fanvue_id).first()
            if not client:
                client = Client(
                    fanvue_id=fanvue_id,
                    username=f"fan_{fanvue_id[:8]}",
                    join_date=datetime.utcnow(),
                    status="new",
                    total_spent=0.0,
                    total_messages=0,
                    score=50
                )
                session.add(client)
                session.commit()
                session.refresh(client)
                # Create default psych profile
                self._create_default_profile(session, client.id)
            return client
        finally:
            session.close()
    
    def get_client_by_id(self, client_id: uuid.UUID) -> Optional[Client]:
        session = self.get_session()
        try:
            return session.query(Client).filter(Client.id == client_id).first()
        finally:
            session.close()
    
    def get_client_by_fanvue_id(self, fanvue_id: str) -> Optional[Client]:
        session = self.get_session()
        try:
            return session.query(Client).filter(Client.fanvue_id == fanvue_id).first()
        finally:
            session.close()
    
    def update_last_interaction(self, client_id: uuid.UUID):
        session = self.get_session()
        try:
            session.query(Client).filter(Client.id == client_id).update({
                "last_interaction": datetime.utcnow()
            })
            session.commit()
        finally:
            session.close()
    
    def increment_message_count(self, client_id: uuid.UUID):
        session = self.get_session()
        try:
            client = session.query(Client).filter(Client.id == client_id).first()
            if client:
                client.total_messages += 1
                session.commit()
        finally:
            session.close()
    
    def update_client_status(self, client_id: uuid.UUID, status: str):
        session = self.get_session()
        try:
            session.query(Client).filter(Client.id == client_id).update({"status": status})
            session.commit()
        finally:
            session.close()
    
    def update_client_score(self, client_id: uuid.UUID, score_delta: int = 0):
        session = self.get_session()
        try:
            client = session.query(Client).filter(Client.id == client_id).first()
            if client:
                client.score = max(0, min(100, client.score + score_delta))
                session.commit()
        finally:
            session.close()
    
    def get_inactive_clients(self, hours: int = 12) -> List[Client]:
        session = self.get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            return session.query(Client).filter(
                Client.last_interaction < cutoff,
                Client.status.in_(["active", "hot", "whale"])
            ).all()
        finally:
            session.close()
    
    def get_recent_content_sent(self, client_id: uuid.UUID, limit: int = 5) -> List[ContentCatalog]:
        """Returns the last N content items sent to this client to avoid repetition."""
        session = self.get_session()
        try:
            # Get recent conversations where content_sent_id is not null
            recent_conv = session.query(Conversation).filter(
                Conversation.client_id == client_id,
                Conversation.content_sent_id.isnot(None)
            ).order_by(desc(Conversation.timestamp)).limit(limit).all()
            
            if not recent_conv:
                return []
            
            content_ids = [c.content_sent_id for c in recent_conv]
            return session.query(ContentCatalog).filter(ContentCatalog.id.in_(content_ids)).all()
        finally:
            session.close()
    
    def get_purchases_last_24h(self, client_id: uuid.UUID) -> int:
        """Count how many purchases (price_history with purchased=True) in the last 24h."""
        session = self.get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=24)
            count = session.query(PriceHistory).filter(
                PriceHistory.client_id == client_id,
                PriceHistory.purchased == True,
                PriceHistory.timestamp >= cutoff
            ).count()
            return count
        finally:
            session.close()
    
    # ──────────────── PSYCH PROFILES ────────────────
    def _create_default_profile(self, session: Session, client_id: uuid.UUID):
        profile = PsychProfile(
            client_id=client_id,
            primary_trigger="validation",
            secondary_trigger="desire",
            spending_trigger="desire",
            resistance_level=5,
            manipulation_success_rate=0.0,
            weak_points=["need_for_validation"],
            emotional_state="neutral",
            current_arousal=3,
            preferred_content_type="video",
            spending_capacity="medium",
            manipulation_sensitivity=50,
            updated_at=datetime.utcnow()
        )
        session.add(profile)
        session.commit()
    
    def get_psych_profile(self, client_id: uuid.UUID) -> PsychProfile:
        session = self.get_session()
        try:
            profile = session.query(PsychProfile).filter(PsychProfile.client_id == client_id).first()
            if not profile:
                self._create_default_profile(session, client_id)
                profile = session.query(PsychProfile).filter(PsychProfile.client_id == client_id).first()
            return profile
        finally:
            session.close()
    
    def save_psych_profile(self, profile: PsychProfile):
        session = self.get_session()
        try:
            existing = session.query(PsychProfile).filter(PsychProfile.client_id == profile.client_id).first()
            if existing:
                for key, value in profile.__dict__.items():
                    if key not in ['_sa_instance_state', 'client_id']:
                        setattr(existing, key, value)
                existing.updated_at = datetime.utcnow()
            else:
                session.add(profile)
            session.commit()
        finally:
            session.close()
    
    # ──────────────── CONVERSATIONS ────────────────
    def save_conversation(self, client_id: uuid.UUID, message: str, response: str, analysis: Dict[str, Any], content_sent_id: uuid.UUID = None):
        session = self.get_session()
        try:
            conv = Conversation(
                client_id=client_id,
                message=message,
                response=response,
                sentiment_score=analysis.get('sentiment_score', 0.5),
                arousal_level=analysis.get('arousal_level', 3),
                manipulation_tactic_used=analysis.get('primary_trigger', 'unknown'),
                content_sent_id=content_sent_id,
                timestamp=datetime.utcnow(),
                embedding=generate_embedding(f"{message}\n{response}")
            )
            session.add(conv)
            session.commit()
        finally:
            session.close()

    def search_similar_conversations(self, client_id: uuid.UUID, query_text: str, limit: int = 5) -> List[Conversation]:
        """Semantic recall of a client's past conversations using pgvector."""
        session = self.get_session()
        try:
            query_emb = generate_embedding(query_text)
            return session.query(Conversation).filter(
                Conversation.client_id == client_id,
                Conversation.embedding.isnot(None)
            ).order_by(Conversation.embedding.cosine_distance(query_emb)).limit(limit).all()
        finally:
            session.close()
    
    def get_conversation_history(self, client_id: uuid.UUID, limit: int = 20) -> List[Conversation]:
        session = self.get_session()
        try:
            return session.query(Conversation).filter(
                Conversation.client_id == client_id
            ).order_by(desc(Conversation.timestamp)).limit(limit).all()
        finally:
            session.close()
    
    # ──────────────── CONTENT CATALOG ────────────────
    def get_all_content(self) -> List[ContentCatalog]:
        session = self.get_session()
        try:
            return session.query(ContentCatalog).all()
        finally:
            session.close()

    def semantic_search_content(self, query_text: str, limit: int = 10) -> List[ContentCatalog]:
        """Rank catalog items by semantic closeness to the fan's message
        using the pgvector cosine-distance operator."""
        session = self.get_session()
        try:
            query_emb = generate_embedding(query_text)
            return session.query(ContentCatalog).filter(
                ContentCatalog.embedding.isnot(None)
            ).order_by(ContentCatalog.embedding.cosine_distance(query_emb)).limit(limit).all()
        finally:
            session.close()
    
    def get_content_by_type(self, content_type: str) -> List[ContentCatalog]:
        session = self.get_session()
        try:
            return session.query(ContentCatalog).filter(ContentCatalog.type == content_type).all()
        finally:
            session.close()
    
    def get_content_by_id(self, content_id: uuid.UUID) -> Optional[ContentCatalog]:
        session = self.get_session()
        try:
            return session.query(ContentCatalog).filter(ContentCatalog.id == content_id).first()
        finally:
            session.close()
    
    def get_content_by_tags(self, tags: List[str], limit: int = 10) -> List[ContentCatalog]:
        session = self.get_session()
        try:
            # Postgres JSONB "?|" operator: true if any of the given strings
            # exist as top-level array elements in the tags column.
            return session.query(ContentCatalog).filter(
                ContentCatalog.tags.op("?|")(cast(tags, ARRAY(Text)))
            ).limit(limit).all()
        finally:
            session.close()
    
    def increment_content_sent_count(self, content_id: uuid.UUID):
        session = self.get_session()
        try:
            content = session.query(ContentCatalog).filter(ContentCatalog.id == content_id).first()
            if content:
                content.times_sent += 1
                content.last_sent = datetime.utcnow()
                session.commit()
        finally:
            session.close()
    
    # ──────────────── PRICE HISTORY ────────────────
    def save_price_history(self, client_id: uuid.UUID, content_id: uuid.UUID, price: float, factors: Dict) -> uuid.UUID:
        session = self.get_session()
        try:
            entry = PriceHistory(
                client_id=client_id,
                content_id=content_id,
                calculated_price=price,
                factors=factors,
                purchased=False,
                timestamp=datetime.utcnow()
            )
            session.add(entry)
            session.commit()
            session.refresh(entry)
            return entry.id
        finally:
            session.close()
    
    def mark_price_as_purchased(self, price_history_id: uuid.UUID):
        session = self.get_session()
        try:
            session.query(PriceHistory).filter(PriceHistory.id == price_history_id).update({"purchased": True})
            session.commit()
        finally:
            session.close()

    # ──────────────── OFFERS / REJECTIONS ────────────────
    def set_last_offer(self, client_id: uuid.UUID, price: float):
        """Records the price of the most recent offer made to a client."""
        session = self.get_session()
        try:
            session.query(Client).filter(Client.id == client_id).update({
                "last_offer_price": price,
                "last_offer_rejected": False
            })
            session.commit()
        finally:
            session.close()

    def register_rejection(self, client_id: uuid.UUID):
        """Increments the rejection counter when a fan pushes back on price."""
        session = self.get_session()
        try:
            client = session.query(Client).filter(Client.id == client_id).first()
            if client:
                client.rejection_count = (client.rejection_count or 0) + 1
                client.last_offer_rejected = True
                session.commit()
        finally:
            session.close()

    def _status_for_spend(self, total_spent: float) -> str:
        if total_spent >= 1000:
            return "whale"
        if total_spent >= 200:
            return "hot"
        if total_spent > 0:
            return "active"
        return "new"

    def record_purchase(self, fanvue_id: str, amount: float, content_id: uuid.UUID = None) -> bool:
        """
        Registers a completed PPV purchase:
          - adds the amount to the client's lifetime spend
          - promotes the client's status (active/hot/whale) based on spend
          - marks the most recent matching price_history row as purchased
        Returns True if the client was found and updated.
        """
        session = self.get_session()
        try:
            client = session.query(Client).filter(Client.fanvue_id == fanvue_id).first()
            if not client:
                return False

            client.total_spent = float(client.total_spent or 0) + float(amount)
            client.rejection_count = 0
            client.last_offer_rejected = False
            client.status = self._status_for_spend(float(client.total_spent))

            ph_query = session.query(PriceHistory).filter(
                PriceHistory.client_id == client.id,
                PriceHistory.purchased == False
            )
            if content_id:
                if isinstance(content_id, str):
                    content_id = uuid.UUID(content_id)
                ph_query = ph_query.filter(PriceHistory.content_id == content_id)
            latest = ph_query.order_by(desc(PriceHistory.timestamp)).first()
            if latest:
                latest.purchased = True

            session.commit()
            return True
        finally:
            session.close()
