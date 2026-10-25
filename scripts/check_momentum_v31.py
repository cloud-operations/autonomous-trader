import argparse
from trader.agents.momentum_v31 import MomentumAgentV31


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--historical", action="store_true")
    parser.add_argument("--min-change", type=float, default=10)
    args = parser.parse_args()

    agent = MomentumAgentV31()
    signals = agent.analyze(
        historical=args.historical,
        min_change_cents=args.min_change,
    )

    print("\n=== KALSHI MOMENTUM V3.1 ===")
    print("Mode:", "HISTORICAL" if args.historical else "LIVE")
    print("Signals detected:", len(signals))

    for s in signals[:20]:
        print(
            f"[{s['direction']}] {s['sport']} | {s['event']} "
            f"| {s['change_cents']:+.1f}c "
            f"| {s['previous_price']*100:.1f}c"
            f" -> {s['current_price']*100:.1f}c "
            f"| spread {s['spread_cents']:.1f}c "
            f"| validation={s['requires_game_validation']}"
        )


if __name__ == "__main__":
    main()
