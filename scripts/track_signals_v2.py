#!/usr/bin/env python3
"""Read-only signal tracker. Requires existing MomentumAgentV31 and SQLite snapshots."""
import argparse
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from trader.agents.momentum_v31 import MomentumAgentV31

PRICE_DB = Path('data/market_history.db')
GAME_DB = Path('data/game_states.db')
TRACKER_DB = Path('data/signal_tracker.db')


def utc_dt(value):
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def columns(conn, table):
    return {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}


def init_db():
    TRACKER_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(TRACKER_DB) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS signals (
            signal_id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            sport TEXT,
            event TEXT,
            detected_at TEXT NOT NULL,
            change_cents REAL,
            signal_midpoint REAL,
            signal_bid REAL,
            signal_ask REAL,
            correlation_status TEXT NOT NULL,
            game_snapshot_at TEXT,
            game_status TEXT,
            game_details TEXT,
            correlation_note TEXT,
            last_midpoint REAL,
            movement_since_signal_cents REAL,
            outcome TEXT NOT NULL DEFAULT 'PENDING',
            last_checked_at TEXT NOT NULL
        )''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker)')


def score_match(signal, max_age_seconds=360):
    """Fail closed: no game verification without a safe schema and reliable team match."""
    if not GAME_DB.exists():
        return ('NO_MATCH', None, None, None, 'Game-state database missing')
    with sqlite3.connect(GAME_DB) as db:
        db.row_factory = sqlite3.Row
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        candidates = [t for t in ('game_snapshots', 'game_states', 'score_snapshots') if t in tables]
        if not candidates:
            return ('UNVERIFIED', None, None, None, 'Unknown game-state table; no match assumed')
        for table in candidates:
            cols = columns(db, table)
            ts_col = next((x for x in ('fetched_at', 'recorded_at', 'observed_at') if x in cols), None)
            sport_col = next((x for x in ('sport', 'league') if x in cols), None)
            home_col = next((x for x in ('home_team', 'home_name') if x in cols), None)
            away_col = next((x for x in ('away_team', 'away_name') if x in cols), None)
            status_col = next((x for x in ('status', 'game_status', 'status_name') if x in cols), None)
            if not all((ts_col, sport_col, home_col, away_col, status_col)):
                continue
            rows = db.execute(f'SELECT * FROM {table} WHERE {sport_col}=? ORDER BY {ts_col} DESC LIMIT 1000', (signal['sport'],)).fetchall()
            event = str(signal['event']).lower()
            names = [p.strip() for p in event.split(' vs ')]
            if len(names) != 2:
                return ('UNVERIFIED', None, None, None, 'Cannot parse event teams')
            signal_time = utc_dt(signal['detected_at'])
            for r in rows:
                names_in_game = [str(r[home_col]).lower(), str(r[away_col]).lower()]
                if not all(any(n == full or n in full.split() or full.endswith(' ' + n) for full in names_in_game) for n in names):
                    continue
                snapshot_time = utc_dt(r[ts_col])
                delta = (signal_time - snapshot_time).total_seconds()
                if delta < 0:
                    continue
                if delta > max_age_seconds:
                    return ('STALE', str(r[ts_col]), str(r[status_col]), json.dumps(dict(r), default=str), f'Snapshot {int(delta)} seconds old')
                status = str(r[status_col]).lower()
                if not any(x in status for x in ('in progress', 'inprogress', 'live', 'halftime', 'in progress')):
                    return ('NOT_LIVE', str(r[ts_col]), str(r[status_col]), json.dumps(dict(r), default=str), 'Game not confirmed live')
                return ('MATCHED_LIVE_SNAPSHOT', str(r[ts_col]), str(r[status_col]), json.dumps(dict(r), default=str), f'Snapshot {int(delta)} seconds old; game state may have changed')
    return ('NO_MATCH', None, None, None, 'No matching prior game observation')


def latest_quotes():
    with sqlite3.connect(PRICE_DB) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('''SELECT p.* FROM price_snapshots p JOIN
            (SELECT ticker, MAX(id) AS max_id FROM price_snapshots GROUP BY ticker) x
            ON p.id=x.max_id''').fetchall()
        return {r['ticker']: dict(r) for r in rows}


def run_once(historical=False, min_change=10):
    init_db()
    signals = MomentumAgentV31().analyze(historical=historical, min_change_cents=min_change)
    quotes = latest_quotes()
    inserted = 0
    with sqlite3.connect(TRACKER_DB) as db:
        for s in signals:
            sid = s.get('signal_id') or f"{s['ticker']}|{s['start_time']}|{s['detected_at']}"
            exists = db.execute('SELECT 1 FROM signals WHERE signal_id=?', (sid,)).fetchone()
            if exists:
                continue
            status, snapshot_at, game_status, details, note = score_match(s)
            quote = quotes.get(s['ticker'])
            latest_mid = float(quote['midpoint']) if quote else None
            change = round((latest_mid - float(s['current_price'])) * 100, 2) if latest_mid is not None else None
            # Outcome is only a price observation, not a trading profit or sports result.
            outcome = 'PENDING' if change is None or abs(change) < 2 else ('PRICE_UP' if change > 0 else 'PRICE_DOWN')
            db.execute('''INSERT INTO signals (signal_id, ticker, sport, event, detected_at, change_cents, signal_midpoint, signal_bid, signal_ask, correlation_status, game_snapshot_at, game_status, game_details, correlation_note, last_midpoint, movement_since_signal_cents, outcome, last_checked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                sid, s['ticker'], s['sport'], s['event'], s['detected_at'],
                s['change_cents'], s['current_price'], s['bid_cents']/100,
                s['ask_cents']/100, status, snapshot_at, game_status, details,
                note, latest_mid, change, outcome, datetime.now(timezone.utc).isoformat()
            ))
            inserted += 1
        # Refresh existing signals from latest market snapshots.
        for sid, ticker, signal_price, detected_at in db.execute('SELECT signal_id,ticker,signal_midpoint,detected_at FROM signals').fetchall():
            q = quotes.get(ticker)
            if not q or utc_dt(q['recorded_at']) <= utc_dt(detected_at):
                continue
            mid = float(q['midpoint'])
            change = round((mid - float(signal_price)) * 100, 2)
            outcome = 'PENDING' if abs(change) < 2 else ('PRICE_UP' if change > 0 else 'PRICE_DOWN')
            db.execute('''UPDATE signals SET last_midpoint=?, movement_since_signal_cents=?, outcome=?, last_checked_at=? WHERE signal_id=?''',
                       (mid, change, outcome, datetime.now(timezone.utc).isoformat(), sid))
        db.commit()
        summary = db.execute('SELECT correlation_status, COUNT(*) FROM signals GROUP BY correlation_status').fetchall()
        total = db.execute('SELECT COUNT(*) FROM signals').fetchone()[0]
    print(f'Found={len(signals)} New={inserted} Tracked={total} Statuses={dict(summary)}', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--historical', action='store_true')
    parser.add_argument('--interval', type=int, default=300)
    parser.add_argument('--min-change', type=float, default=10)
    args = parser.parse_args()
    if args.interval < 60:
        parser.error('--interval must be at least 60 seconds')
    if args.once:
        run_once(historical=args.historical, min_change=args.min_change)
    else:
        print('Signal tracker started. Ctrl+C to stop.', flush=True)
        while True:
            try:
                run_once(historical=args.historical, min_change=args.min_change)
            except Exception:
                logging.exception('Tracker cycle failed')
            time.sleep(args.interval)


if __name__ == '__main__':
    main()
