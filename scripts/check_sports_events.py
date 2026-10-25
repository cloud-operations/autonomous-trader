import requests

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"


def main():
    response = requests.get(
        f"{BASE_URL}/events",
        params={
            "limit": 100,
            "status": "open",
            "with_nested_markets": "true",
        },
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()
    events = payload.get("events", [])

    print(f"Events returned: {len(events)}")
    print(f"Next cursor: {payload.get('cursor')}")
    print()

    for event in events[:30]:
        print(
            "CATEGORY:", event.get("category"),
            "| SERIES:", event.get("series_ticker"),
            "| EVENT:", event.get("event_ticker"),
            "| TITLE:", event.get("title"),
            "| MARKETS:", len(event.get("markets", [])),
        )


if __name__ == "__main__":
    main()
