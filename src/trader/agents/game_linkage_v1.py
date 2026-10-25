"""Conservative Kalshi-event -> ESPN-game linkage. Read-only."""
import datetime as dt
import json
import re
import sqlite3
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

KALSHI = 'https://api.elections.kalshi.com/trade-api/v2'
ESPN = {'NHL': ('hockey','nhl'), 'NBA': ('basketball','nba'), 'NFL': ('football','nfl')}
ALIASES = {
    'utah': 'utah mammoth', 'seattle': 'seattle kraken',
    'la clippers': 'los angeles clippers', 'ny knicks': 'new york knicks',
    'la lakers': 'los angeles lakers',
}

def get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'autonomous-trader-linkage/1.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)

def normalize(name):
    s = re.sub(r'[^a-z0-9 ]+', ' ', str(name).lower())
    s = ' '.join(s.split())
    return ALIASES.get(s, s)

def same_team(a,b):
    x,y = normalize(a), normalize(b)
    return x == y or (len(x)>=4 and (x in y or y in x) and (x.split()[0] == y.split()[0]))

def parse_date_from_event(ticker):
    m = re.search(r'-(\d{2})([A-Z]{3})(\d{2})', ticker)
    if not m: return None
    try: return dt.datetime.strptime('20'+m.group(1)+m.group(2)+m.group(3), '%Y%b%d').date()
    except ValueError: return None

def get_events_from_signals(db_path):
    con=sqlite3.connect(db_path)
    try:
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'signals' not in tables: return []
        cols={r[1] for r in con.execute('PRAGMA table_info(signals)')}
        if not {'ticker','sport'}.issubset(cols): raise ValueError('signals table needs ticker and sport columns')
        rows=con.execute('SELECT DISTINCT ticker, sport FROM signals WHERE ticker IS NOT NULL').fetchall()
    finally: con.close()
    groups={}
    for ticker,sport in rows:
        if '-' not in ticker: continue
        event=ticker.rsplit('-',1)[0]
        groups.setdefault((event,sport.upper()),set()).add(ticker)
    return [(event,sport,sorted(tickers)) for (event,sport),tickers in sorted(groups.items())]

def verify_kalshi(event_ticker, tickers):
    """Verify YES side from each market endpoint (nested event fields may be sparse)."""
    if len(tickers) != 2:
        return None, 'REQUIRES_TWO_DISTINCT_TEAMS'
    teams = []
    for ticker in tickers:
        market = get_json(KALSHI + '/markets/' + urllib.parse.quote(ticker, safe='')).get('market') or {}
        if market.get('ticker') != ticker or market.get('event_ticker') != event_ticker:
            return None, 'MARKET_EVENT_MISMATCH'
        subtitle = (market.get('yes_sub_title') or market.get('yes_subtitle') or '').strip()
        title = (market.get('title') or '').strip()
        rules = (market.get('rules_primary') or '').strip()
        if not subtitle or not title or not rules:
            return None, 'MISSING_MARKET_METADATA'
        # Require title to explicitly name the YES side as the winner, and
        # resolution rules to independently mention that team as the winner.
        # Compare the title and resolution rules against the *literal* YES
        # subtitle. normalize() expands city aliases (e.g. Seattle ->
        # Seattle Kraken), while Kalshi titles say "Seattle wins".
        yes_label = ' '.join(re.sub(r'[^a-z0-9 ]+', ' ', subtitle.lower()).split())
        title_norm = ' '.join(re.sub(r'[^a-z0-9 ]+', ' ', title.lower()).split())
        rules_norm = ' '.join(re.sub(r'[^a-z0-9 ]+', ' ', rules.lower()).split())
        if title_norm != yes_label + ' wins' or (yes_label + ' wins') not in rules_norm:
            return None, 'AMBIGUOUS_YES_TEAM'
        teams.append(subtitle)
    if same_team(teams[0], teams[1]):
        return None, 'REQUIRES_TWO_DISTINCT_TEAMS'
    return teams, 'VERIFIED'

def espn_candidates(sport, date):
    category,league=ESPN[sport]
    # Query adjacent dates because ESPN date/time boundaries differ by timezone.
    found={}
    for delta in (-1,0,1):
        day=(date+dt.timedelta(days=delta)).strftime('%Y%m%d')
        url=f'https://site.api.espn.com/apis/site/v2/sports/{category}/{league}/scoreboard?dates={day}'
        for event in get_json(url).get('events',[]): found[str(event.get('id'))]=event
    return list(found.values())

def link(event_ticker, sport, tickers):
    result={'event':event_ticker,'sport':sport,'tickers':tickers,'status':'UNVERIFIED','reason':'', 'espn_game_id':None}
    if sport not in ESPN: result['reason']='UNSUPPORTED_SPORT'; return result
    day=parse_date_from_event(event_ticker)
    if not day: result['reason']='UNKNOWN_EVENT_DATE'; return result
    result['event_date']=day.isoformat()
    try: teams,reason=verify_kalshi(event_ticker,tickers)
    except Exception as exc: result['reason']='KALSHI_FETCH_FAILED: '+str(exc); return result
    if teams is None: result['reason']=reason; return result
    result['yes_teams']=teams
    try: events=espn_candidates(sport,day)
    except Exception as exc: result['reason']='ESPN_FETCH_FAILED: '+str(exc); return result
    matches=[]
    for e in events:
        competitions=e.get('competitions') or []
        if not competitions: continue
        competitors=competitions[0].get('competitors') or []
        if len(competitors)!=2: continue
        names=[]
        for c in competitors:
            team=c.get('team') or {}
            names.append([team.get('displayName',''),team.get('shortDisplayName',''),team.get('name',''),team.get('abbreviation','')])
        if not ((any(same_team(teams[0],x) for x in names[0]) and any(same_team(teams[1],x) for x in names[1])) or
                (any(same_team(teams[0],x) for x in names[1]) and any(same_team(teams[1],x) for x in names[0]))): continue
        try: actual_day=dt.datetime.fromisoformat(e['date'].replace('Z','+00:00')).date()
        except (ValueError,KeyError): continue
        if abs((actual_day-day).days)>1: continue
        matches.append(e)
    if len(matches)!=1:
        result['reason']='NO_ESPN_MATCH' if not matches else 'AMBIGUOUS_ESPN_MATCH'
        result['candidate_count']=len(matches)
        return result
    e=matches[0]
    result.update(status='VERIFIED',reason='TWO_TEAMS_AND_EVENT_DATE_MATCH',espn_game_id=str(e['id']),espn_name=e.get('name'),espn_start=e.get('date'))
    return result
