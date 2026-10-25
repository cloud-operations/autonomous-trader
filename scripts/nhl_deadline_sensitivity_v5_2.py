#!/usr/bin/env python3
"""Read-only sensitivity analysis for unresolved NHL deadline exits. No orders."""
import argparse
import csv
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_dt(s):
    dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trades', default='data/nhl_comebacks_v5_1.csv')
    p.add_argument('--prices', default='data/market_history.db')
    p.add_argument('--output', default='data/nhl_deadline_sensitivity_v5_2.csv')
    p.add_argument('--max-hold-minutes', type=float, default=30)
    p.add_argument('--tolerance-seconds', type=float, default=150)
    p.add_argument('--fee-per-contract-roundtrip', type=float, default=0.0)
    a = p.parse_args()
    if min(a.max_hold_minutes, a.tolerance_seconds, a.fee_per_contract_roundtrip) < 0:
        p.error('Time and fee values must be nonnegative')
    with open(a.trades, newline='') as f:
        trades = list(csv.DictReader(f))
    db = sqlite3.connect(f'file:{Path(a.prices).resolve()}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    results = []
    for trade in trades:
        reason = trade['exit_reason']
        record = {
            'game_id': trade['game_id'], 'ticker': trade['ticker'],
            'strict_exit_reason': reason, 'strict_net_pnl': trade['net_pnl'],
            'sensitivity_status': 'STRICT_UNCHANGED', 'deadline': '',
            'delayed_quote_time': '', 'delay_seconds': '', 'delayed_bid': '',
            'entry_ask': trade['entry_ask'], 'quantity': trade['quantity'],
            'delayed_gross_pnl': '', 'assumed_fees': '', 'delayed_net_pnl': ''
        }
        if reason == 'UNRESOLVED_DEADLINE_GAP':
            deadline = parse_dt(trade['entry_time']) + timedelta(minutes=a.max_hold_minutes)
            record['deadline'] = deadline.isoformat()
            q = db.execute('''SELECT recorded_at, yes_bid FROM price_snapshots
                WHERE ticker=? AND recorded_at > ? AND recorded_at <= ?
                  AND yes_bid IS NOT NULL
                ORDER BY recorded_at, id LIMIT 1''',
                (trade['ticker'], deadline.isoformat(),
                 (deadline + timedelta(seconds=a.tolerance_seconds)).isoformat())).fetchone()
            if q is None:
                record['sensitivity_status'] = 'NO_QUOTE_WITHIN_TOLERANCE'
            else:
                delay = (parse_dt(q['recorded_at']) - deadline).total_seconds()
                bid = float(q['yes_bid'])
                ask = float(trade['entry_ask'])
                qty = int(trade['quantity'])
                gross = qty * (bid - ask)
                fees = qty * a.fee_per_contract_roundtrip
                record.update({
                    'sensitivity_status': 'DELAYED_EXIT_SENSITIVITY_ONLY',
                    'delayed_quote_time': q['recorded_at'],
                    'delay_seconds': round(delay, 1),
                    'delayed_bid': bid,
                    'delayed_gross_pnl': round(gross, 2),
                    'assumed_fees': round(fees, 2),
                    'delayed_net_pnl': round(gross-fees, 2)
                })
        results.append(record)
    db.close()
    fields = list(results[0]) if results else [
        'game_id','ticker','strict_exit_reason','strict_net_pnl',
        'sensitivity_status','deadline','delayed_quote_time','delay_seconds',
        'delayed_bid','entry_ask','quantity','delayed_gross_pnl',
        'assumed_fees','delayed_net_pnl']
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    with open(a.output, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
    print('NHL V5.2 DEADLINE SENSITIVITY — READ ONLY')
    for r in results:
        if r['strict_exit_reason'] == 'UNRESOLVED_DEADLINE_GAP':
            print(f"{r['game_id']}: {r['sensitivity_status']}; delay={r['delay_seconds']}s; "
                  f"bid={r['delayed_bid']}; hypothetical net=${r['delayed_net_pnl']}")
    print('Strict V5.1 classifications unchanged; delayed quotes are not executable-fill evidence.')
    print('Output:', a.output)

if __name__ == '__main__':
    main()
