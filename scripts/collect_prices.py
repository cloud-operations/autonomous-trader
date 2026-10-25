from trader.providers.sports_markets import SportsMarketProvider
from trader.database.price_history import PriceHistory


def main():
    print("Fetching Kalshi sports markets...")

    provider = SportsMarketProvider()
    markets = provider.discover()

    print(f"Markets discovered: {len(markets)}")

    history = PriceHistory()
    saved = history.save_markets(markets)

    print(f"Snapshots saved: {saved}")

    total, contracts, first, last = history.summary()

    print("\n--- DATABASE SUMMARY ---")
    print(f"Total snapshots: {total}")
    print(f"Unique contracts: {contracts}")
    print(f"First snapshot: {first}")
    print(f"Latest snapshot: {last}")

    if markets:
        ticker = markets[0]["ticker"]
        print(f"\nSample history for {ticker}:")

        for row in history.recent_prices(ticker):
            print(row)


if __name__ == "__main__":
    main()
