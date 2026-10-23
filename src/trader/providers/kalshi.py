
import requests


class KalshiProvider:
    BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json"
        })

    def get_markets(self, limit=100, max_pages=3):
        markets = []
        cursor = None

        for _ in range(max_pages):
            params = {
                "limit": min(limit, 1000),
                "status": "open",
            }

            if cursor:
                params["cursor"] = cursor

            response = self.session.get(
                f"{self.BASE_URL}/markets",
                params=params,
                timeout=15,
            )
            response.raise_for_status()

            payload = response.json()
            markets.extend(payload.get("markets", []))

            cursor = payload.get("cursor")
            if not cursor:
                break

        return markets

