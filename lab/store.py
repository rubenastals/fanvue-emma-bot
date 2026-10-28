"""SQLite persistence separate from all production stores; atomic revision checks."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Callable


class Conflict(Exception):
    pass


class NotFound(Exception):
    pass


class LabStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    comparison_id TEXT NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS candidate_session ON candidates(session_id);
                CREATE INDEX IF NOT EXISTS candidate_comparison ON candidates(comparison_id);
                CREATE TABLE IF NOT EXISTS ratings(candidate_id TEXT PRIMARY KEY, data TEXT NOT NULL);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=20)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _session(db, sid: str) -> dict:
        row = db.execute("SELECT data FROM sessions WHERE id=?", (sid,)).fetchone()
        if not row:
            raise NotFound("Sesión no encontrada.")
        return json.loads(row[0])

    @staticmethod
    def _write(db, state: dict) -> None:
        db.execute("UPDATE sessions SET data=? WHERE id=?", (json.dumps(state, ensure_ascii=False), state["id"]))

    def create(self, state: dict) -> dict:
        with self.connection() as db:
            db.execute("INSERT INTO sessions VALUES (?,?)", (state["id"], json.dumps(state, ensure_ascii=False)))
        return state

    def get(self, sid: str) -> dict:
        with self.connection() as db:
            return self._session(db, sid)

    def list_sessions(self) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT s.data, (SELECT COUNT(DISTINCT c.comparison_id) FROM candidates c WHERE c.session_id=s.id) FROM sessions s ORDER BY s.rowid DESC LIMIT 200").fetchall()
            summaries = []
            for raw, count in rows:
                state = json.loads(raw)
                summaries.append({"id": state["id"], "scenario_id": state["scenario_id"], "revision": state["revision"],
                                  "fan_name": state["fan"]["name"], "created_at": state.get("created_at"), "comparison_count": count})
            return summaries

    def mutate(self, sid: str, expected: int, update: Callable, event: dict | None = None) -> dict:
        with self.connection() as db:
            state = self._session(db, sid)
            if event and event.get("id"):
                previous = next((e for e in state["events"] if e.get("id") == event["id"]), None)
                if previous:
                    if previous != event:
                        raise Conflict("Identificador de evento reutilizado con otros datos.")
                    return state
            if state["revision"] != expected:
                raise Conflict("La conversación ha cambiado. Recarga antes de continuar.")
            update(state)
            state["revision"] += 1
            if event:
                state["events"].append(event)
            self._write(db, state)
            return state

    def save_candidates(self, candidates: list[dict]) -> None:
        with self.connection() as db:
            for c in candidates:
                db.execute("INSERT INTO candidates VALUES (?,?,?,?)", (c["id"], c["session_id"], c["comparison_id"], json.dumps(c, ensure_ascii=False)))

    def candidates(self, sid: str | None = None, comparison_id: str | None = None) -> list[dict]:
        sql, values = "SELECT data FROM candidates", ()
        if sid:
            sql, values = sql + " WHERE session_id=?", (sid,)
        elif comparison_id:
            sql, values = sql + " WHERE comparison_id=?", (comparison_id,)
        with self.connection() as db:
            return [json.loads(r[0]) for r in db.execute(sql, values).fetchall()]

    def candidate(self, cid: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT data FROM candidates WHERE id=?", (cid,)).fetchone()
            if not row:
                raise NotFound("Candidato no encontrado.")
            return json.loads(row[0])

    def review(self, sid: str, cid: str, expected: int, action: str, update: Callable) -> dict:
        with self.connection() as db:
            state = self._session(db, sid)
            row = db.execute("SELECT data FROM candidates WHERE id=? AND session_id=?", (cid, sid)).fetchone()
            if not row:
                raise NotFound("Candidato no encontrado en esta sesión.")
            c = json.loads(row[0])
            if state["revision"] != expected or c["revision"] != expected:
                raise Conflict("Borrador obsoleto: el estado cambió después de generarlo.")
            if c["review"] != "pending":
                raise Conflict("Este candidato ya se ha revisado.")
            if action == "approve":
                if state["paused"] or state["memory"]["commerce"].get("no_contact"):
                    raise Conflict("El control humano o la petición de no contacto bloquea la aprobación.")
                if c["status"] != "ready":
                    raise Conflict("Un candidato incompleto o con error no puede aprobarse.")
                update(state, c)
                state["revision"] += 1
                self._write(db, state)
            c["review"] = "approved" if action == "approve" else "rejected"
            db.execute("UPDATE candidates SET data=? WHERE id=?", (json.dumps(c, ensure_ascii=False), cid))
            return state

    def reveal(self, comparison_id: str) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT id,data FROM candidates WHERE comparison_id=?", (comparison_id,)).fetchall()
            if not rows:
                raise NotFound("Comparación no encontrada.")
            result = []
            for cid, data in rows:
                c = json.loads(data)
                c["revealed"] = True
                db.execute("UPDATE candidates SET data=? WHERE id=?", (json.dumps(c, ensure_ascii=False), cid))
                result.append(c)
            return result

    def rate(self, cid: str, scores: dict, notes: str) -> None:
        with self.connection() as db:
            row = db.execute("SELECT data FROM candidates WHERE id=?", (cid,)).fetchone()
            if not row:
                raise NotFound("Candidato no encontrado.")
            c = json.loads(row[0])
            if c["is_fixture"] or c["status"] != "ready":
                raise Conflict("Solo se puntúan respuestas completas de modelos reales.")
            rating = {"candidate_id": cid, "scores": scores, "notes": notes, "blind_at_rating": not c["revealed"]}
            db.execute("INSERT INTO ratings VALUES (?,?) ON CONFLICT(candidate_id) DO UPDATE SET data=excluded.data", (cid, json.dumps(rating, ensure_ascii=False)))

    def export(self) -> dict:
        with self.connection() as db:
            return {"schema_version": 1, "sessions": [json.loads(r[0]) for r in db.execute("SELECT data FROM sessions")],
                    "candidates": [json.loads(r[0]) for r in db.execute("SELECT data FROM candidates")],
                    "ratings": [json.loads(r[0]) for r in db.execute("SELECT data FROM ratings")]}
