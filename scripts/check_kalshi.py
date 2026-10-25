from decimal import Decimal, InvalidOperation

from trader.providers.kalshi import KalshiProvider


def price(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def main():
    provider = KalshiProvider()
    markets = provider.get_markets(
        limit=100,
        max_pages=10,
    )

    print(f"Total retrieved: {len(markets)}")

    single_markets = []
    liquid_markets = []

    for market in markets:
        ticker = market.get("ticker", "")

        # Temporarily exclude known combination markets
        if ticker.startswith("KXMVECROSSCATEGORY"):
            continue

        single_markets.append(market)

        bid = price(market.get("yes_bid_dollars"))
        ask = price(market.get("yes_ask_dollars"))

        if Decimal("0") < bid <= ask < Decimal("1"):
            liquid_markets.append(market)

    print(f"After combination exclusion: {len(single_markets)}")
    print(f"Markets with two-sided quotes: {len(liquid_markets)}")

    for market in liquid_markets[:20]:
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
