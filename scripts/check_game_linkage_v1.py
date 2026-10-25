import argparse
import json
import os
from trader.agents.game_linkage_v1 import get_events_from_signals, link

def main():
    p=argparse.ArgumentParser(description='Read-only Kalshi to ESPN game linkage')
    p.add_argument('--signals-db',default='data/signal_tracker.db')
    args=p.parse_args()
    if not os.path.isfile(args.signals_db):
        p.error('Missing signal database: '+args.signals_db)
    events=get_events_from_signals(args.signals_db)
    print('=== GAME LINKAGE V1 ===')
    print('Events:',len(events),'| Read-only, no trades or DB writes')
    for event,sport,tickers in events:
        print(json.dumps(link(event,sport,tickers),indent=2))

if __name__=='__main__': main()
