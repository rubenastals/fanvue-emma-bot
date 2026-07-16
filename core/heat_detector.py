import re
from datetime import datetime
from typing import List, Any
from database.db_manager import DBManager

class HeatDetector:
    def __init__(self, db_manager: DBManager):
        self.db = db_manager
    
    def detect_heat_level(self, client_id: str, message: str, history: List) -> int:
        """Returns an arousal level from 1 to 10."""
        
        # 1. Dirty keywords
        heat_keywords = [
            'polla', 'coño', 'correrme', 'follar', 'chupar', 'meter', 
            'mamar', 'darle duro', 'venirme', 'cock', 'pussy', 'cum',
            'fuck', 'suck', 'dick', 'wet', 'hard', 'thick', 'papi',
            'guarra', 'puta', 'zorra', 'perra', 'caliente', 'hot'
        ]
        heat_count = sum(1 for kw in heat_keywords if kw in message.lower())
        
        # 2. Hot emojis
        hot_emojis = ['🥵', '😈', '🔥', '💦', '🍆', '🥵', '💕', '❤️‍🔥']
        emoji_count = sum(1 for emoji in hot_emojis if emoji in message)
        
        # 3. Urgency/Demand words
        urgency_words = ['quiero', 'necesito', 'deseo', 'ahora', 'ya', 'urgente', 'now', 'want', 'need']
        urgency_count = sum(1 for w in urgency_words if w in message.lower())
        
        # Base heat
        heat = 3  # neutral starting point
        
        # Add factors
        heat += min(heat_count * 1.5, 4)      # max +4
        heat += min(emoji_count * 1.2, 3)     # max +3
        heat += min(urgency_count * 1.0, 2)   # max +2
        
        # Check if he just bought recently
        recent_purchases = self.db.get_purchases_last_24h(client_id)
        if recent_purchases > 0:
            heat += 1  # Post-purchase arousal is high
        
        # Time factor (night boost)
        hour = datetime.now().hour
        if 22 <= hour or hour <= 4:
            heat += 1
        
        # Clamp between 1 and 10
        return max(1, min(10, int(round(heat))))
