#!/usr/bin/env python3
"""Read-only NHL comeback candidate scanner; no trades, writes, or market claims."""
import argparse, json, sys, urllib.request
from datetime import datetime, timezone

SCOREBOARD = 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard'

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={'User-Agent':'nhl-research-scanner/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def parse_strength(path):
    if not path: return {}
    with open(path, encoding='utf-8') as f: data=json.load(f)
    if not isinstance(data,dict): raise ValueError('Strength file must be JSON object of ESPN team abbreviations to Elo ratings')
    return {str(k).upper():float(v) for k,v in data.items()}

def team_info(item):
    team=item.get('team') or {}
    return {'abbr':str(team.get('abbreviation') or '').upper(), 'name':team.get('displayName') or team.get('name') or '?', 'score':int(item.get('score') or 0), 'home':item.get('homeAway')=='home'}

def scan(data, strength, min_elo, max_deficit):
    rows=[]; skipped=[]
    for event in data.get('events',[]):
        comps=event.get('competitions') or []
        if not comps: continue
        comp=comps[0]
        status=comp.get('status') or event.get('status') or {}
        typ=status.get('type') or {}
        if typ.get('state')!='in': continue
        competitors=comp.get('competitors') or []
        if len(competitors)!=2: continue
        teams=[team_info(t) for t in competitors]
        home=next((t for t in teams if t['home']),None)
        away=next((t for t in teams if not t['home']),None)
        if not home or not away: continue
        common={'game':f"{away['abbr']} @ {home['abbr']}", 'score':f"{away['score']}-{home['score']}", 'period':status.get('period'), 'clock':status.get('displayClock'), 'event_id':event.get('id')}
        if not all(t['abbr'] in strength for t in teams):
            skipped.append({**common,'reason':'Missing independently sourced Elo rating'})
            continue
        delta=strength[home['abbr']]-strength[away['abbr']]
        if abs(delta)<min_elo: continue
        stronger=home if delta>0 else away
        weaker=away if delta>0 else home
        deficit=weaker['score']-stronger['score']
        if deficit<1 or deficit>max_deficit: continue
        period=status.get('period')
        if not isinstance(period,int) or period>3 or period<1: continue
        rows.append({**common,'stronger':stronger['name'], 'stronger_abbr':stronger['abbr'], 'elo_gap':round(abs(delta),1), 'deficit':deficit, 'status':'CANDIDATE ONLY — probability not calibrated; no price edge established'})
    return rows,skipped

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elo-json', help='JSON map of independently sourced pregame Elo ratings keyed by ESPN team abbreviation')
    p.add_argument('--min-elo',type=float,default=50)
    p.add_argument('--max-deficit',type=int,default=1)
    p.add_argument('--scoreboard-json',help='Optional local ESPN scoreboard fixture for offline tests')
    args=p.parse_args()
    if args.min_elo<0 or args.max_deficit<1: p.error('Invalid thresholds')
    print('=== NHL LIVE COMEBACK SCANNER V1 ===',flush=True)
    print('Read-only. No Kalshi prices, no trades, no database writes.',flush=True)
    print('Checked at:',datetime.now(timezone.utc).isoformat(),flush=True)
    try:
        strength=parse_strength(args.elo_json)
        if args.scoreboard_json:
            with open(args.scoreboard_json,encoding='utf-8') as f:data=json.load(f)
        else:data=fetch(SCOREBOARD)
        rows,skipped=scan(data,strength,args.min_elo,args.max_deficit)
    except Exception as e:
        print('ERROR:',str(e),file=sys.stderr);return 1
    live=sum(1 for e in data.get('events',[]) if (e.get('status') or {}).get('type',{}).get('state')=='in' or any((c.get('status') or {}).get('type',{}).get('state')=='in' for c in e.get('competitions',[])))
    print(f'Live NHL games: {live}; qualifying candidates: {len(rows)}; skipped missing Elo: {len(skipped)}')
    if not args.elo_json: print('NO ELO FILE: all live games require independent strength data; no candidates can be verified.')
    for r in rows: print(json.dumps(r,sort_keys=True))
    for r in skipped: print('SKIPPED:',json.dumps(r,sort_keys=True))
    if not rows: print('No VERIFIED candidates at this scan. This does not imply no teams are trailing.')
    return 0
if __name__=='__main__':sys.exit(main())
