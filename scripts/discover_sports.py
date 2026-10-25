import requests
from collections import Counter

BASE = "https://external-api.kalshi.com/trade-api/v2"
session = requests.Session()


def get(path, params=None):
    response = session.get(
        BASE + path,
        params=params,
        timeout=25,
    )
    response.raise_for_status()
    return response.json()


def main():
    # Discover sports series directly.
    series = get("/series", {"category": "Sports"}).get("series", [])

    print(f"Sports series found: {len(series)}")

    # Display sport categories/tags for inspection.
    tags = Counter()
    for item in series:
        tags.update(item.get("tags") or [])

    print("\nTop sports tags:")
    for tag, count in tags.most_common(20):
        print(f"  {tag}: {count}")

    # Prioritize recurring game-related series.
    keywords = (
        "game", "match", "winner",
        "moneyline", "football",
        "basketball", "hockey",
        "soccer", "tennis", "baseball",
    )

    candidates = [
        item for item in series
        if any(
            word in (
                item.get("title", "") + " " +
                " ".join(item.get("tags") or [])
            ).lower()
            for word in keywords
        )
        and "crosscategory" not in item.get("ticker", "").lower()
    ]

    print(f"\nCandidate series: {len(candidates)}")

    total_events = 0
    total_markets = 0

    # Limit requests during initial diagnostics.
    for item in candidates[:15]:
        ticker = item["ticker"]

        try:
            data = get("/events", {
                "series_ticker": ticker,
                "status": "open",
                "with_nested_markets": "true",
                "limit": 100,
            })
        except requests.RequestException as exc:
            print(f"Error for {ticker}: {exc}")
            continue

        events = data.get("events", [])
        total_events += len(events)

        print(f"\nSERIES: {ticker} | {item.get('title')}")
        print(f"Open events: {len(events)}")

        for event in events[:3]:
            print(" EVENT:", event.get("title"))

            for market in event.get("markets", [])[:3]:
                total_markets += 1
                print(
                    "  MARKET:", market.get("ticker"),
                    "| BID:", market.get("yes_bid_dollars"),
                    "| ASK:", market.get("yes_ask_dollars"),
                    "| CLOSE:", market.get("close_time"),
                )

    print("\n--- SUMMARY ---")
    print("Sports series:", len(series))
    print("Candidate series:", len(candidates))
    print("Open events inspected:", total_events)
    print("Sample markets displayed:", total_markets)


if __name__ == "__main__":
    main()
