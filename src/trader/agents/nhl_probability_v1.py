"""Experimental NHL regulation/final winner probability heuristic; no market prices.

NOT calibrated. Requires a LIVE, recent, timestamped game snapshot.
Scores alone do not encode overtime/shootout probabilities or team strength.
"""
from datetime import datetime, timezone
import math


def parse_utc(value):
    if not value:
        raise ValueError('Missing timestamp')
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp must include UTC offset')
    return parsed.astimezone(timezone.utc)


def estimate_nhl(home_score, away_score, period, clock_seconds, status,
                 fetched_at, now=None, max_age_seconds=600, home_strength=0.0):
    """Return illustrative win chances, or UNVERIFIED if inputs are insufficient.

    home_strength: optional *independent* pregame log-odds adjustment, default 0.
    Only intended for use with separately validated team ratings.
    """
    now = now or datetime.now(timezone.utc)
    age = (now - parse_utc(fetched_at)).total_seconds()
    if age < -30 or age > max_age_seconds:
        return {'status':'UNVERIFIED', 'reason':'STALE_OR_FUTURE_SNAPSHOT', 'age_seconds':round(age)}
    if str(status).lower() not in ('in progress', 'in_progress', 'live'):
        return {'status':'UNVERIFIED', 'reason':'GAME_NOT_LIVE'}
    if not isinstance(period, int) or period not in (1,2,3):
        return {'status':'UNVERIFIED', 'reason':'PERIOD_NOT_SUPPORTED'}
    if clock_seconds is None or not 0 <= clock_seconds <= 1200:
        return {'status':'UNVERIFIED', 'reason':'INVALID_CLOCK'}
    if not all(isinstance(s, int) and s >= 0 for s in (home_score, away_score)):
        return {'status':'UNVERIFIED', 'reason':'INVALID_SCORE'}
    if not -2.0 <= home_strength <= 2.0:
        return {'status':'UNVERIFIED', 'reason':'INVALID_STRENGTH'}
    # A transparent heuristic, NOT a fitted NHL statistical model.
    minutes_left = (3-period)*20 + clock_seconds/60
    diff = home_score-away_score
    # Later leads matter more; cap log odds to avoid artificial certainty.
    time_weight = 0.75 + 3.0*(1-minutes_left/60)**1.5
    log_odds = max(-7, min(7, diff*time_weight + 0.12 + home_strength))
    p = 1/(1+math.exp(-log_odds))
    return {'status':'EXPERIMENTAL', 'home_win_probability':round(p,4),
            'away_win_probability':round(1-p,4), 'minutes_left':round(minutes_left,2),
            'score_diff_home':diff, 'age_seconds':round(age),
            'method':'uncalibrated_heuristic', 'trade_eligible':False}
