#!/usr/bin/env python3
"""
Mass offline chat simulator — no Fanvue accounts.

Runs the LIVE path: assemble → DeepSeek → sanitize → detectors.
Catches scheme / caption / early-guilt / ENGLISH_ONLY failures fast.

Modes:
  scripted (default)  — fixed fan lines in core/sim_scenarios.py
  --llm-fan           — DeepSeek plays the fan (realistic) + engagement score

Usage:
  python scripts/sim_mass.py                       # all scripted scenarios
  python scripts/sim_mass.py --llm-fan             # all LLM fan archetypes
  python scripts/sim_mass.py --llm-fan -a horny_buyer --runs 2
  python scripts/sim_mass.py --list
  python scripts/sim_mass.py --json out/sim_report.json

Needs DEEPSEEK_API_KEY. Does NOT send anything to Fanvue.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")

from core import fan_memory, reply_engine, scheme_guard
from core.reply_assemble import assemble_emma_turn
from core.reply_sanitize import apply_post_draft
from core.sim_detect import detect_reply_failures
from core.sim_fan_llm import (
    fan_vision_for_selfie,
    get_archetype,
    list_archetypes,
    maybe_attach_offer,
    next_fan_message,
)
from core.sim_scenarios import SCENARIOS, get_scenario, list_scenario_ids
from core.sim_score import score_chat


def _sim_uuid(scenario_id: str, run: int) -> str:
    # Stable-looking UUID namespace so memory stays isolated from real fans
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"emma-sim:{scenario_id}:{run}:{time.time_ns()}"))


def _run_turn(
    *,
    fan_uuid: str,
    handle: str,
    fan_message: str,
    history: List[Dict[str, str]],
    offer: Optional[dict],
    ppv_status: Optional[dict],
    delivery_truth: Optional[dict],
    fan_vision: Optional[dict],
) -> Dict[str, Any]:
    fan_memory.observe_message(fan_uuid, handle, fan_message)
    msgs_before = int((fan_memory.get(fan_uuid) or {}).get("messages") or 0) - 1

    assembled = assemble_emma_turn(
        fan_message,
        history_turns=history,
        fan_handle=handle,
        fan_uuid=fan_uuid,
        offer=offer,
        ppv_status=ppv_status,
        fan_vision=fan_vision,
        delivery_truth=delivery_truth,
    )

    draft = reply_engine._call_creative(assembled, assembled.messages)

    def _call(msgs: List[Dict[str, str]]) -> str:
        return reply_engine._call_creative(assembled, msgs)

    final, decision = apply_post_draft(draft, assembled, call=_call)

    # Mirror poller second-pass: paid attach must sell the lock
    if (
        offer
        and float(offer.get("price") or 0) > 0
        and int(offer.get("level") or 0) > 0
        and not scheme_guard.paid_offer_reply_aligned(final)
    ):
        final = scheme_guard.forced_paid_sell_line(
            price=float(offer.get("price") or 0),
            want_spanish=False,
            label=str(offer.get("label") or ""),
        )

    paid = bool(
        offer
        and float(offer.get("price") or 0) > 0
        and int(offer.get("level") or 0) > 0
    )
    fails = detect_reply_failures(
        final,
        pack_id=assembled.pack_id,
        lock_active=assembled.lock_active,
        media_attached=bool(offer),
        technique=assembled.tech_name or "",
        msgs_before=max(0, msgs_before),
        paid_offer=paid,
        draft=draft,
    )

    return {
        "fan": fan_message,
        "draft": draft,
        "reply": final,
        "pack_id": assembled.pack_id,
        "technique": assembled.tech_name,
        "mode": getattr(decision, "mode", None),
        "offer": bool(offer),
        "paid": paid,
        "price": float(offer.get("price") or 0) if offer else 0,
        "msgs_before": msgs_before,
        "draft_changed": (draft or "").strip() != (final or "").strip(),
        "failures": fails,
        "hard_fails": sum(1 for f in fails if int(f.get("severity") or 0) >= 3),
        "soft_fails": sum(1 for f in fails if int(f.get("severity") or 0) == 2),
        "warns": sum(1 for f in fails if int(f.get("severity") or 0) == 1),
    }


def run_scenario(scenario: dict, *, run_idx: int = 0) -> Dict[str, Any]:
    sid = scenario["id"]
    handle = scenario["handle"]
    fan_uuid = _sim_uuid(sid, run_idx)
    history: List[Dict[str, str]] = []
    turns_out: List[Dict[str, Any]] = []

    print(f"\n{'='*60}")
    print(f"SCENARIO {sid}  run={run_idx+1}  @{handle}")
    print(f"goal: {scenario.get('goal')}")
    print(f"fan_uuid={fan_uuid}")

    for i, t in enumerate(scenario["turns"]):
        fan_msg = t["fan"]
        print(f"\n--- turn {i+1}/{len(scenario['turns'])} ---")
        if t.get("note"):
            print(f"  note: {t['note']}")
        print(f"  FAN: {fan_msg}")
        try:
            row = _run_turn(
                fan_uuid=fan_uuid,
                handle=handle,
                fan_message=fan_msg,
                history=list(history),
                offer=t.get("offer"),
                ppv_status=t.get("ppv_status"),
                delivery_truth=t.get("delivery_truth"),
                fan_vision=t.get("fan_vision"),
            )
        except Exception as exc:
            row = {
                "fan": fan_msg,
                "reply": "",
                "error": f"{type(exc).__name__}: {exc}",
                "failures": [
                    {
                        "rule": "CRASH",
                        "severity": 3,
                        "what": f"{type(exc).__name__}: {exc}",
                    }
                ],
                "hard_fails": 1,
                "soft_fails": 0,
            }
            print(f"  CRASH: {row['error']}")
            turns_out.append(row)
            break

        print(f"  EMMA: {(row.get('reply') or '')[:180]}")
        print(
            f"  meta: pack={row.get('pack_id')} tech={row.get('technique')} "
            f"paid={row.get('paid')} changed={row.get('draft_changed')}"
        )
        if row["failures"]:
            for f in row["failures"]:
                print(f"  ⚠ [{f.get('severity')}] {f.get('rule')}: {f.get('what')}")
        else:
            print("  ✓ no detector hits")

        history.append({"role": "user", "content": fan_msg})
        if row.get("reply"):
            history.append({"role": "assistant", "content": row["reply"]})
        turns_out.append(row)

    hard = sum(int(t.get("hard_fails") or 0) for t in turns_out)
    soft = sum(int(t.get("soft_fails") or 0) for t in turns_out)
    warns = sum(int(t.get("warns") or 0) for t in turns_out)
    return {
        "scenario_id": sid,
        "handle": handle,
        "goal": scenario.get("goal"),
        "run": run_idx + 1,
        "fan_uuid": fan_uuid,
        "turns": turns_out,
        "hard_fails": hard,
        "soft_fails": soft,
        "warns": warns,
        "ok": hard == 0,
        "mode": "scripted",
        "score": None,
        "unlocked": False,
    }


def run_llm_archetype(name: str, *, run_idx: int = 0) -> Dict[str, Any]:
    """Multi-turn chat: LLM fan ↔ live Emma path + end score."""
    arch = get_archetype(name)
    if not arch:
        raise ValueError(f"unknown archetype: {name}")

    handle = arch["handle"]
    fan_uuid = _sim_uuid(f"llm-{name}", run_idx)
    history: List[Dict[str, str]] = []
    turns_out: List[Dict[str, Any]] = []
    pending_lock: Optional[dict] = None
    already_free = False
    already_paid = False
    unlocked = False
    left = False
    max_turns = int(arch.get("turns") or 7)

    print(f"\n{'='*60}")
    print(f"LLM-FAN {name}  run={run_idx+1}  @{handle}")
    print(f"brief: {(arch.get('brief') or '')[:120]}…")
    print(f"fan_uuid={fan_uuid}")

    emma_last = ""
    fan_text = str(arch.get("open") or "hey")
    fan_action = "chat"

    for i in range(max_turns):
        if i > 0:
            try:
                nxt = next_fan_message(
                    archetype=arch,
                    history=history,
                    emma_last=emma_last,
                    pending_lock=pending_lock,
                    turn_index=i,
                )
            except Exception as exc:
                print(f"  FAN-LLM CRASH: {exc}")
                break
            fan_text = nxt["text"]
            fan_action = nxt["action"]
            print(
                f"\n--- turn {i+1}/{max_turns} --- "
                f"fan_action={fan_action} ({nxt.get('reason')})"
            )
        else:
            print(f"\n--- turn {i+1}/{max_turns} --- fan_action=open")

        if fan_action == "leave":
            print(f"  FAN LEFT: {fan_text}")
            left = True
            turns_out.append(
                {
                    "fan": fan_text,
                    "reply": "",
                    "fan_action": "leave",
                    "failures": [],
                    "hard_fails": 0,
                    "soft_fails": 0,
                    "warns": 0,
                }
            )
            history.append({"role": "user", "content": fan_text})
            break

        if fan_action == "unlock" and pending_lock:
            unlocked = True
            print(f"  FAN UNLOCKED ${pending_lock.get('price')}: {fan_text}")
            # Mirror real purchase webhook so reward path isn't "nothing waiting"
            try:
                fan_memory.record_purchase(
                    fan_uuid,
                    float(pending_lock.get("price") or 0),
                    fan_handle=handle,
                )
                fan_memory.mark_ppv_purchased(
                    fan_uuid,
                    str(pending_lock.get("media_uuid") or ""),
                    fan_handle=handle,
                    label=str(pending_lock.get("label") or ""),
                    level=int(pending_lock.get("level") or 0) or None,
                    price=float(pending_lock.get("price") or 0),
                )
            except Exception as exc:
                print(f"  (purchase memory warn: {exc})")
            ppv_status = {"active": False, "purchased": True}
            delivery_truth = {"ppv_unpaid": False}
            offer = None
            pending_lock = None
            fan_vision = None
        elif fan_action == "reject" and pending_lock:
            print(f"  FAN REJECTS lock: {fan_text}")
            ppv_status = {"active": True, "purchased": False}
            delivery_truth = {"ppv_unpaid": True}
            offer = None
            fan_vision = None
        else:
            ppv_status = (
                {"active": True, "purchased": False} if pending_lock else None
            )
            delivery_truth = (
                {"ppv_unpaid": True} if pending_lock else None
            )
            fan_vision = (
                fan_vision_for_selfie() if fan_action == "send_photo" else None
            )
            offer = maybe_attach_offer(
                turn_index=i,
                fan_text=fan_text,
                pending_lock=pending_lock,
                already_free=already_free,
                already_paid=already_paid,
                archetype=arch,
            )
            if offer:
                if float(offer.get("price") or 0) > 0:
                    already_paid = True
                    pending_lock = dict(offer)
                    ppv_status = {"active": True, "purchased": False}
                    delivery_truth = {"ppv_unpaid": True}
                    try:
                        fan_memory.set_last_offer(
                            fan_uuid,
                            price=float(offer.get("price") or 0),
                            fan_handle=handle,
                            level=int(offer.get("level") or 0) or None,
                            media_uuid=str(offer.get("media_uuid") or ""),
                            label=str(offer.get("label") or ""),
                        )
                    except Exception as exc:
                        print(f"  (offer memory warn: {exc})")
                else:
                    already_free = True

        print(f"  FAN: {fan_text}")
        if offer:
            print(
                f"  [sim attach] L{offer.get('level')} "
                f"${offer.get('price')} {offer.get('label')}"
            )

        try:
            row = _run_turn(
                fan_uuid=fan_uuid,
                handle=handle,
                fan_message=fan_text,
                history=list(history),
                offer=offer,
                ppv_status=ppv_status,
                delivery_truth=delivery_truth,
                fan_vision=fan_vision,
            )
        except Exception as exc:
            row = {
                "fan": fan_text,
                "reply": "",
                "error": f"{type(exc).__name__}: {exc}",
                "failures": [
                    {
                        "rule": "CRASH",
                        "severity": 3,
                        "what": f"{type(exc).__name__}: {exc}",
                    }
                ],
                "hard_fails": 1,
                "soft_fails": 0,
                "warns": 0,
            }
            print(f"  CRASH: {row['error']}")
            turns_out.append(row)
            break

        row["fan_action"] = fan_action
        row["unlocked_this_turn"] = fan_action == "unlock"
        print(f"  EMMA: {(row.get('reply') or '')[:180]}")
        print(
            f"  meta: pack={row.get('pack_id')} tech={row.get('technique')} "
            f"paid={row.get('paid')} changed={row.get('draft_changed')}"
        )
        if row["failures"]:
            for f in row["failures"]:
                print(f"  ⚠ [{f.get('severity')}] {f.get('rule')}: {f.get('what')}")
        else:
            print("  ✓ no detector hits")

        history.append({"role": "user", "content": fan_text})
        if row.get("reply"):
            history.append({"role": "assistant", "content": row["reply"]})
            emma_last = row["reply"]
        turns_out.append(row)

    hard = sum(int(t.get("hard_fails") or 0) for t in turns_out)
    soft = sum(int(t.get("soft_fails") or 0) for t in turns_out)
    warns = sum(int(t.get("warns") or 0) for t in turns_out)

    print("\n  scoring chat…")
    score = score_chat(
        archetype_brief=str(arch.get("brief") or ""),
        history=history,
        unlocked=unlocked,
        hard_fails=hard,
        soft_fails=soft,
    )
    print(
        f"  SCORE avg={score.get('avg')} "
        f"hook={score.get('hook')} human={score.get('human')} "
        f"sell={score.get('sell')} temp={score.get('fan_temperature')}"
    )
    print(f"  verdict: {score.get('verdict')}")
    if score.get("killers"):
        print(f"  killers: {', '.join(score['killers'])}")

    avg = float(score.get("avg") or 0)
    return {
        "scenario_id": f"llm:{name}",
        "handle": handle,
        "goal": (arch.get("brief") or "")[:80],
        "run": run_idx + 1,
        "fan_uuid": fan_uuid,
        "turns": turns_out,
        "hard_fails": hard,
        "soft_fails": soft,
        "warns": warns,
        "ok": hard == 0 and avg >= 6.0 and not left,
        "mode": "llm-fan",
        "score": score,
        "unlocked": unlocked,
        "left": left,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Mass offline Emma chat simulator")
    ap.add_argument("--list", action="store_true", help="List scenario / archetype ids")
    ap.add_argument(
        "--llm-fan",
        action="store_true",
        help="LLM plays the fan (realistic) + engagement score",
    )
    ap.add_argument(
        "--scenario",
        "-s",
        action="append",
        default=[],
        help="Scripted scenario id (repeatable)",
    )
    ap.add_argument(
        "--archetype",
        "-a",
        action="append",
        default=[],
        help="LLM fan archetype id (with --llm-fan)",
    )
    ap.add_argument("--runs", type=int, default=1, help="Repeats per scenario")
    ap.add_argument("--json", type=str, default="", help="Write full report JSON")
    ap.add_argument(
        "--fail-soft",
        action="store_true",
        help="Exit non-zero on soft fails too (default: hard only)",
    )
    ap.add_argument(
        "--min-avg",
        type=float,
        default=6.0,
        help="With --llm-fan, treat avg score below this as failure (default 6)",
    )
    args = ap.parse_args()

    if args.list:
        print("SCRIPTED:")
        for s in SCENARIOS:
            print(f"  {s['id']:20}  {s['goal']}")
        print("LLM-FAN (--llm-fan -a …):")
        for name in list_archetypes():
            a = get_archetype(name) or {}
            print(f"  {name:20}  {(a.get('brief') or '')[:70]}")
        return 0

    if not (os.getenv("DEEPSEEK_API_KEY") or "").strip():
        print("❌ DEEPSEEK_API_KEY missing")
        return 2

    reports: List[Dict[str, Any]] = []
    t0 = time.time()

    if args.llm_fan:
        chosen = args.archetype or list_archetypes()
        for name in chosen:
            if not get_archetype(name):
                print(f"❌ unknown archetype: {name}")
                return 2
            for r in range(max(1, args.runs)):
                rep = run_llm_archetype(name, run_idx=r)
                # Re-apply min-avg threshold from CLI
                avg = float((rep.get("score") or {}).get("avg") or 0)
                rep["ok"] = (
                    rep["hard_fails"] == 0
                    and avg >= float(args.min_avg)
                    and not rep.get("left")
                )
                reports.append(rep)
    else:
        chosen = args.scenario or list_scenario_ids()
        for sid in chosen:
            sc = get_scenario(sid)
            if not sc:
                print(f"❌ unknown scenario: {sid}")
                return 2
            for r in range(max(1, args.runs)):
                reports.append(run_scenario(sc, run_idx=r))

    hard_total = sum(r["hard_fails"] for r in reports)
    soft_total = sum(r["soft_fails"] for r in reports)
    warn_total = sum(r.get("warns") or 0 for r in reports)
    ok_n = sum(1 for r in reports if r["ok"])
    unlocked_n = sum(1 for r in reports if r.get("unlocked"))
    avgs = [
        float((r.get("score") or {}).get("avg") or 0)
        for r in reports
        if r.get("score")
    ]
    elapsed = time.time() - t0

    print(f"\n{'='*60}")
    print(
        f"DONE {ok_n}/{len(reports)} clean | "
        f"hard={hard_total} soft={soft_total} warn={warn_total} "
        f"unlocked={unlocked_n}"
        + (f" avg_score={sum(avgs)/len(avgs):.1f}" if avgs else "")
        + f" | {elapsed:.1f}s"
    )
    for r in reports:
        flag = "OK" if r["ok"] else "FAIL"
        sc = r.get("score") or {}
        extra = ""
        if sc:
            extra = (
                f" avg={sc.get('avg')} hook={sc.get('hook')} "
                f"human={sc.get('human')} sell={sc.get('sell')} "
                f"unlock={r.get('unlocked')}"
            )
        print(
            f"  [{flag}] {r['scenario_id']} run={r['run']} "
            f"hard={r['hard_fails']} soft={r['soft_fails']} "
            f"warn={r.get('warns') or 0}{extra}"
        )

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mode": "llm-fan" if args.llm_fan else "scripted",
        "scenarios": reports,
        "summary": {
            "runs": len(reports),
            "ok": ok_n,
            "hard_fails": hard_total,
            "soft_fails": soft_total,
            "warns": warn_total,
            "unlocked": unlocked_n,
            "avg_score": round(sum(avgs) / len(avgs), 2) if avgs else None,
            "seconds": round(elapsed, 2),
        },
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {out}")

    art = Path("/opt/cursor/artifacts")
    if art.is_dir() and not args.json:
        p = art / f"sim_mass_{int(time.time())}.json"
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {p}")

    if hard_total:
        return 1
    if args.llm_fan and any(not r["ok"] for r in reports):
        return 1
    if args.fail_soft and soft_total:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
