"""Read-only correlation of Kalshi momentum signals with observed ESPN states."""
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def utc(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def norm(value):
    return re.sub(r'[^a-z0-9]+', '', str(value or '').lower())


ALIASES = {
    'utah': ('utah mammoth', 'utah hockey club'),
    'seattle': ('seattle kraken',),
    'phoenix': ('phoenix suns',),
    'oklahoma city': ('oklahoma city thunder',),
    'la clippers': ('los angeles clippers',),
    'la lakers': ('los angeles lakers',),
}


def team_matches(short, full):
    a, b = norm(short), norm(full)
    if not a or not b:
        return False
    return a == b or (len(a) >= 4 and a in b) or any(norm(x) == b for x in ALIASES.get(short.strip().lower(), ()))


def event_matches(label, row):
    teams = re.split(r'\s+vs\.?\s+', label or '', flags=re.IGNORECASE)
    if len(teams) != 2:
        return False
    combined = ' '.join(str(v) for v in row.values() if v is not None)
    return all(team_matches(team, combined) for team in teams)


class SignalCorrelationAgent:
    def __init__(self, db_path='data/game_states.db'):
        self.db_path = db_path

    def _load_states(self):
        if not Path(self.db_path).is_file():
            raise FileNotFoundError(f'Game-state database not found: {self.db_path}')
        with sqlite3.connect(f'file:{Path(self.db_path).resolve()}?mode=ro', uri=True) as conn:
            conn.row_factory = sqlite3.Row
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            candidates = []
            for table in tables:
                cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
                timecol = next((c for c in ('fetched_at', 'recorded_at', 'observed_at', 'collected_at', 'timestamp') if c in cols), None)
                sportcol = next((c for c in ('sport', 'league') if c in cols), None)
                if not timecol or not sportcol:
                    continue
                records = [dict(r) for r in conn.execute(f'SELECT * FROM "{table}" ORDER BY "{timecol}" DESC LIMIT 10000')]
                candidates.extend((r, timecol, sportcol) for r in records)
            if not candidates:
                raise ValueError('No recognized game-state table. Run: sqlite3 data/game_states.db ".schema" and share output.')
            return candidates

    def correlate(self, signals, max_age_minutes=3):
        states = self._load_states()
        output = []
        for signal in signals:
            when = utc(signal.get('detected_at'))
            base = dict(signal)
            base.update(correlation_status='NO_MATCH', age_minutes=None, game_state=None, reason='No matching prior game observation')
            if when is None:
                base['reason'] = 'Invalid signal timestamp'
                output.append(base)
                continue
            matches = []
            for state, timecol, sportcol in states:
                if norm(state.get(sportcol)) != norm(signal.get('sport')):
                    continue
                observed = utc(state.get(timecol))
                if observed is None or observed > when:
                    continue
                if event_matches(signal.get('event'), state):
                    matches.append((observed, state))
            if matches:
                observed, state = max(matches, key=lambda pair: pair[0])
                age = (when - observed).total_seconds() / 60
                base['age_minutes'] = round(age, 2)
                base['game_state'] = state
                status = str(next((state[k] for k in ('status', 'game_status', 'state') if k in state), '')).lower()
                if age > max_age_minutes:
                    base['correlation_status'] = 'STALE'
                    base['reason'] = f'Prior observation is {age:.1f} minutes old'
                elif any(x in status for x in ('final', 'post', 'completed', 'scheduled', 'pre')):
                    base['correlation_status'] = 'NOT_LIVE'
                    base['reason'] = f'Game status: {status or "unknown"}'
                elif not status:
                    base['correlation_status'] = 'UNVERIFIED'
                    base['reason'] = 'Game status unavailable'
                else:
                    base['correlation_status'] = 'MATCHED_LIVE_SNAPSHOT'
                    base['reason'] = 'Prior observation matched; score is not necessarily identical at signal time'
            output.append(base)
        return output
