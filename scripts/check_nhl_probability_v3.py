#!/usr/bin/env python3
"""Chronological NHL train/holdout experiment. Read-only external ESPN endpoints."""
import argparse
import datetime as dt
import json
import math
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trader.agents.nhl_probability_v3 import features, predict, train, evaluate, sigmoid

BASE = 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl'

def fetch(url, retries=2):
    for attempt in range(retries+1):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; nhl-backtest-research/1.0)','Accept':'application/json'})
            with urllib.request.urlopen(req,timeout=18) as response:
                return json.load(response)
        except Exception:
            if attempt == retries: raise
            time.sleep(0.5*(attempt+1))

def game_info(event):
    comps=event.get('competitions') or []
    if not comps:return None
    sides=comps[0].get('competitors') or []
    home=next((c for c in sides if c.get('homeAway')=='home'),None)
    away=next((c for c in sides if c.get('homeAway')=='away'),None)
    status=(event.get('status') or {}).get('type') or {}
    if not home or not away or not status.get('completed'): return None
    hs,aw=int(home.get('score',0)),int(away.get('score',0))
    if hs==aw:return None  # no tie outcome
    return {'id':str(event.get('id')), 'date':str(event.get('date','')),
            'home_id':str(home.get('id') or (home.get('team') or {}).get('id')),
            'away_id':str(away.get('id') or (away.get('team') or {}).get('id')),
            'home_won':int(hs>aw),'final_home':hs,'final_away':aw}

def event_elapsed(play):
    period=play.get('period') or {}
    num=period.get('number') if isinstance(period,dict) else period
    try:num=int(num)
    except (ValueError,TypeError):return None
    if num not in (1,2,3):return None
    clock=play.get('clock') or {}
    value=clock.get('displayValue') if isinstance(clock,dict) else str(clock)
    if not value or ':' not in str(value):return None
    try:
        mm,ss=str(value).split(':',1)
        remaining=int(mm)*60+float(ss)
    except (ValueError,TypeError):return None
    if not 0<=remaining<=1200:return None
    return (num-1)*1200+remaining

def extract_goals(summary, info):
    # ESPN play-by-play includes non-scoring plays; use only explicitly flagged goals.
    raw=[]
    for key in ('plays','scoringPlays'):
        obj=summary.get(key) or []
        if isinstance(obj,dict): obj=obj.get('plays') or obj.get('items') or []
        if isinstance(obj,list):raw.extend(obj)
    goals={}
    for play in raw:
        if not isinstance(play,dict):continue
        typ=play.get('type') or {}
        typtext=' '.join(str(typ.get(k,'')) for k in ('text','displayName','abbreviation')) if isinstance(typ,dict) else str(typ)
        is_goal=play.get('scoringPlay') is True and isinstance(typ,dict) and typ.get('text','').strip().lower() == 'goal'
        if not is_goal:continue
        elapsed=event_elapsed(play)
        if elapsed is None:continue
        try:h,a=int(play['homeScore']),int(play['awayScore'])
        except (KeyError,ValueError,TypeError):continue
        goals[(elapsed,h,a)]=(elapsed,h,a)
    ordered=sorted(goals.values())
    if not ordered:return None,'NO_SCORING_PLAYS'
    prev_h=prev_a=0
    for _,h,a in ordered:
        if h<prev_h or a<prev_a or (h-prev_h)+(a-prev_a)!=1:
            return None,'INCONSISTENT_GOALS'
        prev_h,prev_a=h,a
    # Validate against the last regulation play, not the final OT/shootout score.
    regulation=[]
    for play in raw:
        if not isinstance(play,dict) or event_elapsed(play) is None: continue
        try: regulation.append((event_elapsed(play),int(play['homeScore']),int(play['awayScore'])))
        except (KeyError,ValueError,TypeError): continue
    if not regulation: return None,'NO_REGULATION_SCORE'
    _,reg_h,reg_a=max(regulation,key=lambda x:x[0])
    if (prev_h,prev_a)!=(reg_h,reg_a):
        return None,'REGULATION_GOALS_MISMATCH'
    fh,fa=info['final_home'],info['final_away']
    if (reg_h,reg_a)!=(fh,fa):
        if reg_h!=reg_a or abs(fh-fa)!=1 or max(fh-reg_h,fa-reg_a)!=1 or min(fh-reg_h,fa-reg_a)!=0:
            return None,'UNSUPPORTED_FINAL_SCORE'
    return ordered,'OK'

def make_rows(goals, elo_diff):
    rows=[]
    # 5-minute checkpoints through regulation; avoid using final-state outcome at 60:00.
    for elapsed in range(300,3600,300):
        h=a=0
        for t,hs,aw in goals:
            if t < elapsed: h,a=hs,aw  # strictly prior to checkpoint
            else:break
        rows.append({'x':features(h,a,3600-elapsed,elo_diff),'home':h,'away':a,'seconds_left':3600-elapsed})
    return rows

def baseline(row):
    # V1's original formula, with clock reconstructed from seconds remaining.
    minutes_left=row['seconds_left']/60
    diff=row['home']-row['away']
    weight=0.75+3.0*(1-minutes_left/60)**1.5
    return sigmoid(max(-7,min(7,diff*weight+0.12)))

def report(name,games,weights):
    print(f'\n{name} — {len(games)} independent games')
    for label,fn in [('V1 heuristic',baseline),('V3 fitted',lambda r:predict(weights,r['x'])),('50% baseline',lambda r:0.5)]:
        result=evaluate(games,fn)
        if not result:continue
        print(f"  {label:13s} Brier={result['brier']:.4f} LogLoss={result['logloss']:.4f} snapshots={result['snapshots']}")
        if label=='V3 fitted':
            print('  V3 bins (snapshots correlated within games): predicted avg vs actual home wins')
            for i,(count,psum,ysum) in result['bins'].items():
                if count:print(f'    {i*10:02d}-{(i+1)*10:02d}%: n={count:4d} predicted={psum/count:.1%} actual={ysum/count:.1%}')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--start',default='2025-10-01',help='YYYY-MM-DD')
    ap.add_argument('--days',type=int,default=30)
    ap.add_argument('--holdout',type=float,default=0.25)
    args=ap.parse_args()
    if args.days<2 or args.days>365 or not .1<=args.holdout<=.5:ap.error('days must be 2..365; holdout 0.1..0.5')
    start=dt.date.fromisoformat(args.start)
    print('=== NHL PROBABILITY V3: CHRONOLOGICAL BACKTEST ===',flush=True)
    print('Read-only. No Kalshi inputs, no trades, no existing DB writes.',flush=True)
    print('Regulation checkpoints, OT/SO winners; pregame rolling Elo; no future data.',flush=True)
    found={}
    errors=[]
    for offset in range(args.days):
        day=start+dt.timedelta(days=offset)
        try:
            data=fetch(f'{BASE}/scoreboard?dates={day:%Y%m%d}')
            for event in data.get('events') or []:
                info=game_info(event)
                if info:found[info['id']]=info
        except Exception as exc:errors.append(f'{day}: {exc}')
    print(f'Completed games discovered: {len(found)}; scoreboard errors: {len(errors)}',flush=True)
    games=[]
    outcomes={}
    ratings={}
    k_factor=20.0
    home_adv=35.0
    # Update ratings after each completed game, never before its own prediction.

    for n,info in enumerate(sorted(found.values(),key=lambda x:(x['date'],x['id'])),1):
        # Pregame rating: update only using earlier completed games.
        hr=ratings.get(info['home_id'],1500.0)
        ar=ratings.get(info['away_id'],1500.0)
        expected=1/(1+10**((ar-hr-home_adv)/400))
        adjustment=k_factor*(info['home_won']-expected)
        try:
            summary=fetch(f"{BASE}/summary?event={info['id']}")
            goals,reason=extract_goals(summary,info)
            if goals is None:outcomes[reason]=outcomes.get(reason,0)+1;continue
            rows=make_rows(goals,hr-ar+home_adv)
            games.append({**info,'rows':rows})
            outcomes['OK']=outcomes.get('OK',0)+1
        except Exception as exc:
            outcomes['ERROR']=outcomes.get('ERROR',0)+1
            if len(errors)<8:errors.append(f"game {info['id']}: {exc}")
        finally:
            ratings[info['home_id']]=hr+adjustment
            ratings[info['away_id']]=ar-adjustment
        if n%25==0:print(f'Processed {n}/{len(found)} games',flush=True)
    print('Parse outcomes:',outcomes,flush=True)
    if errors:
        print('Sample errors:')
        for err in errors[:8]:print(' ',err)
    if len(games)<12:
        print('INSUFFICIENT DATA: need at least 12 valid games. No model fitted.')
        print('If NO_SCORING_PLAYS or GOALS_DO_NOT_MATCH_FINAL dominates, inspect ESPN play schema before expanding.')
        return
    # Chronological split by actual game start date, never snapshots.
    games.sort(key=lambda x:(x['date'],x['id']))
    cut=max(1,min(len(games)-1,round(len(games)*(1-args.holdout))))
    training,testing=games[:cut],games[cut:]
    weights=train(training)
    print(f'Chronological split: train={len(training)} games, holdout={len(testing)} games')
    print('Fitted weights:',[round(x,4) for x in weights])
    report('TRAIN',training,weights)
    report('HOLDOUT',testing,weights)
    print('\nEXPERIMENTAL ONLY: simple rolling Elo, no calibration guarantee, no trade eligibility.')

if __name__=='__main__':main()
