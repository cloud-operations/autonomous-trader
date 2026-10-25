#!/usr/bin/env python3
"""Read-only NHL comeback quote backtest; never submits orders."""
import argparse,csv,json,re,sqlite3
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path

def ts(s):
 try:return datetime.fromisoformat(str(s).replace('Z','+00:00')).astimezone(timezone.utc)
 except (ValueError,TypeError):return None

def db(p):return sqlite3.connect(Path(p).resolve().as_uri()+'?mode=ro',uri=True)

def main():
 p=argparse.ArgumentParser()
 for flag,default in [('prices','data/market_history.db'),('states','data/game_states.db'),('elo','data/nhl_elo.json'),('output','data/nhl_comebacks_v3.csv')]:p.add_argument('--'+flag,default=default)
 for flag,default in [('min-elo',50),('min-drop-cents',10),('take-profit-cents',15),('stop-loss-cents',10),('max-hold-minutes',30),('score-delay-seconds',60),('max-score-age-seconds',120),('max-reference-age-hours',24),('position-dollars',10),('fee-per-contract-roundtrip',0)]:p.add_argument('--'+flag,type=float,default=default)
 a=p.parse_args(); elo=json.loads(Path(a.elo).read_text());pc=db(a.prices);gc=db(a.states)
 aliases={'TBL':'TB','LAK':'LA','SJS':'SJ','NJD':'NJ'}
 norm=lambda x:aliases.get(str(x).upper(),str(x).upper())
 games={};scores=defaultdict(list)
 for gid,date,home,away in gc.execute("SELECT game_id,MIN(game_date),MAX(home_abbr),MAX(away_abbr) FROM game_states WHERE UPPER(sport)='NHL' GROUP BY game_id"):
  home,away=norm(home),norm(away)
  if home not in elo or away not in elo:continue
  diff=float(elo[home])-float(elo[away]);strong=home if diff>=a.min_elo else away if diff<=-a.min_elo else None
  if strong:games[str(gid)]=dict(date=date,home=home,away=away,strong=strong,gap=abs(diff))
 for gid,at,status,home,away in gc.execute("SELECT game_id,fetched_at,status_name,home_score,away_score FROM game_states WHERE UPPER(sport)='NHL' ORDER BY fetched_at,id"):
  if str(gid) not in games or status!='STATUS_IN_PROGRESS':continue
  try:score=(ts(at),int(home),int(away))
  except (ValueError,TypeError):continue
  if score[0]:scores[str(gid)].append(score)
 quotes=defaultdict(list)
 for ticker,at,bid,ask in pc.execute("SELECT ticker,recorded_at,yes_bid,yes_ask FROM price_snapshots WHERE UPPER(sport)='NHL' ORDER BY recorded_at,id"):
  try:bid,ask=float(bid),float(ask)
  except (ValueError,TypeError):continue
  if ticker and ts(at) and 0<bid<=ask<1:quotes[ticker].append((ts(at),bid,ask))
 pattern=re.compile(r'^KXNHLGAME-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)-([A-Z]+)$');months={m:i for i,m in enumerate('JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split(),1)}
 candidates=defaultdict(list)
 for ticker in quotes:
  m=pattern.fullmatch(ticker)
  if not m:continue
  yy,mon,day,teams,side=m.groups()
  try:local=datetime(2000+int(yy),months[mon],int(day)).date()
  except (ValueError,KeyError):continue
  for gid,g in games.items():
   if norm(side)!=g['strong'] or teams not in (g['away']+g['home'],g['home']+g['away']):continue
   date=ts(g['date'])
   if date and abs((date.date()-local).days)<=1:candidates[gid].append(ticker)
 mapped={gid:v[0] for gid,v in candidates.items() if len(v)==1};ambiguous=sum(len(v)>1 for v in candidates.values())
 fields='game_id ticker stronger_team elo_gap reference_time reference_ask entry_time entry_score_away_home entry_ask drop_cents exit_time exit_bid quantity exit_reason gross_pnl fees net_pnl'.split()
 rows=[];with_live=0;no_reference=0
 for gid,ticker in mapped.items():
  obs=scores.get(gid,[])
  if not obs:continue
  with_live+=1;first=obs[0][0]
  prior=[(t,ask) for t,_,ask in quotes[ticker] if t<first and (first-t).total_seconds()<=a.max_reference_age_hours*3600]
  if not prior:no_reference+=1;continue
  ref_time,ref_ask=prior[-1];g=games[gid];idx=0;last=None;pos=None;entered=False
  for t,bid,ask in quotes[ticker]:
   if t<first:continue
   if pos and t>pos['entry_dt']:
    held=(t-pos['entry_dt']).total_seconds()/60;gain=(bid-pos['entry_ask'])*100
    reason='TAKE_PROFIT' if gain>=a.take_profit_cents else 'STOP_LOSS' if gain<=-a.stop_loss_cents else 'MAX_HOLD' if held>=a.max_hold_minutes else None
    if reason:
     gross=pos['quantity']*(bid-pos['entry_ask']);fees=pos['quantity']*a.fee_per_contract_roundtrip
     rows.append({**{k:v for k,v in pos.items() if k!='entry_dt'},'exit_time':t.isoformat(),'exit_bid':bid,'exit_reason':reason,'gross_pnl':round(gross,2),'fees':round(fees,2),'net_pnl':round(gross-fees,2)});pos=None
   if entered:continue
   while idx<len(obs) and obs[idx][0]+timedelta(seconds=a.score_delay_seconds)<=t:last=obs[idx];idx+=1
   if not last or not 0<=(t-last[0]).total_seconds()<=a.max_score_age_seconds:continue
   trailing=last[1]<last[2] if g['strong']==g['home'] else last[2]<last[1]
   drop=(ref_ask-ask)*100
   if not trailing or drop+1e-8<a.min_drop_cents:continue
   qty=int((a.position_dollars+1e-9)/ask)
   if qty<1:continue
   pos=dict(game_id=gid,ticker=ticker,stronger_team=g['strong'],elo_gap=round(g['gap'],1),reference_time=ref_time.isoformat(),reference_ask=ref_ask,entry_dt=t,entry_time=t.isoformat(),entry_score_away_home=f'{last[2]}-{last[1]}',entry_ask=ask,drop_cents=round(drop,2),quantity=qty)
   entered=True
  if pos:rows.append({**{k:v for k,v in pos.items() if k!='entry_dt'},'exit_time':'','exit_bid':'','exit_reason':'UNRESOLVED','gross_pnl':'','fees':'','net_pnl':''})
 Path(a.output).parent.mkdir(parents=True,exist_ok=True)
 with open(a.output,'w',newline='') as f:
  writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
 resolved=[r for r in rows if r['exit_reason']!='UNRESOLVED']
 print('NHL COMEBACK BACKTEST V3 — READ ONLY')
 print(f'Elo-eligible games: {len(games)}; mapped contracts: {len(mapped)}; ambiguous: {ambiguous}')
 print(f'Mapped with live scores: {with_live}; missing pregame reference: {no_reference}')
 print(f'Entries: {len(rows)}; resolved: {len(resolved)}; unresolved: {len(rows)-len(resolved)}')
 if resolved:print(f'Simulated resolved net P&L: ${sum(r["net_pnl"] for r in resolved):.2f}')
 print('CSV:',a.output)
 print('Caution: Elo not point-in-time; batch timestamps approximate; fees default zero; no fill/liquidity proof.')
 pc.close();gc.close()
if __name__=='__main__':main()
