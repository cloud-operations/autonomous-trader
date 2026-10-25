"""Inspect live ESPN game-state snapshots and run experimental NHL model."""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from trader.agents.nhl_probability_v1 import estimate_nhl


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--db', default='data/game_states.db')
    parser.add_argument('--max-age', type=int, default=600)
    args=parser.parse_args()
    print('=== NHL PROBABILITY V1 (EXPERIMENTAL) ===')
    print('No Kalshi prices, no trades, no database writes.')
    path=Path(args.db)
    if not path.is_file():
        print('UNVERIFIED: game-state database not found:', path)
        return
    db=sqlite3.connect('file:'+str(path.resolve())+'?mode=ro', uri=True)
    db.row_factory=sqlite3.Row
    try:
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        print('Available tables:', ', '.join(tables))
        for table in tables:
            if not table.replace('_','').isalnum():
                continue
            cols=[r[1] for r in db.execute('PRAGMA table_info("'+table+'")')]
            lower={c.lower():c for c in cols}
            needed=('sport','fetched_at','status','period')
            if not all(k in lower for k in needed):
                continue
            score_cols=next(((a,b) for a,b in [('home_score','away_score'),('score_home','score_away')] if a in lower and b in lower),None)
            if not score_cols:
                print('Schema inspection needed for',table,':',', '.join(cols))
                continue
            clock_col=next((lower[k] for k in ('clock','display_clock','game_clock') if k in lower),None)
            if not clock_col:
                print('UNVERIFIED: no clock column in',table)
                continue
            rows=db.execute('SELECT * FROM "'+table+'" WHERE UPPER(sport)=? ORDER BY fetched_at DESC LIMIT 150',('NHL',)).fetchall()
            if not rows:
                print('No NHL snapshots in',table)
                continue
            seen=set()
            for row in rows:
                d=dict(row)
                game_id=str(d.get('game_id') or d.get('espn_game_id') or '')
                if game_id in seen:
                    continue
                seen.add(game_id)
                status=str(d['status'])
                if status.lower() not in ('in progress','in_progress','live'):
                    continue
                clock=str(d[clock_col])
                try:
                    parts=clock.split(':')
                    seconds=int(parts[0])*60+int(float(parts[1])) if len(parts)==2 else None
                    result=estimate_nhl(int(d[score_cols[0]]),int(d[score_cols[1]]),int(d['period']),seconds,status,d['fetched_at'],max_age_seconds=args.max_age)
                except (ValueError,TypeError) as exc:
                    result={'status':'UNVERIFIED','reason':str(exc)}
                print(json.dumps({'game_id':game_id,'fetched_at':d['fetched_at'],'result':result},indent=2))
            print('Checked',len(seen),'distinct NHL games in',table)
            return
        print('No compatible NHL game-state table found. Share schema output for adapter.')
    finally:
        db.close()

if __name__=='__main__':
    main()
