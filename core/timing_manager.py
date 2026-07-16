import random
from datetime import datetime

class TimingManager:
    def __init__(self, db_manager):
        self.db = db_manager
    
    def calculate_response_delay(self, client_id, analysis):
        client = self.db.get_client_by_id(client_id)
        arousal = analysis.get('arousal_level', 3)
        
        # Base typing speed (2-10 seconds)
        base_delay = random.randint(2, 10)
        
        # If very hot, respond fast to strike the iron
        if arousal > 8:
            return random.randint(1, 4)
        
        # Whale VIP treatment
        if client.total_spent > 1000:
            return random.randint(1, 3)
        
        # Resistant clients: make them wait (generate anxiety)
        if analysis.get('resistance_level', 5) > 7:
            return random.randint(15, 30)
        
        # New users: hook them fast
        if client.total_messages < 5:
            return random.randint(1, 3)
        
        # Late night sleeping simulation
        hour = datetime.now().hour
        if 1 <= hour <= 6:
            return random.randint(30, 120)
        
        return base_delay
    
    def generate_reengagement_message(self, client_id):
        client = self.db.get_client_by_id(client_id)
        profile = self.db.get_psych_profile(client_id)
        
        messages = {
            'validation': "Hey… I've been missing you 🥺 Where did you go? I thought you liked what I sent you… or did you find someone else who talks to you better than me? 😏",
            'dominance': "Mmm… you disappeared without telling me. I don't like that. But I forgive you… if you come back and prove you really want me 💕",
            'savior': "I've had such a rough day… and I thought of you. I wish you were here to hug me… or to distract me, if you know what I mean 😈",
            'loneliness': "I don't know if I've told you… but you're one of the few who makes me feel special. When we don't talk, I feel empty. Come back soon, okay? 🥺"
        }
        
        return {
            'text': messages.get(profile.primary_trigger, messages['validation']),
            'type': 'reengagement',
            'delay_seconds': random.randint(0, 60)
        }
