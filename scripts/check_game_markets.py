from trader.providers.sports_markets import SportsMarketProvider


def main():
    provider = SportsMarketProvider()
    markets = provider.discover()

    print(f"Tradable quote candidates: {len(markets)}")
    print()

    for market in markets[:30]:
        print(
            market["sport"],
            "|", market["event"],
            "|", market["ticker"],
            "| Bid:", market["yes_bid"],
            "| Ask:", market["yes_ask"],
            "| Spread:", market["spread"],
        )


if __name__ == "__main__":
    main()
