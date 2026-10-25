"""Read-only grouping of Kalshi contract signals by event.

Do not infer the represented team from price direction or ticker suffix.
"""
import re
import sqlite3
from collections import defaultdict
from pathlib import Path


def columns(connection, table):
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def first_available(names, candidates):
    return next((x for x in candidates if x in names), None)


def normalize_event(event):
    text = re.sub(r'\s+', ' ', str(event or '')).strip()
    # Only canonicalize explicitly symmetric 'vs' pairs. Never merge games by date alone.
    sides = re.split(r'\s+(?:vs\.?|versus|@)\s+', text, flags=re.I)
    if len(sides) == 2 and all(sides):
        return ' / '.join(sorted(s.strip().casefold() for s in sides))
    return text.casefold()


def inspect_and_group(db_path, limit=5000):
    db = Path(db_path)
    if not db.is_file():
        raise FileNotFoundError(f'Signal tracker database not found: {db}')
    con = sqlite3.connect(f'file:{db.resolve()}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        available = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'signals' not in available:
            raise ValueError('Missing signals table')
        names = columns(con, 'signals')
        sport_col = first_available(names, ['sport', 'league'])
        event_col = first_available(names, ['event', 'event_name', 'game'])
        ticker_col = first_available(names, ['ticker', 'market_ticker'])
        time_col = first_available(names, ['detected_at', 'signal_time', 'recorded_at', 'created_at'])
        change_col = first_available(names, ['change_cents', 'price_change_cents', 'change'])
        if not all([sport_col, event_col, ticker_col]):
            raise ValueError('Required columns not found; available: ' + ', '.join(names))
        order = f'ORDER BY "{time_col}" DESC' if time_col else ''
        rows = con.execute(f'SELECT * FROM signals {order} LIMIT ?', (limit,)).fetchall()
        groups = defaultdict(lambda: {'tickers': set(), 'signals': [], 'team_resolution': 'UNVERIFIED'})
        for row in rows:
            sport = str(row[sport_col] or 'UNKNOWN')
            event = str(row[event_col] or 'UNKNOWN')
            ticker = str(row[ticker_col] or 'UNKNOWN')
            # No date merge: use the full event string. Game ID resolution comes later.
            key = (sport, normalize_event(event))
            entry = groups[key]
            entry['sport'] = sport
            entry['event'] = event
            entry['tickers'].add(ticker)
            entry['signals'].append({'ticker': ticker, 'time': row[time_col] if time_col else None,
                                     'change': row[change_col] if change_col else None})
        return sorted(groups.values(), key=lambda g: len(g['signals']), reverse=True), len(rows), names
    finally:
        con.close()
