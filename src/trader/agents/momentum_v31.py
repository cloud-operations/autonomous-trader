import sqlite3
from datetime import datetime, timezone


class MomentumAgentV31:
    def __init__(self, db_path="data/market_history.db"):
        self.db_path = db_path

    def analyze(self, historical=False, min_change_cents=10,
                max_spread_cents=10, max_gap_minutes=10,
                max_staleness_minutes=10):
        now = datetime.now(timezone.utc)
        signals = []

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM price_snapshots "
                "ORDER BY ticker, recorded_at, id"
            ).fetchall()

        groups = {}
        for row in rows:
            groups.setdefault(row["ticker"], []).append(row)

        for ticker, prices in groups.items():
            pairs = list(zip(prices[:-1], prices[1:]))
            if not historical:
                pairs = pairs[-1:]

            for previous, current in pairs:
                start = datetime.fromisoformat(
                    previous["recorded_at"]
                )
                end = datetime.fromisoformat(
                    current["recorded_at"]
                )
                gap = (end - start).total_seconds() / 60
                age = (now - end).total_seconds() / 60

                if not 0 < gap <= max_gap_minutes:
                    continue
                if not historical and age > max_staleness_minutes:
                    continue

                spread = (
                    current["yes_ask"] - current["yes_bid"]
                ) * 100
                if spread > max_spread_cents:
                    continue

                change = (
                    current["midpoint"] -
                    previous["midpoint"]
                ) * 100
                if abs(change) < min_change_cents:
                    continue

                signals.append({
                    "ticker": ticker,
                    "sport": current["sport"],
                    "event": current["event"],
                    "start_time": previous["recorded_at"],
                    "detected_at": current["recorded_at"],
                    "duration_minutes": round(gap, 2),
                    "previous_price": previous["midpoint"],
                    "current_price": current["midpoint"],
                    "change_cents": round(change, 2),
                    "direction": "UP" if change > 0 else "DOWN",
                    "bid_cents": round(
                        current["yes_bid"] * 100, 2
                    ),
                    "ask_cents": round(
                        current["yes_ask"] * 100, 2
                    ),
                    "spread_cents": round(spread, 2),
                    "requires_game_validation": abs(change) >= 10,
                    "signal_id": (
                        f"{ticker}|{previous['id']}|{current['id']}"
                    ),
                })

        return sorted(
            signals,
            key=lambda s: abs(s["change_cents"]),
            reverse=True,
        )
