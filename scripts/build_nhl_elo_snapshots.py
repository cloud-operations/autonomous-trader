#!/usr/bin/env python3
"""Reconstruct conservative NHL Elo snapshots from V2 pregame CSV. Research only.

Each game-start group uses pregame ratings from the CSV; outputs a snapshot at
start-minus-one-microsecond, representing the ratings used for that start group.
This does NOT certify actual result availability. See warnings.
"""
import argparse,csv,json
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path

def parse(s):
 d=datetime.fromisoformat(s.replace('Z','+00:00'))
 return d.astimezone(timezone.utc)

def main():
 p=argparse.ArgumentParser()
 p.add_argument('--input',default='data/nhl_point_in_time_elo_v2.csv')
 p.add_argument('--output',default='data/nhl_elo_history_v2.jsonl')
 p.add_argument('--initial-elo',type=float,default=1500)
 p.add_argument('--k',type=float,default=20)
 p.add_argument('--home-advantage',type=float,default=35)
 a=p.parse_args()
 with open(a.input,newline='') as f: rows=list(csv.DictReader(f))
 rows.sort(key=lambda r:(parse(r['game_date']),r['game_id']))
 groups=defaultdict(list)
 for r in rows:groups[parse(r['game_date'])].append(r)
 teams={r["home_abbr"] for r in rows}|{r["away_abbr"] for r in rows}
 ratings={team:a.initial_elo for team in teams};written=0;conflicts=[];snapshots=[]
 for start,group in sorted(groups.items()):
  # Verify builder's stored pregame values match the replayed state before updating.
  for r in group:
   for abbr,col in ((r['home_abbr'],'home_pregame_elo'),(r['away_abbr'],'away_pregame_elo')):
    expected=ratings.get(abbr,a.initial_elo)
    if abs(expected-float(r[col]))>0.001:
     conflicts.append((r['game_id'],abbr,round(expected,4),r[col]))
  # Do not produce misleading snapshots if input is inconsistent with replay assumptions.
  if conflicts:break
  # Snapshot at game start. V4 uses strict stamp < start, so same-time games cannot see one another.
  snapshots.append({'as_of':start.isoformat(),'ratings':{t:round(v,4) for t,v in sorted(ratings.items())}})
  pending=[]
  for r in group:
   h,aw=r['home_abbr'],r['away_abbr']
   rh=ratings.get(h,a.initial_elo);ra=ratings.get(aw,a.initial_elo)
   expected=1/(1+10**((ra-rh-a.home_advantage)/400))
   actual=1.0 if int(r['home_score'])>int(r['away_score']) else 0.0 if int(r['home_score'])<int(r['away_score']) else .5
   pending.append((h,aw,a.k*(actual-expected)))
  for h,aw,delta in pending:
   ratings[h]=ratings.get(h,a.initial_elo)+delta
   ratings[aw]=ratings.get(aw,a.initial_elo)-delta
  written+=len(group)
 if conflicts:
  print('ABORT: Elo replay mismatch; no output written. First mismatches:',conflicts[:5]);return 2
 # A later game's snapshot must not include the result of a game that has not yet ended.
 # We cannot certify result availability from this CSV, so mark output as research-only.
 out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
 with out.open('w') as f:
  for rec in snapshots:f.write(json.dumps(rec,separators=(',',':'))+'\n')
 print(f'Validated games: {written}; snapshots: {len(snapshots)}; teams in final state: {len(ratings)}')
 print(f'JSONL: {out}')
 print('WARNING: Scheduled-start replay assumes earlier games have completed; overlapping games can cause look-ahead.')
 print('WARNING: These snapshots are NOT certified point-in-time. Use only for exploratory diagnostics.')
 return 0
if __name__=='__main__':raise SystemExit(main())
