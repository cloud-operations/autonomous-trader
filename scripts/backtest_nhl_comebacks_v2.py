#!/usr/bin/env python3
"""Read-only NHL score-linked quote-path exploration. No orders or DB writes."""
import argparse,csv,json,sqlite3
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path

def dt(s): return datetime.fromisoformat(s.replace('Z','+00:00'))
def connect(path): return sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro',uri=True)
def money(v): return f'{v:.2f}'
def main():
 p=argparse.ArgumentParser();p.add_argument('--prices',default='data/market_history.db');p.add_argument('--states',default='data/game_states.db');p.add_argument('--elo',default='data/nhl_elo.json');p.add_argument('--output',default='data/nhl_comebacks_v2.csv');p.add_argument('--min-elo',type=float,default=50);p.add_argument('--min-drop-cents',type=float,default=10);p.add_argument('--take-profit-cents',type=float,default=15);p.add_argument('--stop-loss-cents',type=float,default=10);p.add_argument('--max-hold-minutes',type=float,default=30);p.add_argument('--max-quote-age-seconds',type=float,default=90);p.add_argument('--max-score-age-seconds',type=float,default=120);p.add_argument('--position-dollars',type=float,default=10);p.add_argument('--fee-per-contract-roundtrip',type=float,default=0);a=p.parse_args()
 elo=json.loads(Path(a.elo).read_text());pc=connect(a.prices);gc=connect(a.states)
 games={}
 for gid,date,ha,aa in gc.execute("SELECT game_id,MIN(game_date),MAX(home_abbr),MAX(away_abbr) FROM game_states WHERE UPPER(sport)='NHL' GROUP BY game_id"):
  if not gid or not ha or not aa or ha not in elo or aa not in elo:continue
  gap=float(elo[ha])-float(elo[aa]);strong=ha if gap>=a.min_elo else aa if gap<=-a.min_elo else None
  if strong:games[gid]={'date':date,'home':ha,'away':aa,'strong':strong,'gap':abs(gap)}
 # Require unambiguous team and event date match; market event date is local calendar date.
 quotes=defaultdict(list)
 for ticker,t,bid,ask in pc.execute("SELECT ticker,recorded_at,yes_bid,yes_ask FROM price_snapshots WHERE UPPER(sport)='NHL' ORDER BY recorded_at,id"):
  if not ticker or not t or bid is None or ask is None or not 0<float(bid)<=float(ask)<1:continue
  quotes[ticker].append((dt(t),float(bid),float(ask)))
 # Parse Kalshi event date from KXNHLGAME-26OCT23MTLCHI-MTL and map via ESPN participants.
 from re import fullmatch
 months={'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
 mapped={};ambiguous=0
 for ticker,series in quotes.items():
  m=fullmatch(r'KXNHLGAME-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)-([A-Z]+)',ticker)
  if not m:continue
  yy,mon,dd,teams,side=m.groups()
  if mon not in months:continue
  try: local_date=datetime(2000+int(yy),months[mon],int(dd)).date()
  except ValueError:continue
  candidates=[]
  for gid,g in games.items():
   if g['strong']!=side:continue
   # Team concatenation varies in length; verify exactly either order.
   if teams not in (g['away']+g['home'],g['home']+g['away']):continue
   if not g['date']:continue
   # UTC event date may be next calendar day for North American games.
   if abs((dt(g['date']).date()-local_date).days)>1:continue
   candidates.append(gid)
  if len(candidates)==1:mapped[candidates[0]]=ticker
  elif len(candidates)>1:ambiguous+=1
 output=[];matched_live=0;eligible=0;no_exit=0
 for gid,ticker in mapped.items():
  g=games[gid];observations=[]
  for fetched,status,hs,aws in gc.execute("SELECT fetched_at,status_name,home_score,away_score FROM game_states WHERE UPPER(sport)='NHL' AND game_id=? ORDER BY fetched_at,id",(gid,)):
   if status!='STATUS_IN_PROGRESS':continue
   try: h=int(hs);aw=int(aws)
   except (TypeError,ValueError):continue
   observations.append((dt(fetched),h,aw))
  if not observations:continue
  matched_live+=1
  # For every quote, use only last known score at or before quote time.
  series=quotes[ticker];idx=0;last=None;baseline=None;position=None
  for t,bid,ask in series:
   while idx<len(observations) and observations[idx][0]<=t:
    last=observations[idx];idx+=1
   if last is None or (t-last[0]).total_seconds()>a.max_score_age_seconds:continue
   trailing=(last[1]<last[2]) if g['strong']==g['home'] else (last[2]<last[1])
   if baseline is None:baseline=ask
   # Only baseline quotes observed before an entry; no hindsight highs.
   baseline=max(baseline,ask)
   if position is None:
    if not trailing or (baseline-ask)*100<a.min_drop_cents:continue
    qty=int(a.position_dollars//ask)
    if qty<1:continue
    position={'entry':t,'ask':ask,'qty':qty,'score':f'{last[2]}-{last[1]}','baseline':baseline};eligible+=1
    continue
   # The next observed quote is the earliest possible exit.
   held=(t-position['entry']).total_seconds()/60
   gain=(bid-position['ask'])*100
   reason='TAKE_PROFIT' if gain>=a.take_profit_cents else 'STOP_LOSS' if gain<=-a.stop_loss_cents else 'MAX_HOLD' if held>=a.max_hold_minutes else None
   if reason:
    gross=position['qty']*(bid-position['ask']);fee=position['qty']*a.fee_per_contract_roundtrip
    output.append({'game_id':gid,'ticker':ticker,'stronger_team':g['strong'],'elo_gap':round(g['gap'],1),'entry_time':position['entry'].isoformat(),'entry_score_away_home':position['score'],'baseline_ask':position['baseline'],'entry_ask':position['ask'],'exit_time':t.isoformat(),'exit_bid':bid,'quantity':position['qty'],'exit_reason':reason,'gross_pnl':round(gross,2),'fees':round(fee,2),'net_pnl':round(gross-fee,2)})
    position=None
  if position:
   no_exit+=1
   output.append({'game_id':gid,'ticker':ticker,'stronger_team':g['strong'],'elo_gap':round(g['gap'],1),'entry_time':position['entry'].isoformat(),'entry_score_away_home':position['score'],'baseline_ask':position['baseline'],'entry_ask':position['ask'],'exit_time':'','exit_bid':'','quantity':position['qty'],'exit_reason':'UNRESOLVED','gross_pnl':'','fees':'','net_pnl':''})
 fields=['game_id','ticker','stronger_team','elo_gap','entry_time','entry_score_away_home','baseline_ask','entry_ask','exit_time','exit_bid','quantity','exit_reason','gross_pnl','fees','net_pnl']
 Path(a.output).parent.mkdir(parents=True,exist_ok=True)
 with open(a.output,'w',newline='') as f:
  writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(output)
 print('NHL SCORE-LINKED QUOTE EXPLORATION V2 — READ ONLY')
 print(f'Elo-eligible games: {len(games)}; mapped stronger-team contracts: {len(mapped)}; ambiguous mappings: {ambiguous}')
 print(f'Mapped games with live observations: {matched_live}; entries: {eligible}; resolved exits: {len(output)-no_exit}; unresolved: {no_exit}')
 print(f'CSV: {a.output}')
 print('CAUTION: Point-in-time Elo NOT verified; quote timestamp may predate fetch; no liquidity/fill proof; one-minute samples may miss price changes.')
 print('Do not interpret as validated strategy or live-executable P&L.')
 pc.close();gc.close()
if __name__=='__main__':main()
