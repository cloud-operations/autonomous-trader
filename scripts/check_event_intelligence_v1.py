#!/usr/bin/env python3
"""Read-only event intelligence audit; never modifies the tracker database."""
import argparse
from trader.agents.event_intelligence_v1 import inspect_and_group


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='data/signal_tracker.db')
    parser.add_argument('--limit', type=int, default=5000)
    args = parser.parse_args()
    groups, count, cols = inspect_and_group(args.db, args.limit)
    print('=== EVENT INTELLIGENCE V1 ===')
    print(f'Signals inspected: {count}')
    print(f'Event groups: {len(groups)}')
    print('Team-to-contract mapping: UNVERIFIED (requires Kalshi market metadata)')
    print('No trades or database writes.')
    for g in groups:
        print(f"\n{g['sport']} | {g['event']}")
        print(f"  Signals: {len(g['signals'])} | Distinct contracts: {len(g['tickers'])}")
        for ticker in sorted(g['tickers']):
            print(f'  Contract: {ticker} | represented team: UNVERIFIED')
    if not groups:
        print('No recorded signals yet.')


if __name__ == '__main__':
    main()
