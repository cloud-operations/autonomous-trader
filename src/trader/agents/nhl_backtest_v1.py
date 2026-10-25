"""Historical NHL heuristic evaluation. Read-only; no market data."""
import datetime as dt
import hashlib
import json
import math
import urllib.request
from collections import defaultdict
from pathlib import Path

from trader.agents.nhl_probability_v1 import estimate_nhl

BASE = 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl'


def fetch_json(url, cache_path):
    path = Path(cache_path)
    if path.exists():
        return json.loads(path.read_text())
    req = urllib.request.Request(url, headers={'Accept':'application/json','User-Agent':'autonomous-trader-backtest/1.0'})
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.load(response)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return payload


def get_games(day, cache_dir):
    date = dt.date.fromisoformat(day)
    url = BASE + '/scoreboard?dates=' + date.strftime('%Y%m%d')
    return fetch_json(url, Path(cache_dir) / ('scoreboard_' + date.isoformat() + '.json')).get('events', [])


def _competitors(event):
    competitions = event.get('competitions') or []
    if not competitions:
        return None
    competitors = competitions[0].get('competitors') or []
    by_side = {c.get('homeAway'): c for c in competitors}
    if 'home' not in by_side or 'away' not in by_side:
        return None
    return by_side


def _final_scores(event):
    sides = _competitors(event)
    if not sides:
        return None
    state = ((event.get('status') or {}).get('type') or {}).get('state')
    if state != 'post':
        return None
    try:
        hs = int(sides['home']['score'])
        aw = int(sides['away']['score'])
    except (KeyError, TypeError, ValueError):
        return None
    if hs == aw:
        return None
    return hs, aw


def _clock_seconds(play):
    clock = play.get('clock') or {}
    val = clock.get('value')
    if val is not None:
        try:
            n = float(val)
            if 0 <= n <= 1200:
                return n
        except (ValueError, TypeError):
            pass
    display = str(clock.get('displayValue') or '')
    if ':' in display:
        try:
            mm, ss = display.split(':', 1)
            n = int(mm) * 60 + float(ss)
            return n if 0 <= n <= 1200 else None
        except (ValueError, TypeError):
            return None
    return None


def _play_period(play):
    p = play.get('period') or {}
    try:
        return int(p.get('number') if isinstance(p, dict) else p)
    except (TypeError, ValueError):
        return None


def states_from_summary(summary, final_home, final_away):
    """Use only recorded scores in plays; no final-score backfilling."""
    plays = summary.get('plays') or []
    if isinstance(plays, dict):
        plays = plays.get('plays') or plays.get('items') or []
    if not isinstance(plays, list):
        return []
    buckets = {}
    for play in plays:
        if not isinstance(play, dict):
            continue
        period = _play_period(play)
        seconds = _clock_seconds(play)
        if period not in (1, 2, 3) or seconds is None:
            continue
        try:
            home = int(play['homeScore'])
            away = int(play['awayScore'])
        except (KeyError, TypeError, ValueError):
            continue
        if min(home, away) < 0 or home > final_home or away > final_away:
            continue
        # Keep one play per 5-minute clock checkpoint (prefer closest earlier-in-game play).
        elapsed = (period - 1) * 1200 + (1200 - seconds)
        checkpoint = int(elapsed // 300)
        if checkpoint >= 12:
            continue
        old = buckets.get(checkpoint)
        if old is None or elapsed > old[0]:
            buckets[checkpoint] = (elapsed, home, away, period, seconds)
    return [buckets[k] for k in sorted(buckets)]


def evaluate_game(event, cache_dir):
    scores = _final_scores(event)
    if not scores:
        return [], 'NOT_FINAL_OR_TIED'
    game_id = str(event.get('id') or '')
    if not game_id.isdigit():
        return [], 'MISSING_GAME_ID'
    url = BASE + '/summary?event=' + game_id
    summary = fetch_json(url, Path(cache_dir) / ('summary_' + game_id + '.json'))
    states = states_from_summary(summary, *scores)
    if not states:
        return [], 'NO_USABLE_PLAY_SCORES'
    final_home, final_away = scores
    winner = 1 if final_home > final_away else 0
    now = dt.datetime.now(dt.timezone.utc)
    timestamp = now.isoformat()
    rows = []
    for elapsed, home, away, period, seconds in states:
        pred = estimate_nhl(home, away, period, seconds, 'In Progress', timestamp, now=now)
        if pred.get('status') != 'EXPERIMENTAL':
            continue
        p = pred['home_win_probability']
        rows.append({'game_id':game_id,'period':period,'seconds_left':seconds,'home_score':home,
                     'away_score':away,'home_win_p':p,'home_won':winner,'brier':(p-winner)**2})
    return rows, 'OK' if rows else 'MODEL_REJECTED_STATES'


def report(rows, label):
    games = len(set(r['game_id'] for r in rows))
    print(f'\n{label}: games={games} snapshots={len(rows)}')
    if not rows:
        print('No eligible states; cannot score this set.')
        return
    # Game-weighted Brier avoids giving games with more play data disproportionate weight.
    by_game = defaultdict(list)
    for r in rows:
        by_game[r['game_id']].append(r['brier'])
    brier = sum(sum(v)/len(v) for v in by_game.values())/len(by_game)
    print(f'Game-weighted Brier={brier:.4f} (lower is better; not yet a calibrated model)')
    bins = defaultdict(list)
    for r in rows:
        bin_name = min(9, int(r['home_win_p'] * 10))
        bins[bin_name].append(r)
    print('Home win probability bins: range | samples | predicted avg | actual home win rate')
    for b in sorted(bins):
        group = bins[b]
        print(f' {b*10:02d}-{(b+1)*10:02d}% | {len(group):4d} | '
              f'{sum(r["home_win_p"] for r in group)/len(group):.1%} | '
              f'{sum(r["home_won"] for r in group)/len(group):.1%}')
    print('Note: snapshots from the same game share an outcome; bin counts are not independent games.')


def partition(game_id):
    # Deterministic, by game, no tuning or label leakage.
    return 'HOLDOUT' if int(hashlib.sha256(game_id.encode()).hexdigest()[:8], 16) % 5 == 0 else 'DEVELOPMENT'
