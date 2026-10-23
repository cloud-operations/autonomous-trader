
from trader.providers.kalshi import KalshiProvider


def main():
    provider = KalshiProvider()

    try:
        markets = provider.get_markets(
            limit=100,
            max_pages=3,
        )
    except Exception as exc:
        print(f"Kalshi request failed: {exc}")
        return

    print(f"Retrieved {len(markets)} markets")

    for market in markets[:10]:
        print(
            market.get("ticker"),
            "|",
            market.get("title"),
            "| Bid:",
            market.get("yes_bid_dollars"),
            "| Ask:",
            market.get("yes_ask_dollars"),
        )


if __name__ == "__main__":
    main()

