import json
import re
from typing import Dict, Any, List
from openai import OpenAI
from config import config

class PsychologicalAnalyzer:
    def __init__(self, ai_client: OpenAI):
        self.client = ai_client
    
    def analyze_message(self, client_id: str, message: str, history: List) -> Dict[str, Any]:
        """Analyzes the fan's message and extracts psychological insights."""
        
        # Prepare a condensed history for context
        history_text = ""
        if history:
            last_5 = history[-5:]
            history_text = "\n".join([f"Fan: {h.message}\nEmma: {h.response}" for h in last_5])
        
        prompt = f"""
        You are a behavioral psychologist and manipulation expert. Analyze this fan's message for the Emma AI system.

        **Context:**
        Client ID: {client_id}
        Recent Conversation:
        {history_text if history_text else "No recent history."}

        **Current Fan Message:**
        "{message}"

        **Return ONLY valid JSON** with the following structure:
        {{
            "emotional_state": "horny" | "romantic" | "angry" | "sad" | "happy" | "lonely" | "dominant" | "submissive" | "neutral",
            "arousal_level": integer 1-10,
            "weak_points_detected": ["needs_validation", "low_self_esteem", "loneliness", "addiction", "need_for_control", "guilt_complex", "savior_complex"],
            "primary_trigger": "validation" | "dominance" | "savior" | "loneliness" | "control" | "desire",
            "secondary_trigger": "validation" | "dominance" | "savior" | "loneliness" | "control" | "desire" | null,
            "spending_trigger": "guilt" | "desire" | "exclusivity" | "competition" | "empathy",
            "resistance_level": integer 1-10 (how resistant is he to emotional manipulation right now),
            "buying_signal": boolean,
            "price_objection": boolean (true if he complains about price, asks for a discount, says he has no money, or asks for free content),
            "sentiment_score": float -1.0 to 1.0
        }}
        """
        
        try:
            response = self.client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=[{"role": "system", "content": "You are an expert psychologist. Output only JSON."},
                          {"role": "user", "content": prompt}],
                temperature=0.2,  # Low temp for consistent parsing
                max_tokens=300,
                response_format={"type": "json_object"}
            )
            
            raw = response.choices[0].message.content
            # Clean potential markdown
            raw = re.sub(r'```json\s*|\s*```', '', raw).strip()
            return json.loads(raw)
        
        except Exception as e:
            print(f"Error analyzing message: {e}")
            # Return safe defaults
            return {
                "emotional_state": "neutral",
                "arousal_level": 3,
                "weak_points_detected": ["need_for_validation"],
                "primary_trigger": "validation",
                "secondary_trigger": None,
                "spending_trigger": "desire",
                "resistance_level": 5,
                "buying_signal": False,
                "price_objection": False,
                "sentiment_score": 0.0
            }
