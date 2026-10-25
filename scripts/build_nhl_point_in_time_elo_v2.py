#!/usr/bin/env python3
"""NHL club pregame Elo builder, with alias normalization and auditable exclusions.

Historical ESPN final-only results are not a verified point-in-time feed.
Default includes NHL regular season and playoffs, excludes preseason/all-star/international.
"""
import argparse, csv, json, time, urllib.request
from collections import Counter
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

API='https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates={}'
CLUBS=set('ANA BOS BUF CAR CBJ CGY CHI COL DAL DET EDM FLA LA MIN MTL NJ NSH NYI NYR OTT PHI PIT SEA SJ STL TB TOR UTA VAN VGK WPG WSH'.split())
ALIASES={'UTAH':'UTA'}
FIELDS=['game_id','game_date','away_abbr','home_abbr','away_pregame_elo','home_pregame_elo','elo_gap_home_minus_away','home_win_probability','away_score','home_score']

def fetch_day(d,retries=3):
    req=urllib.request.Request(API.format(d.strftime('%Y%m%d')),headers={'User-Agent':'nhl-elo-research/2.0'})
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
            # ESPN event season.type: 1 preseason, 2 regular, 3 postseason.
            season=e.get('season') or c.get('season') or {}
            season_type=season.get('type') if isinstance(season,dict) else None
            yield {'game_id':str(e['id']),'start':e['date'],
                   'home':ALIASES.get(h['team']['abbreviation'],h['team']['abbreviation']),
                   'away':ALIASES.get(a['team']['abbreviation'],a['team']['abbreviation']),
                   'home_score':int(h['score']),'away_score':int(a['score']),
                   'season_type':season_type}
        except (KeyError,ValueError,TypeError):continue

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start',default='2024-10-01');p.add_argument('--end',default=None)
    p.add_argument('--output',default='data/nhl_point_in_time_elo_v2.csv')
    p.add_argument('--audit',default='data/nhl_point_in_time_elo_v2_audit.csv')
    p.add_argument('--k',type=float,default=20);p.add_argument('--home-advantage',type=float,default=35)
    p.add_argument('--initial-elo',type=float,default=1500);p.add_argument('--sleep',type=float,default=.12)
    p.add_argument('--allow-incomplete',action='store_true')
    p.add_argument('--include-preseason',action='store_true',help='Include season type 1 (not recommended)')
    p.add_argument('--exclude-playoffs',action='store_true',help='Exclude season type 3')
    p.add_argument('--allow-unknown-season-type',action='store_true',help='Allow missing season type (not recommended)')
    args=p.parse_args()
    start=date.fromisoformat(args.start);end=date.fromisoformat(args.end) if args.end else datetime.now(timezone.utc).date()-timedelta(days=1)
    if end<start:p.error('end must be >= start')
    if end>=datetime.now(timezone.utc).date():p.error('end must be before current UTC date')
    all_games={};failed=[];d=start
    print(f'Fetching completed games {start} through {end}',flush=True)
    while d<=end:
        try:
            for game in parse_games(fetch_day(d)):all_games[game['game_id']]=game
        except Exception as exc:
            failed.append((d.isoformat(),str(exc)));print(f'FAILED {d}: {exc}',flush=True)
        d+=timedelta(days=1)
        if args.sleep:time.sleep(args.sleep)
    if failed and not args.allow_incomplete:
        print(f'ABORT: {len(failed)} failed dates; no output written');return 2
    games=[];audit=[]
    for g in all_games.values():
        reason=None
        if g['home'] not in CLUBS or g['away'] not in CLUBS:reason='NON_NHL_CLUB'
        elif g['season_type'] is None and not args.allow_unknown_season_type:reason='UNKNOWN_SEASON_TYPE'
        elif str(g['season_type'])=='1' and not args.include_preseason:reason='PRESEASON'
        elif str(g['season_type'])=='3' and args.exclude_playoffs:reason='PLAYOFFS'
        elif str(g['season_type']) not in ('1','2','3') and not (g['season_type'] is None and args.allow_unknown_season_type):reason='UNRECOGNIZED_SEASON_TYPE'
        if reason:
            audit.append({'game_id':g['game_id'],'game_date':g['start'],'away':g['away'],'home':g['home'],'season_type':g['season_type'],'reason':reason})
        else:games.append(g)
    games.sort(key=lambda x:(x['start'],x['game_id']))
    ratings={};rows=[];ties=0;i=0
    while i<len(games):
        j=i+1
        while j<len(games) and games[j]['start']==games[i]['start']:j+=1
        pending=[]
        for g in games[i:j]:
            rh=ratings.get(g['home'],args.initial_elo);ra=ratings.get(g['away'],args.initial_elo)
            eh=1/(1+10**((ra-rh-args.home_advantage)/400))
            actual=.5 if g['home_score']==g['away_score'] else float(g['home_score']>g['away_score'])
            if actual==.5:ties+=1
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
    for path,fields,records in [(args.output,FIELDS,rows),(args.audit,['game_id','game_date','away','home','season_type','reason'],audit)]:
        out=Path(path);out.parent.mkdir(parents=True,exist_ok=True)
        with out.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(records)
    print(f'Raw unique final events: {len(all_games)}; included: {len(rows)}; excluded: {len(audit)}; teams: {len(ratings)}; ties: {ties}; failed dates: {len(failed)}')
    print('Exclusions:',dict(Counter(x['reason'] for x in audit)))
    print(f'CSV: {args.output}; audit: {args.audit}')
    print('CAUTION: Scheduled-start order is not verified result-availability order; early ratings have warm-up bias; no season resets; historical ESPN scores may be revised.')
    if failed:print('INCOMPLETE DATES:',failed[:20])
    return 0
if __name__=='__main__':raise SystemExit(main())
