import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from decimal import Decimal, InvalidOperation


BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

SPORTS_SERIES = {
    "NFL": "KXNFLGAME",
    "NBA": "KXNBAGAME",
    "NHL": "KXNHLGAME",
    "UCL": "KXUCLGAME",
}


def parse_price(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


class SportsMarketProvider:
    def __init__(self):
        self.session = requests.Session()

        retry_policy = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )

        adapter = HTTPAdapter(
            max_retries=retry_policy,
            pool_connections=10,
            pool_maxsize=10,
        )

        self.session.mount(BASE_URL + "/", adapter)

    def get_events(self, series_ticker, max_pages=5):
        events = []
        cursor = None

        for _ in range(max_pages):
            params = {
                "series_ticker": series_ticker,
                "status": "open",
                "with_nested_markets": "true",
                "limit": 100,
            }

            if cursor:
                params["cursor"] = cursor

            response = self.session.get(
                f"{BASE_URL}/events",
                params=params,
                timeout=20,
            )
            response.raise_for_status()

            payload = response.json()
            events.extend(payload.get("events", []))

            cursor = payload.get("cursor")
            if not cursor:
                break

        return events

    def discover(self):
        results = []

        for sport, series_ticker in SPORTS_SERIES.items():
            events = self.get_events(series_ticker)

            for event in events:
                for market in event.get("markets", []):
                    bid = parse_price(
                        market.get("yes_bid_dollars")
                    )
                    ask = parse_price(
                        market.get("yes_ask_dollars")
                    )

                    if not (
                        Decimal("0") < bid <= ask < Decimal("1")
                    ):
                        continue

                    results.append({
                        "sport": sport,
                        "event": event.get("title"),
                        "ticker": market.get("ticker"),
                        "yes_bid": bid,
                        "yes_ask": ask,
                        "spread": ask - bid,
                        "close_time": market.get("close_time"),
                    })

        return results
