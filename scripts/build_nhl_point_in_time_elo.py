#!/usr/bin/env python3
"""Build pregame NHL Elo ratings from historical ESPN scoreboard results. Read-only to existing databases."""
import argparse,csv,json,time,urllib.request
from datetime import date,timedelta,datetime,timezone
from pathlib import Path

API='https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates={}'

def fetch_day(d,retries=3):
    req=urllib.request.Request(API.format(d.strftime('%Y%m%d')),headers={'User-Agent':'nhl-elo-research/1.0'})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req,timeout=25) as resp:return json.load(resp)
        except Exception:
            if i==retries-1:raise
            time.sleep(2**i)

def parse_games(payload):
    for e in payload.get('events',[]):
        comps=e.get('competitions',[])
        if not comps:continue
        c=comps[0]
        if c.get('status',{}).get('type',{}).get('name')!='STATUS_FINAL':continue
        sides={x.get('homeAway'):x for x in c.get('competitors',[])}
        if not all(k in sides for k in ('home','away')):continue
        try:
            h,a=sides['home'],sides['away']
            yield {'game_id':str(e['id']),'start':e['date'],'home':h['team']['abbreviation'],'away':a['team']['abbreviation'],
                   'home_score':int(h['score']),'away_score':int(a['score'])}
        except (KeyError,ValueError,TypeError):continue

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start',default='2024-10-01',help='Historical collection start YYYY-MM-DD')
    p.add_argument('--end',default=None,help='Last historical game date (default yesterday UTC)')
    p.add_argument('--output',default='data/nhl_point_in_time_elo.csv')
    p.add_argument('--k',type=float,default=20)
    p.add_argument('--home-advantage',type=float,default=35)
    p.add_argument('--initial-elo',type=float,default=1500)
    p.add_argument('--sleep',type=float,default=0.12,help='Delay between requests')
    p.add_argument('--allow-incomplete',action='store_true',help='Write partial output if some dates fail (NOT recommended)')
    args=p.parse_args()
    start=date.fromisoformat(args.start);end=date.fromisoformat(args.end) if args.end else datetime.now(timezone.utc).date()-timedelta(days=1)
    if end<start:p.error('end must be >= start')
    if end>=datetime.now(timezone.utc).date():p.error('end must be before current UTC date to avoid unfinished games')
    all_games={};failed=[];d=start
    print(f'Fetching NHL completed games from {start} through {end}',flush=True)
    while d<=end:
        try:
            for game in parse_games(fetch_day(d)):
                all_games[game['game_id']]=game
        except Exception as exc:
            failed.append((d.isoformat(),str(exc)));print(f'FAILED {d}: {exc}',flush=True)
        d+=timedelta(days=1)
        if args.sleep:time.sleep(args.sleep)
    if failed and not args.allow_incomplete:
        print(f'ABORT: {len(failed)} failed dates; refusing incomplete Elo history. Retry later.');return 2
    games=sorted(all_games.values(),key=lambda x:(x['start'],x['game_id']))
    ratings={};rows=[];ties=0
    # Simultaneous start timestamps are updated as a group, avoiding same-time future information.
    i=0
    while i<len(games):
        j=i+1
        while j<len(games) and games[j]['start']==games[i]['start']:j+=1
        pending=[]
        for g in games[i:j]:
            rh=ratings.get(g['home'],args.initial_elo);ra=ratings.get(g['away'],args.initial_elo)
            eh=1/(1+10**((ra-rh-args.home_advantage)/400))
            if g['home_score']==g['away_score']:
                ties+=1;actual=.5
            else:actual=1.0 if g['home_score']>g['away_score'] else 0.0
            change=args.k*(actual-eh)
            rows.append({'game_id':g['game_id'],'game_date':g['start'],'away_abbr':g['away'],'home_abbr':g['home'],
                         'away_pregame_elo':round(ra,4),'home_pregame_elo':round(rh,4),
                         'elo_gap_home_minus_away':round(rh-ra,4),'home_win_probability':round(eh,6),
                         'away_score':g['away_score'],'home_score':g['home_score']})
            pending.append((g['home'],g['away'],change))
        for h,a,change in pending:
            ratings[h]=ratings.get(h,args.initial_elo)+change
            ratings[a]=ratings.get(a,args.initial_elo)-change
        i=j
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    fields=['game_id','game_date','away_abbr','home_abbr','away_pregame_elo','home_pregame_elo','elo_gap_home_minus_away','home_win_probability','away_score','home_score']
    with out.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    print(f'Games: {len(rows)}; teams: {len(ratings)}; final-score ties: {ties}; failed dates: {len(failed)}')
    print(f'CSV: {out}')
    print('CAUTION: Elo is sequential by scheduled game start, not verified result-publication time; initial 1500 is a warm-up assumption; no season resets.')
    print('CAUTION: ESPN final-only historical API is not an immutable point-in-time archive; games with corrections may differ from originally published scores.')
    if failed:print('INCOMPLETE DATES:',failed[:20])
    return 0

if __name__=='__main__':raise SystemExit(main())
