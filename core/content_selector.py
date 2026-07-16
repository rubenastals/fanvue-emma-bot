import random
from datetime import datetime
from typing import Dict, Any, Optional, List
from uuid import UUID
from database.db_manager import DBManager
from core.dynamic_pricing import DynamicPricingEngine
from database.models import ContentCatalog, Client

class ContentSelector:
    def __init__(self, db_manager: DBManager):
        self.db = db_manager
        self.pricing_engine = DynamicPricingEngine(db_manager)
    
    def select_content(self, client_id: UUID, analysis: Dict[str, Any], message: str = None) -> Dict[str, Any]:
        """
        Selects the best content from the catalog, avoids repetition,
        and calculates the dynamic price.

        When the fan's `message` is provided, candidate content is first ranked
        by semantic similarity (pgvector) so we surface the clips whose
        title/description/tags best match what he's talking about.
        """
        client = self.db.get_client_by_id(client_id)
        profile = self.db.get_psych_profile(client_id)
        
        # 1. Fetch candidate content, semantically ranked by the fan's message
        #    when available; otherwise fall back to the full catalog.
        all_content = []
        if message:
            all_content = self.db.semantic_search_content(message, limit=20)
        if not all_content:
            all_content = self.db.get_all_content()
        
        if not all_content:
            # Fallback if catalog is empty (should not happen)
            return self._empty_fallback(client_id, analysis)
        
        # 2. Get recently sent content to avoid repetition
        recent_sent = self.db.get_recent_content_sent(client_id, limit=5)
        recent_ids = [c.id for c in recent_sent]
        
        # 3. Filter out recently sent
        available = [c for c in all_content if c.id not in recent_ids]
        
        # 4. If no fresh content, use the least recently sent one
        if not available:
            available = sorted(all_content, key=lambda c: c.last_sent or datetime.min)
        
        # 5. Filter by preferred type (if set and available)
        preferred = profile.preferred_content_type or "video"
        preferred_pool = [c for c in available if c.type == preferred]
        if preferred_pool:
            pool = preferred_pool
        else:
            pool = available
        
        # 6. If the fan is NOT semantically ranked (no message) or he's hot/cold,
        #    apply the explicitness/softness heuristic. When a message drove a
        #    semantic ranking we keep that order, only re-sorting on heat.
        semantic_ranked = bool(message)
        if analysis.get('buying_signal', False) or analysis.get('arousal_level', 0) > 7:
            # He's hot -> send the most explicit content
            pool = sorted(pool, key=lambda c: c.explicitness_score or 0, reverse=True)
        elif not semantic_ranked:
            # He's cold -> send soft/romantic content to warm him up
            pool = sorted(pool, key=lambda c: c.softness_score or 5, reverse=True)
        
        # 7. Pick the best one
        selected_content = pool[0]
        
        # 8. Calculate price dynamically
        price = self.pricing_engine.calculate_price(
            client_id, 
            selected_content, 
            analysis.get('arousal_level', 3),
            analysis
        )
        
        # 9. Increment send counter in DB
        self.db.increment_content_sent_count(selected_content.id)
        
        return {
            "content": selected_content,
            "price": round(price, 2),
            "strategy": self._determine_strategy(client, analysis)
        }
    
    def _determine_strategy(self, client: Client, analysis: Dict) -> str:
        if client.total_spent > 1000:
            return "whale_premium"
        elif analysis.get('arousal_level', 0) > 7:
            return "heat_up"
        elif analysis.get('resistance_level', 5) > 7:
            return "break_resistance"
        elif client.rejection_count > 2:
            return "recovery"
        elif analysis.get('primary_trigger') == 'validation':
            return "love_bomb"
        elif analysis.get('primary_trigger') == 'dominance':
            return "challenge_masculinity"
        else:
            return "standard"
    
    def _empty_fallback(self, client_id: UUID, analysis: Dict) -> Dict:
        """Mock fallback if no content is loaded in the DB."""
        from database.models import ContentCatalog
        import uuid
        
        mock_content = ContentCatalog(
            id=uuid.uuid4(),
            title="Emma's Exclusive Tease",
            description="A special clip just for you.",
            file_url="https://example.com/mock.mp4",
            price_base=14.99,
            price_whale=24.99,
            duration_seconds=120,
            type="video",
            tags=["tease", "exclusive"],
            explicitness_score=6,
            softness_score=4
        )
        price = self.pricing_engine.calculate_price(client_id, mock_content, analysis.get('arousal_level', 3), analysis)
        return {
            "content": mock_content,
            "price": round(price, 2),
            "strategy": "standard"
        }
