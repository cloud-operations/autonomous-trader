
from trader.agents.discovery import MarketDiscoveryAgent
from trader.agents.orchestrator import TradingOrchestrator


def sample_market():
    return {
        "ticker": "TEST-NFL",
        "sport": "NFL",
        "title": "Example NFL game",
        "status": "active",
        "yes_bid": 0.40,
        "yes_ask": 0.45,
    }


def test_discovery_finds_valid_market():
    agent = MarketDiscoveryAgent()
    result = agent.discover([sample_market()])

    assert len(result) == 1
    assert result[0].ticker == "TEST-NFL"


def test_discovery_rejects_invalid_spread():
    market = sample_market()
    market["yes_bid"] = 0.60

    agent = MarketDiscoveryAgent()
    assert agent.discover([market]) == []


def test_orchestrator_skips_without_probability_model():
    orchestrator = TradingOrchestrator()
    decisions = orchestrator.run([sample_market()])

    assert len(decisions) == 1
    assert decisions[0].action == "SKIP"

