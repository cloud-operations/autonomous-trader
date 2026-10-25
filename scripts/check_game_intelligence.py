"""Read-only game lookup for large historical price movements."""
from trader.agents.momentum_v31 import MomentumAgentV31
from trader.agents.game_intelligence import GameIntelligenceAgent


def main():
    signals = MomentumAgentV31().analyze(historical=True, min_change_cents=10)
    print("\n=== GAME INTELLIGENCE V1 ===")
    print("Momentum signals:", len(signals))
    agent = GameIntelligenceAgent()
    # Only one lookup per game, not one per contract movement.
    games = {}
    for signal in signals:
        key = (signal["sport"], signal["event"], signal["detected_at"][:10])
        if key not in games:
            games[key] = signal
    print("Distinct game/date lookups:", len(games))
    for signal in games.values():
        print(f"\n{signal['sport']} | {signal['event']}")
        print("Signal observed at:", signal["detected_at"])
        result = agent.analyze_signal(signal)
        if not result["matched"]:
            print("Lookup unavailable:", result["error"])
            continue
        print("Game:", result["game_id"], "|", result["game_date"])
        print("Status:", result["status"], "| Period:", result["period"], "| Clock:", result["clock"])
        for team in result["teams"]:
            print(" ", team["team"], "—", team["score"])
        print("WARNING:", result["warning"])


if __name__ == "__main__":
    main()
