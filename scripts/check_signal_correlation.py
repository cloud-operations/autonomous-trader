import argparse
from collections import Counter
from trader.agents.momentum_v31 import MomentumAgentV31
from trader.agents.signal_correlation import SignalCorrelationAgent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--historical', action='store_true')
    parser.add_argument('--min-change', type=float, default=10)
    parser.add_argument('--max-age', type=float, default=3)
    args = parser.parse_args()

    signals = MomentumAgentV31().analyze(historical=args.historical, min_change_cents=args.min_change)
    results = SignalCorrelationAgent().correlate(signals, max_age_minutes=args.max_age)
    print('\n=== SIGNAL CORRELATION V1 ===')
    print('Mode:', 'HISTORICAL' if args.historical else 'LIVE')
    print('Momentum signals:', len(signals))
    print('Correlation statuses:', dict(Counter(r['correlation_status'] for r in results)))
    for r in results[:20]:
        print(f"\n{r['sport']} | {r['event']} | {r['change_cents']:+.1f}c")
        print(f"Signal: {r['detected_at']}")
        print(f"Correlation: {r['correlation_status']} | {r['reason']}")
        if r['game_state']:
            s = r['game_state']
            fields = ('fetched_at', 'recorded_at', 'status', 'home_team', 'home_score', 'away_team', 'away_score', 'period', 'clock')
            print('Observed state:', ' | '.join(f'{k}={s[k]}' for k in fields if k in s))
    print('\nNo trading decisions are made by this script.')


if __name__ == '__main__':
    main()
