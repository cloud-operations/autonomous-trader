#!/usr/bin/env python3
"""Show recent game-state snapshots without confusing historical and final state."""
import sqlite3
from pathlib import Path

DB = Path("data/game_states.db")
if not DB.exists():
    raise SystemExit("No game-state database yet. Run collect_game_states.py --once first.")
with sqlite3.connect(DB) as conn:
    conn.row_factory = sqlite3.Row
    count = conn.execute("SELECT COUNT(*) FROM game_states").fetchone()[0]
    print(f"=== GAME INTELLIGENCE V2 ===\nSnapshots saved: {count}")
    rows = conn.execute("""
        SELECT sport, game_id, fetched_at, status, period, clock,
               away_team, away_score, home_team, home_score
        FROM game_states
        ORDER BY fetched_at DESC, id DESC LIMIT 15
    """).fetchall()
    for r in rows:
        print(f"{r['fetched_at']} | {r['sport']} | {r['away_team']} {r['away_score']}"
              f" @ {r['home_team']} {r['home_score']} | {r['status']}"
              f" | period={r['period']} clock={r['clock']} | game={r['game_id']}")
print("Note: Each row is the scoreboard state observed at fetched_at, not an earlier historical state.")
