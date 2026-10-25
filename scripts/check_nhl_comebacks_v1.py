#!/usr/bin/env python3
"""Read-only, game-level NHL stronger-team comeback validation."""
import argparse
import datetime as dt
import math
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trader.agents.nhl_probability_v3 import train, predict, features
from scripts.check_nhl_probability_v3 import BASE, fetch, game_info, extract_goals, make_rows, baseline


def collect(start, days):
    found={}; errors=[]
    for d in range(days):
        date=start+dt.timedelta(days=d)
        try:
            for event in fetch(f'{BASE}/scoreboard?dates={date:%Y%m%d}').get('events',[]):
                info=game_info(event)
                if info:found[info['id']]=info
        except Exception as exc:errors.append(f'{date}: {exc}')
    return sorted(found.values(),key=lambda x:(x['date'][:10],x['id'])),errors


def build(games, min_elo):
    ratings={}; rows=[]; outcomes=Counter(); all_games=[]
    # Batch Elo updates at end of each calendar date: no same-date future results.
    for date in sorted({g['date'][:10] for g in games}):
        day_games=[g for g in games if g['date'][:10]==date]
        changes={}
        for info in day_games:
            h_id,a_id=info['home_id'],info['away_id']
            hr,ar=ratings.get(h_id,1500.0),ratings.get(a_id,1500.0)
            elo_delta=hr-ar
            expected=1/(1+10**((ar-hr-35)/400))
            change=20*(info['home_won']-expected)
            changes[h_id]=changes.get(h_id,0)+change
            changes[a_id]=changes.get(a_id,0)-change
            try:
                summary=fetch(f"{BASE}/summary?event={info['id']}")
                goals,reason=extract_goals(summary,info)
                if goals is None:
                    outcomes[reason]+=1;continue
                # Elo includes fixed 35-point home adjustment in V3 features.
                game={**info,'rows':make_rows(goals,elo_delta+35)}
                all_games.append(game)
                outcomes['OK']+=1
                if abs(elo_delta)<min_elo:continue
                stronger_home=elo_delta>0
                for checkpoint,row in enumerate(game['rows'],start=1):
                    deficit=(row['away']-row['home']) if stronger_home else (row['home']-row['away'])
                    if deficit>=1:
                        rows.append({'game':game,'row':row,'stronger_home':stronger_home,
                                     'elo_gap':abs(elo_delta),'deficit':deficit,
                                     'minute':checkpoint*5,'won':int(info['home_won']==stronger_home)})
                        break
            except Exception as exc:
                outcomes['ERROR']+=1
                if outcomes['ERROR']<=3:print('Sample error:',info['id'],str(exc)[:150],flush=True)
        for team,change in changes.items():ratings[team]=ratings.get(team,1500.0)+change
    return all_games,rows,outcomes


def metrics(items,weights):
    if not items:
        print('No qualifying comeback opportunities in this split.')
        return
    n=len(items); wins=sum(x['won'] for x in items)
    print(f'  Opportunities={n} | actual comeback wins={wins} ({wins/n:.1%})')
    print('  Each game counted once at first qualifying checkpoint.')
    for name,fn in [('V1 heuristic',lambda x:baseline(x['row'])),
                    ('V3 fitted',lambda x:predict(weights,x['row']['x']))]:
        probs=[]; actual=[]
        for x in items:
            home_p=fn(x)
            probs.append(home_p if x['stronger_home'] else 1-home_p)
            actual.append(x['won'])
        brier=sum((p-y)**2 for p,y in zip(probs,actual))/n
        loss=sum(-y*math.log(max(1e-6,p))-(1-y)*math.log(max(1e-6,1-p)) for p,y in zip(probs,actual))/n
        print(f'  {name:13s} Brier={brier:.4f} LogLoss={loss:.4f} mean predicted={sum(probs)/n:.1%}')
        for lo,hi in [(0,.2),(.2,.4),(.4,.6),(.6,.8),(.8,1.000001)]:
            indices=[i for i,p in enumerate(probs) if lo<=p<hi]
            if indices:
                print(f'    {lo:.0%}-{hi:.0%}: games={len(indices):3d} predicted={sum(probs[i] for i in indices)/len(indices):.1%} won={sum(actual[i] for i in indices)/len(indices):.1%}')
    print('  By deficit:')
    for label,subset in [('1 goal',[x for x in items if x['deficit']==1]),
                         ('2+ goals',[x for x in items if x['deficit']>=2])]:
        if subset:print(f'    {label}: {len(subset)} games; win rate={sum(x["won"] for x in subset)/len(subset):.1%}')


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--start',default='2025-10-01')
    ap.add_argument('--days',type=int,default=90)
    ap.add_argument('--min-elo',type=float,default=50)
    ap.add_argument('--holdout',type=float,default=.25)
    args=ap.parse_args()
    if not 2<=args.days<=365 or not 0<args.min_elo<=500 or not .1<=args.holdout<=.5:ap.error('Invalid range')
    print('=== NHL COMEBACK VALIDATION V1 ===',flush=True)
    print('Research only; no Kalshi prices, trades, or database writes.',flush=True)
    games,errors=collect(dt.date.fromisoformat(args.start),args.days)
    print(f'Completed games discovered: {len(games)}; scoreboard errors: {len(errors)}',flush=True)
    if errors:print('First scoreboard error:',errors[0],flush=True)
    all_games,candidates,outcomes=build(games,args.min_elo)
    print('Parse outcomes:',dict(outcomes),flush=True)
    if len(all_games)<40:
        print('INSUFFICIENT DATA: need at least 40 valid games.');return
    cut=max(1,min(len(all_games)-1,round(len(all_games)*(1-args.holdout))))
    train_games,holdout_games=all_games[:cut],all_games[cut:]
    weights=train(train_games)
    train_ids={g['id'] for g in train_games}; holdout_ids={g['id'] for g in holdout_games}
    print(f'Chronological split: train={len(train_games)} holdout={len(holdout_games)}; Elo threshold={args.min_elo:.0f}')
    print('Fitted weights:',[round(w,4) for w in weights])
    print('\nTRAIN — qualifying stronger-team trailing states')
    metrics([x for x in candidates if x['game']['id'] in train_ids],weights)
    print('\nHOLDOUT — qualifying stronger-team trailing states')
    metrics([x for x in candidates if x['game']['id'] in holdout_ids],weights)
    print('\nLIMITATIONS: preliminary Elo initialized at 1500; same-day updates delayed; no season resets; game-level sample may be small. No trade eligibility.')

if __name__=='__main__':main()
