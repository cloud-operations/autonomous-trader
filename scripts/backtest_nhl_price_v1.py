#!/usr/bin/env python3
"""Read-only, exploratory NHL Kalshi quote-path simulator.

No game-state validation, order-book depth, fills, or real orders. Entries are
hypothetical at observed ask; exits at a subsequent observed bid. Candidate
entries are independent overlapping what-if scenarios, not a portfolio strategy.
"""
import argparse
import csv
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


def arguments():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', default='data/market_history.db')
    ap.add_argument('--ticker-prefix', default='KXNHLGAME-')
    ap.add_argument('--take-profit-cents', type=float, default=15)
    ap.add_argument('--stop-loss-cents', type=float, default=10)
    ap.add_argument('--max-hold-minutes', type=float, default=30)
    ap.add_argument('--max-quote-gap-minutes', type=float, default=10)
    ap.add_argument('--fee-per-contract-roundtrip', type=float, default=0.0,
                    help='User-supplied roundtrip fee in dollars; 0 means fees excluded, not free trading')
    ap.add_argument('--max-position-dollars', type=float, default=10)
    ap.add_argument('--output', default='data/nhl_price_backtest_v1.csv')
    return ap.parse_args()


def main():
    a = arguments()
    if not Path(a.db).exists():
        raise SystemExit(f'Database not found: {a.db}')
    if any(v <= 0 for v in (a.take_profit_cents, a.stop_loss_cents, a.max_hold_minutes,
                            a.max_quote_gap_minutes, a.max_position_dollars)) or a.fee_per_contract_roundtrip < 0:
        raise SystemExit('TP, SL, hold, gap and position must be positive; fee must be nonnegative')
    conn = sqlite3.connect(f'file:{Path(a.db).resolve()}?mode=ro', uri=True)
    try:
        rows = conn.execute('''SELECT id, recorded_at, ticker, yes_bid, yes_ask
            FROM price_snapshots WHERE UPPER(sport)='NHL' AND ticker LIKE ?
            ORDER BY ticker, recorded_at, id''', (a.ticker_prefix + '%',)).fetchall()
    finally:
        conn.close()
    grouped = defaultdict(list)
    bad = 0
    for _id, stamp, ticker, bid, ask in rows:
        try:
            t = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if t.tzinfo is None or not (0 < bid <= ask < 1):
                raise ValueError('Invalid timestamp or quote')
            grouped[ticker].append((t, _id, bid, ask))
        except (ValueError, TypeError):
            bad += 1
    outcomes = []
    tp = a.take_profit_cents / 100
    sl = a.stop_loss_cents / 100
    for ticker, quotes in grouped.items():
        # Duplicate timestamps cannot establish ordering; retain latest row per timestamp.
        dedup = {q[0]: q for q in quotes}
        quotes = [dedup[t] for t in sorted(dedup)]
        for i, (entry_time, entry_id, entry_bid, entry_ask) in enumerate(quotes[:-1]):
            qty = int((a.max_position_dollars + 1e-9) / entry_ask)
            if qty < 1:
                continue
            deadline = entry_time + timedelta(minutes=a.max_hold_minutes)
            previous = entry_time
            exit_quote = None
            reason = 'UNRESOLVED'
            for t, row_id, bid, ask in quotes[i + 1:]:
                if t > deadline:
                    break
                if (t - previous).total_seconds() > a.max_quote_gap_minutes * 60:
                    reason = 'STALE_GAP'
                    break
                previous = t
                exit_quote = (t, bid)
                if bid - entry_ask >= tp - 1e-9:
                    reason = 'TAKE_PROFIT'
                    break
                if bid - entry_ask <= -sl + 1e-9:
                    reason = 'STOP_LOSS'
                    break
            if reason == 'UNRESOLVED' and exit_quote is not None:
                reason = 'LAST_OBSERVED_BID'
            # LAST_OBSERVED_BID is only a mark, not proof of executable timed exit.
            t_exit, bid_exit = exit_quote if exit_quote else (None, None)
            gross = (bid_exit - entry_ask) * qty if bid_exit is not None else None
            net = gross - a.fee_per_contract_roundtrip * qty if gross is not None else None
            outcomes.append(dict(ticker=ticker, entry_time=entry_time.isoformat(),
                entry_ask=entry_ask, quantity=qty, exit_time=t_exit.isoformat() if t_exit else '',
                exit_bid=bid_exit if bid_exit is not None else '', exit_reason=reason,
                gross_pnl=round(gross, 4) if gross is not None else '',
                net_pnl=round(net, 4) if net is not None else ''))
    fields = ['ticker', 'entry_time', 'entry_ask', 'quantity', 'exit_time', 'exit_bid',
              'exit_reason', 'gross_pnl', 'net_pnl']
    output = Path(a.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(outcomes)
    counts = defaultdict(int)
    for r in outcomes:
        counts[r['exit_reason']] += 1
    print('NHL QUOTE-PATH EXPLORATION V1 — READ ONLY')
    print(f'Input snapshots: {len(rows)}; invalid: {bad}; contracts: {len(grouped)}')
    print(f'Hypothetical independent entry scenarios: {len(outcomes)}')
    for reason in ('TAKE_PROFIT', 'STOP_LOSS', 'LAST_OBSERVED_BID', 'STALE_GAP', 'UNRESOLVED'):
        print(f'  {reason}: {counts[reason]}')
    print(f'CSV: {output}')
    print('WARNING: Not a live-score-linked backtest or executable-fill proof.')
    print('Entries overlap; results must NOT be aggregated as portfolio returns.')
    print('LAST_OBSERVED_BID is a mark, not a verified time-based exit.')
    if a.fee_per_contract_roundtrip == 0:
        print('Fees excluded (set --fee-per-contract-roundtrip for a fee sensitivity test).')

if __name__ == '__main__':
    main()
