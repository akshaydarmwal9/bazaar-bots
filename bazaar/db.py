"""SQLite log of every run and every message (data/bazaar.db)."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .config import ROOT

DB_PATH = ROOT / "data" / "bazaar.db"


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, request TEXT, strategy TEXT,
        budget INTEGER, best_store TEXT, best_price INTEGER, lazy_price INTEGER,
        savings INTEGER, providers TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS turns (
        run_id INTEGER, store_id TEXT, round INTEGER, sender TEXT, action TEXT,
        price INTEGER, claim_price INTEGER, extras TEXT, note TEXT, message TEXT)""")
    return c


def save_run(summary) -> int:
    with _conn() as c:
        best = summary.best
        cur = c.execute(
            "INSERT INTO runs (ts, request, strategy, budget, best_store, best_price, lazy_price, savings, providers)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (time.time(), summary.needs.raw, summary.strategy, summary.needs.budget,
             best.store_name if best else None, best.final_price if best else None,
             summary.lazy_price, summary.savings_vs_lazy, json.dumps(summary.providers_used)),
        )
        run_id = cur.lastrowid
        for r in summary.results:
            for t in r.turns:
                c.execute("INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (run_id, r.store_id, t.round, t.sender, t.action, t.price, t.claim_price,
                           json.dumps(t.extras), t.note, t.message))
        return run_id
