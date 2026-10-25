#!/usr/bin/env python3
"""Research-only NHL comeback validation by deficit, period, Elo gap, and uncertainty."""
import argparse
import datetime as dt
import math
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'src'))
from scripts.check_nhl_comebacks_v1 import collect, build
from trader.agents.nhl_probability_v3 import train, predict
from scripts.check_nhl_probability_v3 import baseline


def wilson(wins,n,z=1.96):
    if not n:return (0.0,1.0)
    p=wins/n; zz=z*z; d=1+zz/n
    c=(p+zz/(2*n))/d
    m=z*math.sqrt(p*(1-p)/n+zz/(4*n*n))/d
    return max(0,c-m),min(1,c+m)


def report(label,items,weights,detail=True):
    n=len(items)
    if not n:
        print(f'  {label}: n=0 (insufficient observations)');return
    wins=sum(x['won'] for x in items)
    low,high=wilson(wins,n)
    parts=[f'  {label}: n={n} wins={wins} rate={wins/n:.1%} 95% Wilson CI=[{low:.1%},{high:.1%}]']
    for model,fn in [('V1',lambda x:baseline(x['row'])),('V3',lambda x:predict(weights,x['row']['x']))]:
        probs=[(fn(x) if x['stronger_home'] else 1-fn(x)) for x in items]
        brier=sum((p-x['won'])**2 for p,x in zip(probs,items))/n
        logloss=sum(-(x['won']*math.log(max(1e-8,min(1-1e-8,p)))+(1-x['won'])*math.log(max(1e-8,min(1-1e-8,1-p)))) for p,x in zip(probs,items))/n
        parts.append(f'{model}: Brier={brier:.4f} LogLoss={logloss:.4f} meanP={sum(probs)/n:.1%}')
    if detail:
        constant=sum(x['won'] for x in items)/n
        # This is an oracle descriptive reference, NOT a deployable benchmark.
        oracle=constant*(1-constant)
        parts.append(f'constant-at-observed-rate Brier={oracle:.4f} (in-sample oracle; NOT predictive)')
    print(' | '.join(parts))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--start',default='2025-10-01')
    ap.add_argument('--days',type=int,default=90)
    ap.add_argument('--min-elo',type=float,default=50)
    ap.add_argument('--holdout',type=float,default=.25)
    args=ap.parse_args()
    if not 2<=args.days<=365 or not 0<args.min_elo<=500 or not .1<=args.holdout<=.5:ap.error('Invalid range')
    print('=== NHL COMEBACK VALIDATION V2 ===',flush=True)
    print('Read-only; no Kalshi prices, trades, or DB writes. One first trailing checkpoint per game.',flush=True)
    games,errors=collect(dt.date.fromisoformat(args.start),args.days)
    print(f'Completed games discovered: {len(games)}; scoreboard errors: {len(errors)}',flush=True)
    if errors:print('First scoreboard error:',errors[0],flush=True)
    all_games,candidates,outcomes=build(games,args.min_elo)
    print('Parse outcomes:',dict(outcomes),flush=True)
    if len(all_games)<40:
        print('INSUFFICIENT DATA: need at least 40 valid games');return
    cut=max(1,min(len(all_games)-1,round(len(all_games)*(1-args.holdout))))
    train_games,holdout_games=all_games[:cut],all_games[cut:]
    weights=train(train_games)
    train_ids={g['id'] for g in train_games}
    holdout_ids={g['id'] for g in holdout_games}
    print(f'Chronological split: training games={len(train_games)}, holdout games={len(holdout_games)}; fitted weights={[round(w,4) for w in weights]}')
    for split,ids in [('TRAIN',train_ids),('HOLDOUT',holdout_ids)]:
        items=[x for x in candidates if x['game']['id'] in ids]
        print(f'\n{split}: {len(items)} qualifying games (not independent checkpoints)',flush=True)
        report('ALL',items,weights)
        for period in (1,2,3):
            report(f'Period {period}',[x for x in items if (x['minute']-1)//20+1==period],weights,False)
        report('One-goal deficit',[x for x in items if x['deficit']==1],weights,False)
        report('Two+ goal deficit',[x for x in items if x['deficit']>=2],weights,False)
        for lo,hi in [(args.min_elo,100),(100,150),(150,float('inf'))]:
            if hi<=args.min_elo:continue
            subset=[x for x in items if max(args.min_elo,lo)<=x['elo_gap']<hi]
            report(f'Elo gap {max(args.min_elo,lo):g}–{hi if math.isfinite(hi) else "inf"}',subset,weights,False)
    print('\nCAVEATS: Subgroups may be tiny; Wilson intervals are game-level and do not include model-fit uncertainty.')
    print('Elo initialized at 1500; date-batched updates; no season resets; no deployment or trading eligibility.')

if __name__=='__main__':main()
