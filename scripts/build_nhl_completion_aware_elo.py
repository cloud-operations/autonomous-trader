#!/usr/bin/env python3
"""Read-only NHL Elo replay with assumed result availability; no orders.

Results become usable start + delay hours. This is an assumption, NOT observed
completion time. Pregame ratings and snapshots are computed from scratch.
"""
import argparse
import csv
import heapq
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def dt(s):
    d = datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('Game dates must include a UTC offset')
    return d.astimezone(timezone.utc)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', default='data/nhl_point_in_time_elo_v2.csv')
    p.add_argument('--csv-output', default='data/nhl_elo_completion_aware.csv')
    p.add_argument('--jsonl-output', default='data/nhl_elo_completion_aware.jsonl')
    p.add_argument('--delay-hours', type=float, default=4.0)
    p.add_argument('--initial-elo', type=float, default=1500.0)
    p.add_argument('--k', type=float, default=20.0)
    p.add_argument('--home-advantage', type=float, default=35.0)
    a = p.parse_args()
    if a.delay_hours <= 0 or a.k <= 0:
        p.error('--delay-hours and --k must be positive')
    with open(a.input, newline='') as f:
        rows = list(csv.DictReader(f))
    required = {'game_id', 'game_date', 'home_abbr', 'away_abbr', 'home_score', 'away_score'}
    if not rows or not required.issubset(rows[0]):
        p.error('Missing input rows or required columns')
    groups = defaultdict(list)
    seen = set()
    for r in rows:
        gid = r['game_id']
        if gid in seen:
            p.error(f'Duplicate game_id: {gid}')
        seen.add(gid)
        groups[dt(r['game_date'])].append(r)
    teams = sorted({r['home_abbr'] for r in rows} | {r['away_abbr'] for r in rows})
    ratings = {t: a.initial_elo for t in teams}
    delay = timedelta(hours=a.delay_hours)
    pending = []  # (available_at, game_id, home, away, home_score, away_score)
    out_rows, snapshots = [], []
    applied = 0
    for start, group in sorted(groups.items()):
        # Only apply results assumed available STRICTLY BEFORE this start.
        # Equal timestamps are excluded to avoid ordering ambiguity.
        while pending and pending[0][0] < start:
            available, gid, h, aw, hs, aws = heapq.heappop(pending)
            rh, ra = ratings[h], ratings[aw]
            expected = 1 / (1 + 10 ** ((ra - rh - a.home_advantage) / 400))
            actual = 1 if hs > aws else 0 if hs < aws else .5
            change = a.k * (actual - expected)
            ratings[h] += change
            ratings[aw] -= change
            applied += 1
        # V4 requires snapshot timestamp strictly less than scheduled start.
        # The 1-microsecond offset does not make the assumed completion time real.
        snapshot_time = start - timedelta(microseconds=1)
        snapshots.append({'as_of': snapshot_time.isoformat(),
                          'ratings': {t: round(v, 6) for t, v in sorted(ratings.items())}})
        for r in sorted(group, key=lambda x: x['game_id']):
            h, aw = r['home_abbr'], r['away_abbr']
            hs, aws = int(r['home_score']), int(r['away_score'])
            gap = ratings[h] - ratings[aw]
            expected = 1 / (1 + 10 ** ((ratings[aw] - ratings[h] - a.home_advantage) / 400))
            out_rows.append({
                'game_id': r['game_id'], 'game_date': r['game_date'],
                'away_abbr': aw, 'home_abbr': h,
                'away_pregame_elo': round(ratings[aw], 6),
                'home_pregame_elo': round(ratings[h], 6),
                'elo_gap_home_minus_away': round(gap, 6),
                'home_win_probability': round(expected, 8),
                'away_score': aws, 'home_score': hs,
                'assumed_result_available_at': (start + delay).isoformat(),
                'elo_method': f'assumed_start_plus_{a.delay_hours:g}h',
            })
            heapq.heappush(pending, (start + delay, r['game_id'], h, aw, hs, aws))
    csv_path = Path(a.csv_output)
    jsonl_path = Path(a.jsonl_output)
    if csv_path.resolve() == jsonl_path.resolve():
        p.error('CSV and JSONL outputs must be different files')
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    with jsonl_path.open('w') as f:
        for snap in snapshots:
            f.write(json.dumps(snap, separators=(',', ':')) + '\n')
    print(f'Completed games: {len(out_rows)}; snapshots: {len(snapshots)}; teams: {len(teams)}')
    print(f'Results applied before subsequent starts: {applied}; pending at final historical start: {len(pending)}')
    print(f'CSV: {csv_path}; JSONL: {jsonl_path}')
    print(f'ASSUMPTION: Results become available {a.delay_hours:g} hours after scheduled start.')
    print('CAUTION: Not certified leakage-free: actual game end/final publication times are unknown.')
    print('CAUTION: Same-availability-time results are applied in game-id order; affects subsequent ratings.')
    print('CAUTION: Snapshots stop at the last historical game start; future games need a refreshed as-of snapshot.')


if __name__ == '__main__':
    main()
