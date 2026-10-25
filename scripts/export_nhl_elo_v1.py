#!/usr/bin/env python3
"""Export preliminary NHL Elo ratings for the existing read-only live scanner."""
import argparse
import datetime as dt
import json
import math
import os
import sys
from pathlib import Path

from scripts.check_nhl_probability_v3 import BASE, fetch, game_info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='2025-10-01', help='First historical date (YYYY-MM-DD)')
    parser.add_argument('--through', help='Last date to include, inclusive (YYYY-MM-DD); default yesterday UTC')
    parser.add_argument('--output', default='data/nhl_elo.json')
    args = parser.parse_args()
    start = dt.date.fromisoformat(args.start)
    through = dt.date.fromisoformat(args.through) if args.through else dt.datetime.now(dt.timezone.utc).date()-dt.timedelta(days=1)
    if through < start or (through-start).days > 730:
        parser.error('Date range must be 1..731 days')
    print('=== NHL ELO EXPORT V1 ===', flush=True)
    print('ESPN completed games only; no market data, no trades.', flush=True)
    found = {}
    abbreviations = {}
    errors = []
    for i in range((through-start).days+1):
        day = start+dt.timedelta(days=i)
        try:
            data = fetch(f'{BASE}/scoreboard?dates={day:%Y%m%d}')
            for event in data.get('events') or []:
                info = game_info(event)
                if not info: continue
                found[info['id']] = info
                for comp in (event.get('competitions') or []):
                    for side in comp.get('competitors') or []:
                        tid = str(side.get('id') or (side.get('team') or {}).get('id'))
                        abbr = str((side.get('team') or {}).get('abbreviation') or '').upper()
                        if tid and abbr: abbreviations[tid] = abbr
        except Exception as exc:
            errors.append(f'{day}: {exc}')
        if (i+1)%30==0: print(f'Scanned {i+1} dates', flush=True)
    print(f'Completed games discovered: {len(found)}; scoreboard errors: {len(errors)}',flush=True)
    if errors:
        for err in errors[:5]: print('ERROR:',err,flush=True)
        print('Refusing to export incomplete ratings.',file=sys.stderr)
        return 1
    if not found:
        print('No completed games. Refusing empty Elo export.',file=sys.stderr)
        return 1
    ratings = {}
    # Games sharing a calendar date are updated together, preventing same-day order leakage.
    grouped = {}
    for info in found.values():
        grouped.setdefault(info['date'][:10], []).append(info)
    for date in sorted(grouped):
        changes = {}
        for info in grouped[date]:
            home,away = info['home_id'],info['away_id']
            hr,ar = ratings.get(home,1500.0),ratings.get(away,1500.0)
            expected = 1/(1+10**((ar-hr-35.0)/400.0))
            delta = 20.0*(info['home_won']-expected)
            changes[home] = changes.get(home,0.0)+delta
            changes[away] = changes.get(away,0.0)-delta
        for tid,change in changes.items(): ratings[tid] = ratings.get(tid,1500.0)+change
    output = {}
    for tid,rating in ratings.items():
        abbr = abbreviations.get(tid)
        if abbr:
            if abbr in output:
                print(f'Duplicate abbreviation {abbr}; refusing ambiguous export',file=sys.stderr)
                return 1
            output[abbr] = round(rating,3)
    if len(output)<20:
        print(f'Only {len(output)} teams mapped; refusing incomplete export',file=sys.stderr)
        return 1
    dest = Path(args.output)
    dest.parent.mkdir(parents=True,exist_ok=True)
    temp = dest.with_name(dest.name+'.tmp')
    with temp.open('w',encoding='utf-8') as f: json.dump(dict(sorted(output.items())),f,indent=2); f.write('\n')
    os.replace(temp,dest)
    print(f'Exported {len(output)} team Elo ratings to {dest} (through {through})',flush=True)
    print('PRELIMINARY: starts at 1500; no season resets; update before live scans.',flush=True)
    return 0

if __name__ == '__main__': sys.exit(main())
