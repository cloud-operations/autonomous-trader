import requests

BASE = "https://external-api.kalshi.com/trade-api/v2"

def main():
    response = requests.get(
        f"{BASE}/series",
        params={"category": "Sports"},
        timeout=30,
    )
    response.raise_for_status()

    series = response.json().get("series", [])

    sports = [
        "NFL", "NBA", "NHL", "MLB",
        "MLS", "Tennis", "Soccer",
        "NCAA", "Football", "Hockey",
        "Basketball", "Baseball",
    ]

    print("GAME-RELATED SPORTS SERIES")
    print("=" * 70)

    for item in series:
        ticker = item.get("ticker", "")
        title = item.get("title", "")
        tags = ", ".join(item.get("tags") or [])

        text = f"{ticker} {title} {tags}".lower()

        if any(sport.lower() in text for sport in sports):
            if any(word in text for word in [
                "winner", "game", "match", "moneyline"
            ]):
                print(
                    f"{ticker} | {title} | {tags}"
                )

if __name__ == "__main__":
    main()
