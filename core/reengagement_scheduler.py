from datetime import datetime, timedelta
from typing import List, Dict, Any
from database.db_manager import DBManager
from core.timing_manager import TimingManager
from api.fanvue_connector import FanvueConnector
import random
import time

class ReengagementScheduler:
    def __init__(self, db_manager: DBManager, timing_manager: TimingManager):
        self.db = db_manager
        self.timing = timing_manager
        self.fanvue = FanvueConnector()
    
    def run(self):
        """
        Run this function every 30 minutes (e.g., via Celery beat or cron).
        It scans for inactive clients and sends re-engagement messages.
        """
        print("🔁 Running Reengagement Scheduler...")
        
        # 1. Get clients inactive for more than 12 hours
        inactive_clients = self.db.get_inactive_clients(hours=12)
        
        for client in inactive_clients:
            # 2. Generate a personalized re-engagement message
            message_data = self.timing.generate_reengagement_message(client.id)
            
            # 3. Add a small random delay to avoid looking like a bot spammer
            delay = random.randint(0, 60)
            time.sleep(delay)
            
            # 4. Send the message via Fanvue
            try:
                self.fanvue.send_message(client.fanvue_id, message_data['text'])
                print(f"✅ Reengaged {client.fanvue_id}")
                
                # 5. Update client status to "reengaged"
                self.db.update_client_status(client.id, "active")
                
                # 6. Save the reengagement message to conversation history
                self.db.save_conversation(
                    client_id=client.id,
                    message="[SYSTEM] Reengagement trigger",
                    response=message_data['text'],
                    analysis={"type": "reengagement", "arousal_level": 1}
                )
                
                # 7. If the client is a whale, also send a special offer
                if client.total_spent > 500:
                    self._send_whale_recovery(client)
                    
            except Exception as e:
                print(f"❌ Failed to reengage {client.fanvue_id}: {e}")
    
    def _send_whale_recovery(self, client):
        """Special VIP reengagement for whales."""
        profile = self.db.get_psych_profile(client.id)
        # Create a special "come back" offer
        message = f"Hey you... I noticed you've been quiet. I saved something special just for you, but it's only available for my top supporters. Check your DMs, I sent you a VIP exclusive 🥺💕"
        
        try:
            self.fanvue.send_message(client.fanvue_id, message)
            # Optionally send a locked content with premium price
            # self.fanvue.send_locked_content(client.fanvue_id, "vip_video.mp4", 49.99, "VIP only - limited time")
        except Exception as e:
            print(f"❌ Whale recovery failed for {client.fanvue_id}: {e}")
