from datetime import datetime
import random

class DynamicPricingEngine:
    def __init__(self, db_manager):
        self.db = db_manager
    
    def calculate_price(self, client_id, content, arousal_level, analysis):
        client = self.db.get_client_by_id(client_id)
        profile = self.db.get_psych_profile(client_id)
        base_price = float(content.price_base)
        
        # 1. Arousal Factor (HOTTER = MORE EXPENSIVE)
        arousal_factor = 1 + (arousal_level / 20)  # 1.0 -> 1.5
        
        # 2. Whale Factor (If big spender, charge more)
        if client.total_spent > 1000:
            whale_factor = 1.4
        elif client.total_spent > 500:
            whale_factor = 1.2
        elif client.total_spent > 200:
            whale_factor = 1.05
        else:
            whale_factor = 1.0
        
        # 3. Resistance Factor (If resistant, lower to break barrier)
        if profile.resistance_level > 7:
            resistance_factor = 0.8
        elif profile.resistance_level > 4:
            resistance_factor = 0.9
        else:
            resistance_factor = 1.0
        
        # 4. Recency Factor (If bought recently, charge more)
        recent_purchases = self.db.get_purchases_last_24h(client_id)
        if recent_purchases > 3:
            recency_factor = 1.25
        elif recent_purchases > 1:
            recency_factor = 1.1
        else:
            recency_factor = 1.0
        
        # 5. Rejection Factor (If rejected many times, lower to convert)
        if client.rejection_count > 2:
            rejection_factor = 0.85
        elif client.rejection_count > 0:
            rejection_factor = 0.95
        else:
            rejection_factor = 1.0
        
        # 6. Time Factor (Night = more expensive)
        hour = datetime.now().hour
        if 22 <= hour or hour <= 2:
            time_factor = 1.25
        elif 20 <= hour <= 23:
            time_factor = 1.1
        else:
            time_factor = 1.0
        
        # 7. Buying Signal Boost (If he is begging, raise price)
        if analysis.get('buying_signal', False) and arousal_level > 8:
            desperation_factor = 1.2
        else:
            desperation_factor = 1.0
        
        # Calculate final price
        final_price = base_price * arousal_factor * whale_factor * resistance_factor * recency_factor * rejection_factor * time_factor * desperation_factor
        
        # Rounding strategy
        if final_price < 10:
            final_price = round(final_price * 2) / 2
        elif final_price < 30:
            final_price = round(final_price)
        else:
            final_price = round(final_price / 5) * 5
        
        # Clamp to min/max
        final_price = max(3.99, min(final_price, 99.99))
        
        # Log price calculation
        self.db.save_price_history(client_id, content.id, final_price, {
            'base': base_price,
            'arousal_factor': arousal_factor,
            'whale_factor': whale_factor,
            'resistance_factor': resistance_factor,
            'recency_factor': recency_factor,
            'time_factor': time_factor,
            'desperation_factor': desperation_factor
        })
        
        return round(final_price, 2)
