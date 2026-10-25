#!/usr/bin/env python3
"""Read-only Kalshi NHL order-book collector. Never places orders."""
import argparse
import json
import logging
import signal
import re
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from trader.providers.sports_markets import BASE_URL, SportsMarketProvider

STOP = False


def stop_handler(_signum, _frame):
    global STOP
    STOP = True


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def validate_levels(raw, side):
    if not isinstance(raw, list):
        raise ValueError(f"{side} must be a list")
    levels = []
    for i, item in enumerate(raw):
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(f"invalid {side} level {i}: {item!r}")
        try:
            price, quantity = Decimal(str(item[0])), Decimal(str(item[1]))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"invalid decimal at {side} level {i}") from exc
        if not (Decimal(0) < price < Decimal(1) and quantity >= 0 and price.is_finite() and quantity.is_finite()):
            raise ValueError(f"invalid values at {side} level {i}")
        levels.append((str(price), str(quantity)))
    return levels


def setup_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=20)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS orderbook_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recorded_at TEXT NOT NULL,
        ticker TEXT NOT NULL,
        status TEXT NOT NULL,
        yes_bid TEXT,
        yes_ask TEXT,
        raw_json TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS orderbook_levels (
        snapshot_id INTEGER NOT NULL,
        side TEXT NOT NULL,
        price_dollars TEXT NOT NULL,
        quantity TEXT NOT NULL,
        PRIMARY KEY (snapshot_id, side, price_dollars),
        FOREIGN KEY (snapshot_id) REFERENCES orderbook_snapshots(id)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orderbook_ticker_time ON orderbook_snapshots(ticker, recorded_at)")
    conn.commit()
    return conn


def save_book(conn, ticker, payload, timestamp):
    book = payload.get("orderbook_fp")
    if not isinstance(book, dict):
        raise ValueError("missing orderbook_fp")
    yes = validate_levels(book.get("yes_dollars"), "yes_dollars")
    no = validate_levels(book.get("no_dollars"), "no_dollars")
    yes_bid = max((Decimal(p) for p, _ in yes), default=None)
    no_bid = max((Decimal(p) for p, _ in no), default=None)
    yes_ask = Decimal(1) - no_bid if no_bid is not None else None
    if yes_bid is not None and yes_ask is not None and yes_bid > yes_ask:
        raise ValueError("crossed derived YES market")
    with conn:
        cur = conn.execute("""INSERT INTO orderbook_snapshots
            (recorded_at, ticker, status, yes_bid, yes_ask, raw_json)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (timestamp, ticker, "OK", str(yes_bid) if yes_bid is not None else None,
             str(yes_ask) if yes_ask is not None else None, json.dumps(payload, separators=(",", ":"))))
        sid = cur.lastrowid
        conn.executemany("INSERT INTO orderbook_levels VALUES (?, ?, ?, ?)",
                         [(sid, "YES_BID", p, q) for p, q in yes] +
                         [(sid, "NO_BID", p, q) for p, q in no])
    return len(yes), len(no)



def select_game_events(score_db, events, now, max_age_seconds=180, upcoming_hours=3, live_hours=5):
    """Select only fresh, current NHL games; never infer LIVE from clock alone."""
    with sqlite3.connect(f"file:{Path(score_db).resolve()}?mode=ro", uri=True) as db:
        rows = db.execute("""
            SELECT g.game_id, g.game_date, g.away_abbr, g.home_abbr,
                   g.status_name, g.fetched_at
            FROM game_states g
            JOIN (SELECT game_id, MAX(id) latest_id FROM game_states
                  WHERE UPPER(sport)='NHL' GROUP BY game_id) latest
              ON g.id=latest.latest_id
            WHERE UPPER(g.sport)='NHL'
        """).fetchall()
    event_map = {e.get("event_ticker"): e for e in events}
    selected, diagnostics = [], []
    for gid, start_str, away, home, status, fetched in rows:
        if not all((start_str, away, home, status, fetched)):
            continue
        try:
            start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            observed = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
        except ValueError:
            continue
        age = (now - observed).total_seconds()
        if not (0 <= age <= max_age_seconds):
            continue
        delta_h = (start - now).total_seconds() / 3600
        state = str(status).upper()
        if "FINAL" in state or "POSTPONED" in state or "CANCEL" in state:
            continue
        if state == "STATUS_SCHEDULED":
            if not (0 <= delta_h <= upcoming_hours):
                continue
            priority = 1
        else:
            if not (-live_hours <= delta_h <= 0):
                continue
            priority = 0
        # Kalshi NHL ticker date is US Eastern calendar date of puck drop.
        local_date = start.astimezone(ZoneInfo("America/New_York")).strftime("%y%b%d").upper()
        key = f"KXNHLGAME-{local_date}{away}{home}"
        event = event_map.get(key)
        if not event:
            diagnostics.append(f"NO_EVENT {away}@{home} expected={key} status={status}")
            continue
        markets = [m.get("ticker") for m in event.get("markets", [])
                   if m.get("status") in ("active", "open") and isinstance(m.get("ticker"), str)]
        if len(markets) != 2 or len(set(markets)) != 2:
            diagnostics.append(f"INCOMPLETE_PAIR {key} count={len(markets)}")
            continue
        selected.append((priority, abs(delta_h), key, markets, status, age))
    selected.sort(key=lambda x: (x[0], x[1], x[2]))
    return selected, diagnostics


def main():
    parser = argparse.ArgumentParser(description="Read-only NHL orderbook collector")
    parser.add_argument("--db", default="data/nhl_orderbook.db")
    parser.add_argument("--interval", type=int, default=120)
    parser.add_argument("--max-markets", type=int, default=12)
    parser.add_argument("--request-delay", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--score-db", default="data/game_states.db")
    parser.add_argument("--max-status-age", type=int, default=180)
    parser.add_argument("--upcoming-hours", type=float, default=3.0)
    parser.add_argument("--live-hours", type=float, default=5.0)
    parser.add_argument("--dry-run", action="store_true", help="Print selected games; do not fetch depth or write DB")
    args = parser.parse_args()
    if args.interval < 60 or args.max_markets < 1 or args.request_delay < 0.5:
        parser.error("interval >=60, max-markets >=1, request-delay >=0.5 required")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    provider = SportsMarketProvider()
    conn = None if args.dry_run else setup_db(Path(args.db))
    try:
        while not STOP:
            started = time.monotonic()
            try:
                events = provider.get_events("KXNHLGAME")
                games, diagnostics = select_game_events(
                    args.score_db, events, datetime.now(timezone.utc),
                    max_age_seconds=args.max_status_age,
                    upcoming_hours=args.upcoming_hours,
                    live_hours=args.live_hours)
                for detail in diagnostics:
                    logging.warning("%s", detail)
                tickers = []
                for priority, hours, key, pair, status, age in games:
                    if len(tickers) + 2 > args.max_markets:
                        break
                    logging.info("SELECT %s %s status=%s status_age=%.0fs", key, pair, status, age)
                    tickers.extend(pair)
                logging.info("Selected %s complete games / %s contracts", len(tickers)//2, len(tickers))
                if args.dry_run:
                    break
                for i, ticker in enumerate(tickers):
                    if STOP:
                        break
                    try:
                        response = provider.session.get(
                            f"{BASE_URL}/markets/{ticker}/orderbook",
                            params={"depth": 5}, timeout=20)
                        response.raise_for_status()
                        n_yes, n_no = save_book(conn, ticker, response.json(), utcnow())
                        logging.info("%s YES levels=%s NO levels=%s", ticker, n_yes, n_no)
                    except Exception as exc:
                        logging.warning("Orderbook failed for %s: %s", ticker, exc)
                    if i + 1 < len(tickers) and not STOP:
                        time.sleep(args.request_delay)
            except Exception:
                logging.exception("Discovery failed")
            if args.once:
                break
            remaining = args.interval - (time.monotonic() - started)
            while remaining > 0 and not STOP:
                step = min(1, remaining)
                time.sleep(step)
                remaining -= step
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
