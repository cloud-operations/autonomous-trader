"""Read-only ESPN scoreboard lookup for Kalshi momentum signals.

ESPN's public scoreboard API is unofficial and may change. Scoreboard
results are current/final, NOT point-in-time historical score snapshots.
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

SPORTS = {"NHL": ("hockey", "nhl"), "NBA": ("basketball", "nba"), "NFL": ("football", "nfl")}
ALIASES = {
    "utah": {"utah", "utah mammoth", "utah hockey club"},
    "seattle": {"seattle", "seattle kraken", "seattle seahawks"},
    "phoenix": {"phoenix", "phoenix suns"},
    "oklahoma city": {"oklahoma city", "oklahoma city thunder"},
}


def _names(team):
    return {str(team.get(k, "")).strip().lower() for k in ("displayName", "shortDisplayName", "name", "location", "abbreviation")}


def _team_matches(requested, team):
    requested = requested.strip().lower()
    names = _names(team)
    allowed = ALIASES.get(requested, {requested})
    return any(a == n or n.startswith(a + " ") for a in allowed for n in names if n)


class GameIntelligenceAgent:
    def __init__(self, timeout=12):
        self.timeout = timeout
        self._cache = {}

    def fetch_scoreboard(self, sport, date):
        if sport not in SPORTS:
            raise ValueError(f"Unsupported sport: {sport}")
        key = (sport, date)
        if key in self._cache:
            return self._cache[key]
        category, league = SPORTS[sport]
        url = (f"https://site.api.espn.com/apis/site/v2/sports/{category}/{league}/scoreboard?"
               + urllib.parse.urlencode({"dates": date, "limit": 500}))
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; research-scoreboard/1.0)"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            events = json.load(response).get("events", [])
        self._cache[key] = events
        return events

    def analyze_signal(self, signal):
        sport = signal["sport"]
        title = signal["event"]
        parts = title.split(" vs ")
        if len(parts) != 2:
            return {"matched": False, "error": "Event name is not 'Team vs Team'"}
        if sport not in SPORTS:
            return {"matched": False, "error": f"Unsupported sport: {sport}"}
        timestamp = datetime.fromisoformat(signal["detected_at"])
        # Date +/- 1 accounts for UTC/local date boundaries.
        dates = [(timestamp + timedelta(days=d)).strftime("%Y%m%d") for d in (0, -1, 1)]
        errors = []
        for date in dates:
            try:
                events = self.fetch_scoreboard(sport, date)
            except Exception as exc:
                errors.append(f"{date}: {type(exc).__name__}: {exc}")
                continue
            for event in events:
                competitions = event.get("competitions") or []
                if not competitions:
                    continue
                competitors = competitions[0].get("competitors") or []
                if len(competitors) != 2:
                    continue
                teams = [c.get("team") or {} for c in competitors]
                if not ((_team_matches(parts[0], teams[0]) and _team_matches(parts[1], teams[1])) or
                        (_team_matches(parts[0], teams[1]) and _team_matches(parts[1], teams[0]))):
                    continue
                status = event.get("status") or {}
                return {
                    "matched": True, "sport": sport, "event": title,
                    "game_id": event.get("id"), "game_date": event.get("date"),
                    "status": (status.get("type") or {}).get("description"),
                    "clock": status.get("displayClock"), "period": status.get("period"),
                    "teams": [{"team": (c.get("team") or {}).get("displayName"),
                               "score": c.get("score")} for c in competitors],
                    "historical_score_verified": False,
                    "warning": "Scoreboard shows latest/final state, not necessarily the state at signal time.",
                }
        return {"matched": False, "sport": sport, "event": title,
                "error": "; ".join(errors) if errors else "No matching ESPN game found"}
