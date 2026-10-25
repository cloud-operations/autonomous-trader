import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class PriceHistory:
    def __init__(self, db_path="data/market_history.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS price_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at TEXT NOT NULL,
                    sport TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    event TEXT,
                    yes_bid REAL NOT NULL,
                    yes_ask REAL NOT NULL,
                    midpoint REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_price_ticker_time
                ON price_snapshots(ticker, recorded_at)
            """)

    def save_markets(self, markets):
        timestamp = datetime.now(timezone.utc).isoformat()
        rows = []

        for market in markets:
            bid = float(market["yes_bid"])
            ask = float(market["yes_ask"])

            if not (0 < bid <= ask < 1):
                continue

            rows.append((
                timestamp,
                market["sport"],
                market["ticker"],
                market["event"],
                bid,
                ask,
                (bid + ask) / 2,
            ))

        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("""
                INSERT INTO price_snapshots (
                    recorded_at, sport, ticker, event,
                    yes_bid, yes_ask, midpoint
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, rows)

        return len(rows)

    def summary(self):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("""
                SELECT
                    COUNT(*) AS snapshots,
                    COUNT(DISTINCT ticker) AS contracts,
                    MIN(recorded_at) AS first_snapshot,
                    MAX(recorded_at) AS last_snapshot
                FROM price_snapshots
            """).fetchone()

    def recent_prices(self, ticker, limit=10):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("""
                SELECT recorded_at, yes_bid, yes_ask, midpoint
                FROM price_snapshots
                WHERE ticker = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT ?
            """, (ticker, limit)).fetchall()
