"""Read-only market metadata verification. Never infer YES team from ticker alone."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://external-api.kalshi.com/trade-api/v2'


def fetch_market(ticker, timeout=12):
    url = BASE + '/markets/' + urllib.parse.quote(ticker, safe='')
    req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'autonomous-trader-readonly/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)['market']


def normalize(s):
    return re.sub(r'[^a-z0-9]+', ' ', str(s).lower()).strip()


def classify(market, team_aliases):
    """Only explicit YES subtitle matching a unique supplied team alias is verified."""
    yes = normalize(market.get('yes_sub_title', ''))
    matches = []
    for team, aliases in team_aliases.items():
        if yes and any(yes == normalize(a) for a in aliases):
            matches.append(team)
    return matches[0] if len(matches) == 1 else None


def inspect(tickers, teams):
    results = []
    for ticker in tickers:
        try:
            market = fetch_market(ticker)
            team = classify(market, teams)
            results.append({'ticker': ticker, 'status': 'VERIFIED' if team else 'UNVERIFIED',
                            'team': team, 'event_ticker': market.get('event_ticker'),
                            'yes_sub_title': market.get('yes_sub_title'), 'title': market.get('title'),
                            'rules_primary': market.get('rules_primary'), 'error': None})
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError) as exc:
            results.append({'ticker': ticker, 'status': 'UNVERIFIED', 'team': None,
                            'event_ticker': None, 'yes_sub_title': None, 'title': None,
                            'rules_primary': None, 'error': str(exc)})
    return results
