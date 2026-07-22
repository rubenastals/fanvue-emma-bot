#!/usr/bin/env python3
"""
Mass offline chat simulator — no Fanvue accounts.

Runs the LIVE path: assemble → DeepSeek → sanitize → detectors.
Catches scheme / caption / early-guilt / ENGLISH_ONLY failures fast.

Usage:
  python scripts/sim_mass.py                       # all scenarios, 1 run each
  python scripts/sim_mass.py --scenario new_horny_en --runs 3
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
from core.sim_scenarios import SCENARIOS, get_scenario, list_scenario_ids


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
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Mass offline Emma chat simulator")
    ap.add_argument("--list", action="store_true", help="List scenario ids")
    ap.add_argument(
        "--scenario",
        "-s",
        action="append",
        default=[],
        help="Scenario id (repeatable). Default: all",
    )
    ap.add_argument("--runs", type=int, default=1, help="Repeats per scenario")
    ap.add_argument("--json", type=str, default="", help="Write full report JSON")
    ap.add_argument(
        "--fail-soft",
        action="store_true",
        help="Exit non-zero on soft fails too (default: hard only)",
    )
    args = ap.parse_args()

    if args.list:
        for s in SCENARIOS:
            print(f"{s['id']:20}  {s['goal']}")
        return 0

    if not (os.getenv("DEEPSEEK_API_KEY") or "").strip():
        print("❌ DEEPSEEK_API_KEY missing")
        return 2

    chosen = args.scenario or list_scenario_ids()
    reports: List[Dict[str, Any]] = []
    t0 = time.time()

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
    elapsed = time.time() - t0

    print(f"\n{'='*60}")
    print(
        f"DONE {ok_n}/{len(reports)} scenarios clean (hard=0) | "
        f"hard={hard_total} soft={soft_total} warn={warn_total} | {elapsed:.1f}s"
    )
    for r in reports:
        flag = "OK" if r["ok"] else "FAIL"
        print(
            f"  [{flag}] {r['scenario_id']} run={r['run']} "
            f"hard={r['hard_fails']} soft={r['soft_fails']} warn={r.get('warns') or 0}"
        )

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "scenarios": reports,
        "summary": {
            "runs": len(reports),
            "ok": ok_n,
            "hard_fails": hard_total,
            "soft_fails": soft_total,
            "warns": warn_total,
            "seconds": round(elapsed, 2),
        },
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {out}")

    # Also drop a copy under artifacts when present
    art = Path("/opt/cursor/artifacts")
    if art.is_dir() and not args.json:
        p = art / f"sim_mass_{int(time.time())}.json"
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {p}")

    if hard_total:
        return 1
    if args.fail_soft and soft_total:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
