#!/usr/bin/env python3
"""Read-only Kalshi NHL order-book collector. Never places orders."""
import argparse
import json
import logging
import signal
import sqlite3
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

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


def main():
    parser = argparse.ArgumentParser(description="Read-only NHL orderbook collector")
    parser.add_argument("--db", default="data/nhl_orderbook.db")
    parser.add_argument("--interval", type=int, default=120)
    parser.add_argument("--max-markets", type=int, default=12)
    parser.add_argument("--request-delay", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.interval < 60 or args.max_markets < 1 or args.request_delay < 0.5:
        parser.error("interval >=60, max-markets >=1, request-delay >=0.5 required")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    provider = SportsMarketProvider()
    conn = setup_db(Path(args.db))
    try:
        while not STOP:
            started = time.monotonic()
            try:
                events = provider.get_events("KXNHLGAME")
                candidates = []
                for event in events:
                    for market in event.get("markets", []):
                        ticker = market.get("ticker")
                        if isinstance(ticker, str) and ticker.startswith("KXNHLGAME-"):
                            candidates.append(ticker)
                tickers = list(dict.fromkeys(candidates))[:args.max_markets]
                logging.info("Discovered %s NHL tickers; checking %s", len(set(candidates)), len(tickers))
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
        conn.close()


if __name__ == "__main__":
    main()
