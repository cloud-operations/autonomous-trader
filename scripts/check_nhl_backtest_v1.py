"""NHL historical heuristic backtest. Uses ESPN scoreboard and play summaries."""
import argparse
import datetime as dt
from collections import Counter
from trader.agents.nhl_backtest_v1 import get_games, evaluate_game, report, partition


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--start', default='2025-10-15', help='YYYY-MM-DD inclusive')
    p.add_argument('--days', type=int, default=3, help='1..31 days')
    p.add_argument('--max-games', type=int, default=20)
    p.add_argument('--cache-dir', default='data/nhl_backtest_cache')
    a = p.parse_args()
    if not 1 <= a.days <= 31 or not 1 <= a.max_games <= 100:
        p.error('--days must be 1..31 and --max-games 1..100')
    start = dt.date.fromisoformat(a.start)
    print('=== NHL HISTORICAL BACKTEST V1 ===')
    print('No Kalshi prices; no trades; no existing database writes.')
    print('Dates:', start, 'through', start + dt.timedelta(days=a.days-1))
    games = {}
    failures = Counter()
    for i in range(a.days):
        day = (start + dt.timedelta(days=i)).isoformat()
        try:
            for game in get_games(day, a.cache_dir):
                game_id = str(game.get('id') or '')
                if game_id:
                    games[game_id] = game
        except Exception as exc:
            failures['SCOREBOARD_FETCH_ERROR'] += 1
            print('Scoreboard error', day, type(exc).__name__, str(exc)[:160])
    rows = []
    considered = 0
    for game_id, event in sorted(games.items()):
        if considered >= a.max_games:
            break
        status = ((event.get('status') or {}).get('type') or {}).get('state')
        if status != 'post':
            failures['NOT_FINAL'] += 1
            continue
        considered += 1
        try:
            records, reason = evaluate_game(event, a.cache_dir)
            rows.extend(records)
            failures[reason] += 1
        except Exception as exc:
            failures['SUMMARY_FETCH_OR_PARSE_ERROR'] += 1
            print('Game error', game_id, type(exc).__name__, str(exc)[:160])
    print('Unique games discovered:', len(games), '| final games attempted:', considered)
    print('Outcomes:', dict(failures))
    report([r for r in rows if partition(r['game_id']) == 'DEVELOPMENT'], 'DEVELOPMENT')
    report([r for r in rows if partition(r['game_id']) == 'HOLDOUT'], 'HOLDOUT')
    if not rows:
        print('\nNo usable historical snapshots. ESPN may omit play-level scores; do not invent data.')
    print('\nThis is a diagnostic evaluation, not an independently validated probability model.')

if __name__ == '__main__':
    main()
