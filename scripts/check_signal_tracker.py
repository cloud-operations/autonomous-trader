import sqlite3
from pathlib import Path

path = Path('data/signal_tracker.db')
if not path.exists():
    raise SystemExit('No tracker database yet. Run track_signals_v2.py --once first.')
with sqlite3.connect(path) as db:
    print('=== SIGNAL TRACKER V2 ===')
    for status, count in db.execute('SELECT correlation_status, COUNT(*) FROM signals GROUP BY correlation_status'):
        print(f'{status}: {count}')
    print('\nRecent signals:')
    for row in db.execute('''SELECT sport,event,change_cents,correlation_status,outcome,
        movement_since_signal_cents,detected_at FROM signals ORDER BY detected_at DESC LIMIT 15'''):
        print(' | '.join(str(x) for x in row))
