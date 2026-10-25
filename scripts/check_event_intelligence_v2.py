"""Read-only verification for Utah vs Seattle historical contracts."""
from trader.agents.event_intelligence_v2 import inspect

TICKERS = [
    'KXNHLGAME-26OCT22UTASEA-SEA',
    'KXNHLGAME-26OCT22UTASEA-UTA',
]
TEAMS = {
    'Seattle Kraken': ['Seattle Kraken', 'Seattle', 'SEA'],
    'Utah Mammoth': ['Utah Mammoth', 'Utah', 'UTA'],
}


def main():
    print('=== EVENT INTELLIGENCE V2 ===')
    print('Read-only Kalshi metadata verification; no trades or database writes.')
    results = inspect(TICKERS, TEAMS)
    for r in results:
        print('\nTicker:', r['ticker'])
        print('Status:', r['status'])
        print('YES team:', r['team'] or 'UNVERIFIED')
        print('Event:', r['event_ticker'] or 'UNKNOWN')
        print('YES subtitle:', r['yes_sub_title'] or 'UNKNOWN')
        print('Market title:', r['title'] or 'UNKNOWN')
        if r['error']:
            print('API error:', r['error'])
        if r['rules_primary']:
            print('Rules excerpt:', ' '.join(r['rules_primary'].split())[:240])
    events = {r['event_ticker'] for r in results if r['event_ticker']}
    verified = [r for r in results if r['status'] == 'VERIFIED']
    distinct = len({r['team'] for r in verified}) == len(verified)
    same_event = len(events) == 1 and all(r['event_ticker'] for r in results)
    print('\nEvent linkage:', 'VERIFIED' if same_event else 'UNVERIFIED')
    print('Distinct YES teams:', 'VERIFIED' if len(verified) == len(results) and distinct else 'UNVERIFIED')
    print('ESPN game-ID linkage: NOT IMPLEMENTED (requires date and team cross-check)')

if __name__ == '__main__':
    main()
