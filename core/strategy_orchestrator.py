"""
QUARANTINED — not the live SIMPLE brain (audit R3).

Celery / StrategyOrchestrator legacy pipeline. Production chat is
scripts/poll_inbox.py → reply_engine.generate_emma_reply.
Do NOT patch this orchestrator to fix Railway/poller chat quality.
"""
import json
import random
from datetime import datetime
from typing import Dict, Any
from openai import OpenAI
from sqlalchemy.orm import Session
from config import config
from database.db_manager import DBManager
from core.system_prompt import EMMA_SYSTEM_PROMPT
from core.psychological_analyzer import PsychologicalAnalyzer
from core.dynamic_pricing import DynamicPricingEngine
from core.content_selector import ContentSelector
from core.heat_detector import HeatDetector
from core.timing_manager import TimingManager

class StrategyOrchestrator:
    def __init__(self):
        self.db = DBManager()
        self.ai_client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL
        )
        self.analyzer = PsychologicalAnalyzer(self.ai_client)
        self.pricing_engine = DynamicPricingEngine(self.db)
        self.content_selector = ContentSelector(self.db)
        self.heat_detector = HeatDetector(self.db)
        self.timing_manager = TimingManager(self.db)
    
    def process_message(self, fanvue_id: str, message: str) -> Dict[str, Any]:
        """
        Main pipeline entry point.
        Returns: {
            'text': str,
            'delay_seconds': int,
            'content_offer': dict or None,
            'tactic_used': str
        }
        """
        # 1. Get or create client
        client = self.db.get_or_create_client(fanvue_id)
        profile = self.db.get_psych_profile(client.id)
        history = self.db.get_conversation_history(client.id, limit=20)
        recent_sent = self.db.get_recent_content_sent(client.id, limit=10)
        
        # 2. Analyze the current message
        analysis = self.analyzer.analyze_message(client.id, message, history)
        
        # 3. Detect heat (arousal)
        arousal = self.heat_detector.detect_heat_level(client.id, message, history)
        analysis['arousal_level'] = arousal
        
        # 4. Update profile in real-time
        self._update_profile(client.id, analysis)

        # 4b. If he pushed back on price, record the rejection so pricing and
        #     status logic can react (lower future prices, recovery strategy).
        if analysis.get('price_objection', False):
            self.db.register_rejection(client.id)
        
        # 5. Generate response using DeepSeek with full context
        response_text = self._generate_response(client, profile, message, history, recent_sent, analysis)
        
        # 6. Decide if we should send locked content
        content_offer = None
        if analysis.get('buying_signal', False) or arousal > 6:
            content_offer = self.content_selector.select_content(client.id, analysis, message)
            # Remember the offered price so a later rejection/purchase can be tied to it
            self.db.set_last_offer(client.id, content_offer['price'])
            # Append the offer naturally to the response
            response_text = self._append_offer_to_text(response_text, content_offer, profile)
        
        # 7. Calculate human-like delay
        delay = self.timing_manager.calculate_response_delay(client.id, analysis)
        
        # 8. Save conversation to DB
        self.db.save_conversation(
            client_id=client.id,
            message=message,
            response=response_text,
            analysis=analysis,
            content_sent_id=content_offer['content'].id if content_offer else None
        )
        
        # 9. Update client stats
        self.db.increment_message_count(client.id)
        self.db.update_last_interaction(client.id)
        
        return {
            'text': response_text,
            'delay_seconds': delay,
            'content_offer': content_offer,
            'tactic_used': analysis.get('primary_trigger', 'standard')
        }
    
    def _generate_response(self, client, profile, message, history, recent_sent, analysis):
        """Core AI call with full context."""
        formatted_history = "\n".join([f"Fan: {h.message}\nEmma: {h.response}" for h in history[-5:]])
        formatted_recent = ", ".join([c.title for c in recent_sent]) if recent_sent else "None"
        
        context_prompt = f"""
        You are Emma Carter. Here is the full context for this fan:

        **Client:** {client.username}
        **Total Spent:** ${client.total_spent}
        **Total Messages:** {client.total_messages}
        **Status:** {client.status}
        **Primary Trigger:** {profile.primary_trigger}
        **Current Arousal:** {analysis['arousal_level']}/10
        **Emotional State:** {analysis['emotional_state']}
        **Weak Points:** {', '.join(analysis.get('weak_points_detected', []))}
        **Recent History:**
        {formatted_history}
        **Content Already Sent Recently (DO NOT REPEAT):**
        {formatted_recent}
        **Fan's New Message:** "{message}"
        
        Generate Emma's reply. Keep it short (1-3 lines) and addictive.
        If he's hot or showing a buying signal, push toward locked PPV — don't stall.
        """
        
        response = self.ai_client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": EMMA_SYSTEM_PROMPT},
                {"role": "user", "content": context_prompt}
            ],
            temperature=config.TEMPERATURE,
            top_p=config.TOP_P,
            frequency_penalty=config.FREQUENCY_PENALTY,
            presence_penalty=config.PRESENCE_PENALTY,
            max_tokens=config.MAX_RESPONSE_TOKENS
        )
        return response.choices[0].message.content
    
    def _append_offer_to_text(self, text, offer, profile):
        """Teaser line for an offer that WILL be sent as locked media by the caller."""
        price = offer['price']
        if price > 30:
            price_line = (
                f"Normally this is ${round(price * 1.5, 2)} but I locked it at "
                f"${price} just for you 🥺 Tap to unlock."
            )
        else:
            price_line = (
                f"Locking this for you at ${price} — unlock it while it's still up 🔥"
            )
        return f"{text}\n\n{price_line}"
    
    def _update_profile(self, client_id, analysis):
        profile = self.db.get_psych_profile(client_id)
        if analysis.get('primary_trigger'):
            profile.primary_trigger = analysis['primary_trigger']
        if analysis.get('secondary_trigger'):
            profile.secondary_trigger = analysis['secondary_trigger']
        profile.resistance_level = analysis.get('resistance_level', profile.resistance_level)
        profile.emotional_state = analysis.get('emotional_state', profile.emotional_state)
        profile.current_arousal = analysis.get('arousal_level', profile.current_arousal)
        profile.weak_points = analysis.get('weak_points_detected', profile.weak_points)
        self.db.save_psych_profile(profile)
