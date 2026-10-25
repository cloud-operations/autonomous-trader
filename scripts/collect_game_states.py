#!/usr/bin/env python3
"""Read-only ESPN scoreboard snapshot collector; unofficial endpoint."""
import argparse
import json
import sqlite3
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SPORTS = {"NHL": ("hockey", "nhl"), "NBA": ("basketball", "nba"), "NFL": ("football", "nfl")}
DB = Path("data/game_states.db")


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS game_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fetched_at TEXT NOT NULL,
        sport TEXT NOT NULL,
        game_id TEXT NOT NULL,
        game_date TEXT,
        status TEXT,
        status_name TEXT,
        period INTEGER,
        clock TEXT,
        home_team TEXT,
        home_abbr TEXT,
        home_score TEXT,
        away_team TEXT,
        away_abbr TEXT,
        away_score TEXT
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_game_states_game_time ON game_states(sport, game_id, fetched_at)")
    conn.commit()
    return conn


def fetch(sport, date):
    category, league = SPORTS[sport]
    url = f"https://site.api.espn.com/apis/site/v2/sports/{category}/{league}/scoreboard?dates={date}"
    req = urllib.request.Request(url, headers={"User-Agent": "autonomous-trader-score-collector/0.1"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response).get("events", [])


def collect_once(conn):
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    inserted = 0
    errors = []
    # Include UTC yesterday for games that began before midnight.
    dates = {(now + timedelta(days=offset)).strftime("%Y%m%d") for offset in (-1, 0)}
    for sport in SPORTS:
        for date in sorted(dates):
            try:
                events = fetch(sport, date)
                for event in events:
                    competitions = event.get("competitions") or []
                    if not competitions:
                        continue
                    sides = {}
                    for item in competitions[0].get("competitors", []):
                        role = item.get("homeAway")
                        if role in ("home", "away"):
                            team = item.get("team") or {}
                            sides[role] = (team.get("displayName"), team.get("abbreviation"), item.get("score"))
                    if not sides:
                        continue
                    home = sides.get("home", (None, None, None))
                    away = sides.get("away", (None, None, None))
                    status = event.get("status") or {}
                    status_type = status.get("type") or {}
                    conn.execute("""INSERT INTO game_states (
                        fetched_at, sport, game_id, game_date, status, status_name,
                        period, clock, home_team, home_abbr, home_score,
                        away_team, away_abbr, away_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                        stamp, sport, str(event.get("id", "")), event.get("date"),
                        status_type.get("description"), status_type.get("name"),
                        status.get("period"), status.get("displayClock"),
                        *home, *away
                    ))
                    inserted += 1
                conn.commit()
            except Exception as exc:
                errors.append(f"{sport}/{date}: {exc}")
    return stamp, inserted, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()
    if args.interval < 60:
        parser.error("interval must be at least 60 seconds")
    with connect() as conn:
        print(f"Score collector started; DB={DB}; interval={args.interval}s", flush=True)
        while True:
            stamp, inserted, errors = collect_once(conn)
            print(f"{stamp} snapshots={inserted} errors={len(errors)}", flush=True)
            for error in errors:
                print(f"WARNING {error}", flush=True)
            if args.once:
                break
            time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Score collector stopped", flush=True)
