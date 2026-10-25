#!/usr/bin/env python3
"""V6.2 read-only NHL orderbook liquidity and hypothetical sweep analysis."""
import argparse
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

D = Decimal

def dt(s):
    value = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('naive timestamp')
    return value.astimezone(timezone.utc)

def levels(db, snapshot_id):
    out = defaultdict(list)
    for side, p, q in db.execute('SELECT side, price_dollars, quantity FROM orderbook_levels WHERE snapshot_id=?', (snapshot_id,)):
        out[side].append((D(p), D(q)))
    return out

def sweep(book, side, qty):
    """Buy YES takes NO bids at (1-NO bid); sell YES takes YES bids."""
    if side == 'BUY_YES':
        available = sorted(((D(1)-p, q) for p,q in book.get('NO_BID', [])), key=lambda x:x[0])
    else:
        available = sorted(book.get('YES_BID', []), key=lambda x:x[0], reverse=True)
    remaining = qty
    notional = D(0)
    filled = 0
    for price, raw_qty in available:
        n = min(remaining, int(raw_qty.to_integral_value(rounding=ROUND_FLOOR)))
        if n <= 0: continue
        notional += price*n
        filled += n
        remaining -= n
        if remaining == 0: break
    return filled, notional, (notional / filled if filled else None), (available[0][0] if available else None)

def affordable(book, budget):
    asks = sorted(((D(1)-p, int(q.to_integral_value(rounding=ROUND_FLOOR))) for p,q in book.get('NO_BID', [])), key=lambda x:x[0])
    spent = D(0); qty = 0
    for price, capacity in asks:
        if price <= 0: continue
        can_buy = min(capacity, int(((budget-spent)/price).to_integral_value(rounding=ROUND_FLOOR)))
        if can_buy <= 0: break
        spent += price*can_buy
        qty += can_buy
    return qty, spent

def main():
    p=argparse.ArgumentParser(description='V6.2 read-only orderbook liquidity assessment; no orders')
    p.add_argument('--db', default='data/nhl_orderbook.db')
    p.add_argument('--budget', type=str, default='10')
    p.add_argument('--contracts', type=int, default=0, help='Optional fixed quantity to sweep instead of budget-based quantity')
    p.add_argument('--max-age-seconds', type=int, default=180)
    p.add_argument('--limit', type=int, default=12)
    a=p.parse_args()
    budget=D(a.budget)
    if not budget.is_finite() or budget<=0 or a.contracts<0 or a.max_age_seconds<0 or a.limit<1:
        p.error('Invalid budget, contracts, age or limit')
    path=Path(a.db).resolve()
    if not path.is_file(): p.error(f'Database not found: {path}')
    db=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
    try:
        rows=db.execute('''SELECT s.id,s.ticker,s.recorded_at,s.yes_bid,s.yes_ask
            FROM orderbook_snapshots s
            JOIN (SELECT ticker,MAX(id) id FROM orderbook_snapshots WHERE status='OK' GROUP BY ticker) t
            ON t.id=s.id ORDER BY s.recorded_at DESC LIMIT ?''',(a.limit,)).fetchall()
        now=datetime.now(timezone.utc)
        print('=== V6.2 OBSERVED ORDERBOOK LIQUIDITY (READ ONLY) ===')
        print(f'Budget=${budget} | max age={a.max_age_seconds}s | fixed contracts={a.contracts or "auto"}')
        print('IMPORTANT: Independent buy/sell snapshots; not a realized round-trip or executable fill.\n')
        if not rows: print('No snapshots found.')
        for sid,ticker,ts,bid,ask in rows:
            age=(now-dt(ts)).total_seconds()
            book=levels(db,sid)
            qty,entry_cost=affordable(book,budget) if a.contracts==0 else (a.contracts,None)
            buy_n,buy_value,buy_avg,buy_top=sweep(book,'BUY_YES',qty)
            sell_n,sell_value,sell_avg,sell_top=sweep(book,'SELL_YES',qty)
            valid=0<=age<=a.max_age_seconds
            status='FRESH' if valid else 'STALE'
            entry_slip=(buy_avg-buy_top) if buy_avg is not None and buy_top is not None else None
            exit_slip=(sell_top-sell_avg) if sell_avg is not None and sell_top is not None else None
            print(f'{ticker} | {status} age={age:.0f}s | snapshot={sid}')
            print(f'  YES top bid/ask={bid}/{ask} | target_qty={qty} | buy_depth={buy_n}/{qty} sell_depth={sell_n}/{qty}')
            print(f'  BUY YES: avg={buy_avg} cost=${buy_value:.4f} slippage=${entry_slip if entry_slip is not None else "N/A"}/contract')
            print(f'  SELL YES: avg={sell_avg} proceeds=${sell_value:.4f} slippage=${exit_slip if exit_slip is not None else "N/A"}/contract')
            if buy_n!=qty or sell_n!=qty: print('  WARNING: INSUFFICIENT VISIBLE WHOLE-CONTRACT DEPTH')
            if not valid: print('  WARNING: stale for current-decision analysis')
            print('  NOTE: sell liquidity is an independent counterfactual at the same instant; no P&L claim.')
    finally: db.close()
if __name__=='__main__': main()
