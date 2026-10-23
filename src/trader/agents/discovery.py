
from dataclasses import dataclass


@dataclass(frozen=True)
class MarketCandidate:
    ticker: str
    sport: str
    title: str
    yes_bid: float
    yes_ask: float


class MarketDiscoveryAgent:
    def discover(self, markets: list[dict]) -> list[MarketCandidate]:
        candidates = []

        for market in markets:
            if market.get("status") != "active":
                continue

            ticker = market.get("ticker")
            sport = market.get("sport")
            title = market.get("title")
            bid = market.get("yes_bid")
            ask = market.get("yes_ask")

            if not ticker or not sport or not title:
                continue

            if not isinstance(bid, (int, float)):
                continue
            if not isinstance(ask, (int, float)):
                continue

            if not (0 <= bid <= ask <= 1):
                continue

            candidates.append(
                MarketCandidate(
                    ticker=ticker,
                    sport=sport,
                    title=title,
                    yes_bid=float(bid),
                    yes_ask=float(ask),
                )
            )

        return candidates

