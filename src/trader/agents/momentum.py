import sqlite3
from datetime import datetime, timedelta, timezone


class MomentumAgent:
    def __init__(self, db_path="data/market_history.db"):
        self.db_path = db_path

    def analyze(
        self,
        windows=(5, 15, 60),
        min_change_cents=2,
        max_spread_cents=10,
        max_staleness_minutes=10,
        max_baseline_gap_minutes=5,
        max_jump_gap_minutes=10,
        include_historical_jumps=False,
    ):
        now = datetime.now(timezone.utc)
        results = []

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, ticker, sport, event,
                       recorded_at, yes_bid, yes_ask, midpoint
                FROM price_snapshots
                ORDER BY ticker, recorded_at, id
            """).fetchall()

        history = {}
        for row in rows:
            history.setdefault(row["ticker"], []).append(row)

        for ticker, prices in history.items():
            latest = prices[-1]
            latest_time = datetime.fromisoformat(
                latest["recorded_at"]
            )

            age = (now - latest_time).total_seconds() / 60
            if age > max_staleness_minutes:
                continue

            spread = (
                latest["yes_ask"] - latest["yes_bid"]
            ) * 100

            if spread > max_spread_cents:
                continue

            # Rolling-window analysis
            for window in windows:
                target = latest_time - timedelta(minutes=window)

                eligible = [
                    row for row in prices
                    if target - timedelta(
                        minutes=max_baseline_gap_minutes
                    ) <= datetime.fromisoformat(
                        row["recorded_at"]
                    ) <= target
                ]

                if not eligible:
                    continue

                baseline = eligible[-1]
                change = (
                    latest["midpoint"] -
                    baseline["midpoint"]
                ) * 100

                if abs(change) < min_change_cents:
                    continue

                results.append({
                    "type": "ROLLING",
                    "ticker": ticker,
                    "sport": latest["sport"],
                    "event": latest["event"],
                    "window_minutes": window,
                    "baseline_price": baseline["midpoint"],
                    "latest_price": latest["midpoint"],
                    "change_cents": round(change, 2),
                    "direction": "UP" if change > 0 else "DOWN",
                    "spread_cents": round(spread, 2),
                    "detected_at": latest["recorded_at"],
                })

            # Consecutive snapshot jumps
            pairs = list(zip(prices[:-1], prices[1:]))

            if not include_historical_jumps:
                pairs = pairs[-1:]

            for previous, current in pairs:
                previous_time = datetime.fromisoformat(
                    previous["recorded_at"]
                )
                current_time = datetime.fromisoformat(
                    current["recorded_at"]
                )

                gap = (
                    current_time - previous_time
                ).total_seconds() / 60

                if not 0 < gap <= max_jump_gap_minutes:
                    continue

                current_spread = (
                    current["yes_ask"] -
                    current["yes_bid"]
                ) * 100

                if current_spread > max_spread_cents:
                    continue

                change = (
                    current["midpoint"] -
                    previous["midpoint"]
                ) * 100

                if abs(change) < min_change_cents:
                    continue

                results.append({
                    "type": "JUMP",
                    "ticker": ticker,
                    "sport": current["sport"],
                    "event": current["event"],
                    "window_minutes": round(gap, 2),
                    "baseline_price": previous["midpoint"],
                    "latest_price": current["midpoint"],
                    "change_cents": round(change, 2),
                    "direction": "UP" if change > 0 else "DOWN",
                    "spread_cents": round(current_spread, 2),
                    "detected_at": current["recorded_at"],
                })

        return sorted(
            results,
            key=lambda x: abs(x["change_cents"]),
            reverse=True,
        )
