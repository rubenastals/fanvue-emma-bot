"""
Celery tasks.

Flow:
  webhook  ──enqueue──▶  handle_incoming_message
                              │  runs the full pipeline (analysis, pricing, ...)
                              │  computes a human-like delay
                              ▼
                         send_reply.apply_async(countdown=delay)
                              │  fires AFTER the delay
                              ▼
                         Fanvue send_message / send_locked_content
"""
from celery_app import celery_app
from config import config

# Lazily-built singletons so importing this module (e.g. by the beat process)
# doesn't immediately open a DB connection or an OpenAI client.
_orchestrator = None
_fanvue = None


def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from core.strategy_orchestrator import StrategyOrchestrator
        _orchestrator = StrategyOrchestrator()
    return _orchestrator


def get_fanvue():
    global _fanvue
    if _fanvue is None:
        from api.fanvue_connector import FanvueConnector
        _fanvue = FanvueConnector()
    return _fanvue


@celery_app.task(name="tasks.handle_incoming_message", bind=True, max_retries=3, default_retry_delay=10)
def handle_incoming_message(self, fanvue_id: str, message: str):
    """Run the pipeline and schedule the (delayed) reply."""
    try:
        orch = get_orchestrator()
        result = orch.process_message(fanvue_id, message)

        offer_payload = None
        offer = result.get("content_offer")
        if offer:
            content = offer["content"]
            offer_payload = {
                "price": offer["price"],
                "description": content.description,
                "media_uuid": getattr(content, "fanvue_media_uuid", None),
            }

        delay = max(0, int(result.get("delay_seconds", 0)))
        send_reply.apply_async(
            args=[fanvue_id, result["text"], offer_payload],
            countdown=delay,
        )
        return {"scheduled_in_seconds": delay, "tactic": result.get("tactic_used")}
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(name="tasks.send_reply", bind=True, max_retries=5, default_retry_delay=15)
def send_reply(self, fanvue_id: str, text: str, offer_payload: dict = None):
    """Deliver the text reply (and any locked PPV offer) via Fanvue."""
    try:
        fanvue = get_fanvue()
        fanvue.send_message(fanvue_id, text)
        if offer_payload and offer_payload.get("media_uuid"):
            fanvue.send_locked_content(
                fanvue_id,
                price=offer_payload["price"],
                description=offer_payload.get("description"),
                media_uuid=offer_payload["media_uuid"],
            )
        return {"sent": True, "had_offer": bool(offer_payload)}
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(name="tasks.run_reengagement")
def run_reengagement():
    """Periodic scan (via beat) for inactive fans."""
    from core.reengagement_scheduler import ReengagementScheduler
    orch = get_orchestrator()
    scheduler = ReengagementScheduler(orch.db, orch.timing_manager)
    scheduler.run()
    return {"status": "reengagement_scan_complete"}
