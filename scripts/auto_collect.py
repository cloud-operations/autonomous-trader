import argparse
import logging
import signal
import time
from datetime import datetime, timezone

from trader.providers.sports_markets import SportsMarketProvider
from trader.database.price_history import PriceHistory


running = True


def stop_handler(signum, frame):
    global running
    running = False
    logging.info("Shutdown requested.")


def collect(provider, history):
    markets = provider.discover()
    saved = history.save_markets(markets)
    total, contracts, first, last = history.summary()

    logging.info(
        "Discovered=%s Saved=%s Total=%s Unique=%s",
        len(markets),
        saved,
        total,
        contracts,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Collection interval in seconds (default: 300)",
    )
    args = parser.parse_args()

    if args.interval < 60:
        parser.error("Minimum interval is 60 seconds")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("logs/collector.log"),
        ],
    )

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    provider = SportsMarketProvider()
    history = PriceHistory()

    logging.info(
        "Starting price collector. Interval=%s seconds",
        args.interval,
    )

    while running:
        started = time.monotonic()

        try:
            collect(provider, history)
        except Exception:
            logging.exception("Collection failed")

        elapsed = time.monotonic() - started
        remaining = max(0, args.interval - elapsed)

        while running and remaining > 0:
            sleep_for = min(1, remaining)
            time.sleep(sleep_for)
            remaining -= sleep_for

    logging.info("Collector stopped.")


if __name__ == "__main__":
    main()
