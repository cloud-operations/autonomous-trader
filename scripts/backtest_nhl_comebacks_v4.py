#!/usr/bin/env python3
"""Read-only NHL comeback quote-path research. Never places orders."""
import argparse, csv, json, re, sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

MONTHS={m:i for i,m in enumerate('JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split(),1)}
TICKER=re.compile(r'^KXNHLGAME-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)-([A-Z]+)$')

def parse_dt(v):
    if not v:return None
    d=datetime.fromisoformat(str(v).replace('Z','+00:00'))
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)

def conn(path):
    return sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro',uri=True)

def historical_ratings(path):
    """JSONL: {\"as_of\": ISO UTC, \"ratings\": {\"MTL\": 1500, ...}}.
    Each record must represent ratings computed exclusively from completed prior games.
    """
    if not path:return []
    out=[]
    with open(path) as f:
        for n,line in enumerate(f,1):
            if not line.strip():continue
            rec=json.loads(line);ts=parse_dt(rec['as_of']);ratings=rec['ratings']
            if ts is None or not isinstance(ratings,dict):raise ValueError(f'Invalid Elo record line {n}')
            out.append((ts,ratings))
    return sorted(out,key=lambda x:x[0])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prices',default='data/market_history.db')
    p.add_argument('--states',default='data/game_states.db')
    p.add_argument('--elo',default='data/nhl_elo.json',help='Current Elo fallback; NOT valid historical point-in-time ratings')
    p.add_argument('--elo-history',help='JSONL of pregame point-in-time Elo rating snapshots')
    p.add_argument('--require-point-in-time-elo',action='store_true')
    p.add_argument('--output',default='data/nhl_comebacks_v4.csv')
    p.add_argument('--audit-output',default='data/nhl_comebacks_v4_audit.csv')
    p.add_argument('--min-elo',type=float,default=50)
    p.add_argument('--min-drop-cents',type=float,default=10)
    p.add_argument('--take-profit-cents',type=float,default=15)
    p.add_argument('--stop-loss-cents',type=float,default=10)
    p.add_argument('--max-hold-minutes',type=float,default=30)
    p.add_argument('--max-quote-age-seconds',type=float,default=90,help='Max separation between consecutive quotes used for an exit (else mark unresolved)')
    p.add_argument('--max-score-age-seconds',type=float,default=120)
    p.add_argument('--score-delay-seconds',type=float,default=60)
    p.add_argument('--position-dollars',type=float,default=10)
    p.add_argument('--fee-per-contract-roundtrip',type=float,default=0,help='User-supplied assumed total entry+exit fee per contract in dollars')
    p.add_argument('--baseline-window-minutes',type=float,default=120,help='Use last valid pregame quote within this many minutes of scheduled start')
    a=p.parse_args()
    for key in ('min_elo','min_drop_cents','take_profit_cents','stop_loss_cents','max_hold_minutes','max_quote_age_seconds','max_score_age_seconds','score_delay_seconds','position_dollars','fee_per_contract_roundtrip','baseline_window_minutes'):
        if getattr(a,key)<0: p.error(f'--{key.replace("_","-")} cannot be negative')
    if a.position_dollars==0:p.error('--position-dollars must be positive')
    if a.require_point_in_time_elo and not a.elo_history:p.error('--require-point-in-time-elo needs --elo-history')
    current=json.loads(Path(a.elo).read_text()) if Path(a.elo).exists() else {}
    history=historical_ratings(a.elo_history)
    pc=conn(a.prices);sc=conn(a.states)
    games={}
    for gid,game_date,home,away in sc.execute('''SELECT game_id,MIN(game_date),MAX(home_abbr),MAX(away_abbr)
           FROM game_states WHERE UPPER(sport)='NHL' GROUP BY game_id'''):
        if not (gid and game_date and home and away):continue
        start=parse_dt(game_date)
        if not start:continue
        ratings=None;elo_source='CURRENT_SNAPSHOT_NOT_POINT_IN_TIME'
        for stamp,r in history:
            if stamp<start:ratings=r;elo_source='HISTORICAL_SNAPSHOT'
            else:break
        if ratings is None:
            if a.require_point_in_time_elo:continue
            ratings=current
        if home not in ratings or away not in ratings:continue
        gap=float(ratings[home])-float(ratings[away])
        strong=home if gap>=a.min_elo else away if gap<=-a.min_elo else None
        if strong:games[str(gid)]={'start':start,'home':home,'away':away,'strong':strong,'gap':abs(gap),'elo_source':elo_source}
    quotes=defaultdict(list)
    for ticker,stamp,bid,ask in pc.execute('''SELECT ticker,recorded_at,yes_bid,yes_ask FROM price_snapshots
                                          WHERE UPPER(sport)='NHL' ORDER BY recorded_at,id'''):
        if not ticker or not stamp or bid is None or ask is None:continue
        bid=float(bid);ask=float(ask)
        if not 0<bid<=ask<1:continue
        quotes[ticker].append((parse_dt(stamp),bid,ask))
    # Deduplicate repeated quote timestamps, conservatively keep last observed row.
    for ticker,seq in quotes.items():
        by_time={t:(t,bid,ask) for t,bid,ask in seq if t is not None}
        quotes[ticker]=sorted(by_time.values(),key=lambda q:q[0])
    matches=defaultdict(list)
    for ticker in quotes:
        m=TICKER.fullmatch(ticker)
        if not m:continue
        yy,mon,dd,teams,side=m.groups()
        if mon not in MONTHS:continue
        try:local=datetime(2000+int(yy),MONTHS[mon],int(dd)).date()
        except ValueError:continue
        for gid,g in games.items():
            if side!=g['strong']:continue
            if teams!=g['away']+g['home']:continue  # Kalshi standard away-home order; do not silently reverse
            if abs((g['start'].date()-local).days)>1:continue
            matches[gid].append(ticker)
    audit=[];trades=[];stats=defaultdict(int)
    for gid,g in sorted(games.items(),key=lambda kv:kv[1]['start']):
        rec={'game_id':gid,'away':g['away'],'home':g['home'],'stronger_team':g['strong'],
             'elo_gap':round(g['gap'],1),'elo_source':g['elo_source'],'ticker':'','status':'','detail':''}
        candidates=matches.get(gid,[])
        if len(candidates)!=1:
            rec['status']='NO_UNAMBIGUOUS_CONTRACT';rec['detail']=f'{len(candidates)} candidates';audit.append(rec);stats[rec['status']]+=1;continue
        ticker=candidates[0];rec['ticker']=ticker;seq=quotes[ticker]
        pre=[q for q in seq if g['start']-timedelta(minutes=a.baseline_window_minutes)<=q[0]<g['start']]
        if not pre:
            rec['status']='NO_PREGAME_QUOTE';rec['detail']='No valid pregame ask within baseline window';audit.append(rec);stats[rec['status']]+=1;continue
        base_time,_,baseline=pre[-1]
        scores=[]
        for fetched,status,home_score,away_score in sc.execute('''SELECT fetched_at,status_name,home_score,away_score
            FROM game_states WHERE UPPER(sport)='NHL' AND game_id=? ORDER BY fetched_at,id''',(gid,)):
            if status!='STATUS_IN_PROGRESS':continue
            try:scores.append((parse_dt(fetched),int(home_score),int(away_score)))
            except (ValueError,TypeError):continue
        scores.sort(key=lambda v:v[0]);rec['detail']=f'baseline={baseline:.2f} at {base_time.isoformat()}; live_scores={len(scores)}'
        if not scores:
            rec['status']='NO_LIVE_SCORE';audit.append(rec);stats[rec['status']]+=1;continue
        idx=0;last=None;position=None;last_quote_time=None;closed=False
        for t,bid,ask in seq:
            if t<g['start']:continue
            # Only scores fetched at least delay seconds before the quote are eligible.
            cutoff=t-timedelta(seconds=a.score_delay_seconds)
            while idx<len(scores) and scores[idx][0]<=cutoff:
                last=scores[idx];idx+=1
            if position is not None:
                held=(t-parse_dt(position['entry_time'])).total_seconds()/60
                gap_seconds=(t-last_quote_time).total_seconds() if last_quote_time else 0
                if gap_seconds>a.max_quote_age_seconds:
                    rec['detail'] += f'; stale_gap={gap_seconds:.1f}s at {t.isoformat()}'
                    rec['status']='UNRESOLVED_STALE_QUOTE_GAP';stats[rec['status']]+=1
                    trades.append({**position,'exit_time':'','exit_bid':'','exit_reason':'UNRESOLVED_STALE_QUOTE_GAP','gross_pnl':'','fees':'','net_pnl':''})
                    position=None;closed=True;break
                gain=(bid-position['entry_ask'])*100
                reason='TAKE_PROFIT' if gain>=a.take_profit_cents else 'STOP_LOSS' if gain<=-a.stop_loss_cents else 'MAX_HOLD' if held>=a.max_hold_minutes else None
                if reason:
                    gross=position['quantity']*(bid-position['entry_ask']);fee=position['quantity']*a.fee_per_contract_roundtrip
                    trades.append({**position,'exit_time':t.isoformat(),'exit_bid':bid,'exit_reason':reason,'gross_pnl':round(gross,2),'fees':round(fee,2),'net_pnl':round(gross-fee,2)})
                    rec['status']='CLOSED';stats[rec['status']]+=1;position=None;closed=True;break
                last_quote_time=t
                continue
            if closed:break
            if last is None:continue
            age=(t-last[0]).total_seconds()
            if age<0 or age>a.max_score_age_seconds:continue
            trailing=last[1]<last[2] if g['strong']==g['home'] else last[2]<last[1]
            if not trailing or (baseline-ask)*100<a.min_drop_cents:continue
            qty=int(a.position_dollars/ask)
            if qty<1:continue
            position={'game_id':gid,'ticker':ticker,'stronger_team':g['strong'],'elo_gap':round(g['gap'],1),
                      'elo_source':g['elo_source'],'baseline_time':base_time.isoformat(),'baseline_ask':baseline,
                      'entry_time':t.isoformat(),'entry_score_away_home':f'{last[2]}-{last[1]}',
                      'entry_ask':ask,'quantity':qty,'score_age_seconds':round(age,1)}
            last_quote_time=t
        if position:
            trades.append({**position,'exit_time':'','exit_bid':'','exit_reason':'UNRESOLVED_END_OF_DATA','gross_pnl':'','fees':'','net_pnl':''})
            rec['status']='UNRESOLVED_END_OF_DATA';stats[rec['status']]+=1
        elif not closed:
            rec['status']='NO_ENTRY_SIGNAL';stats[rec['status']]+=1
        audit.append(rec)
    trade_cols=['game_id','ticker','stronger_team','elo_gap','elo_source','baseline_time','baseline_ask','entry_time','entry_score_away_home','entry_ask','quantity','score_age_seconds','exit_time','exit_bid','exit_reason','gross_pnl','fees','net_pnl']
    audit_cols=['game_id','away','home','stronger_team','elo_gap','elo_source','ticker','status','detail']
    for path,rows,cols in ((a.output,trades,trade_cols),(a.audit_output,audit,audit_cols)):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with open(path,'w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(rows)
    closed=[r for r in trades if r['exit_reason'] in ('TAKE_PROFIT','STOP_LOSS','MAX_HOLD')]
    print('NHL COMEBACK BACKTEST V4 — READ ONLY')
    print(f'Elo-eligible games: {len(games)}; uniquely mapped: {sum(len(v)==1 for v in matches.values())}')
    print(f'Entries: {len(trades)}; closed: {len(closed)}; unresolved: {len(trades)-len(closed)}')
    print('Audit: '+', '.join(f'{k}={v}' for k,v in sorted(stats.items())))
    if closed:print(f'Closed-trade net P&L under supplied fee assumption: ${sum(float(r["net_pnl"]) for r in closed):.2f} (NOT realized or fill-verified)')
    print(f'Trades CSV: {a.output}; audit CSV: {a.audit_output}')
    print('WARNING: Current Elo fallback is NOT point-in-time. Fee default is zero; quotes do not prove executable liquidity/fills.')
    print('WARNING: Collection timestamps are approximate; a score delay reduces but cannot eliminate synchronization risk.')
    pc.close();sc.close()

if __name__=='__main__':main()
