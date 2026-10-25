import argparse

from trader.agents.momentum import MomentumAgent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--historical",
        action="store_true",
        help="Include historical consecutive-snapshot jumps",
    )
    args = parser.parse_args()

    agent = MomentumAgent()
    results = agent.analyze(
        min_change_cents=2,
        include_historical_jumps=args.historical,
    )

    print("\n=== KALSHI SPORTS MOMENTUM V3 ===")
    print(f"Signals detected: {len(results)}")

    for item in results[:30]:
        print()
        print(
            f"[{item['type']}] [{item['direction']}] "
            f"{item['sport']} | {item['event']}"
        )
        print(f"Ticker: {item['ticker']}")
        print(f"Duration: {item['window_minutes']} minutes")
        print(
            f"Price: ${item['baseline_price']:.3f}"
            f" -> ${item['latest_price']:.3f}"
        )
        print(
            f"Movement: {item['change_cents']:+.2f} cents"
        )
        print(f"Spread: {item['spread_cents']:.2f} cents")
        print(f"Detected at: {item['detected_at']}")


if __name__ == "__main__":
    main()
