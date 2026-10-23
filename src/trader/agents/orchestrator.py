
from dataclasses import dataclass

from trader.agents.discovery import MarketDiscoveryAgent


@dataclass
class AgentDecision:
    ticker: str
    action: str
    reason: str


class TradingOrchestrator:
    def __init__(self):
        self.discovery = MarketDiscoveryAgent()

    def run(self, markets: list[dict]) -> list[AgentDecision]:
        candidates = self.discovery.discover(markets)
        decisions = []

        for market in candidates:
            decisions.append(
                AgentDecision(
                    ticker=market.ticker,
                    action="SKIP",
                    reason="Independent probability model not connected",
                )
            )

        return decisions

