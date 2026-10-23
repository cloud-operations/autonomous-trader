# Autonomous multi-sport prediction market system — Paper V1

**Status: prototype, paper-only, no live orders.** It uses Kalshi's public read-only markets API, SQLite, a deterministic risk gate, strategy decisions and a Streamlit dashboard. No Kalshi API keys are needed. This is a functional *skeleton*, not a validated profitable trading strategy.

## Run

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python engine.py
```

In a second terminal (same directory and virtual environment):

```bash
streamlit run dashboard.py
```

Run tests: `pytest -q`.

## Design

- **Discovery:** fetches a bounded set of open Kalshi markets through the public API and filters sports-related titles/tickers. This heuristic can miss sports markets or include false positives. Improve using exchange event/series metadata before deployment.
- **Sports intelligence:** interface is `decision(m, external_probability)`; currently no calibrated sports model or live scores provider is connected.
- **Strategy:** skips all new positions without an independently estimated win probability. With a supplied probability, checks expected edge after illustrative costs. A simplistic +15% profit / -20% loss exit rule demonstrates position monitoring. Settlement handling is **not implemented**.
- **Risk:** $10 max new position, $30 max total cost exposure, $5 daily realized loss threshold, $80 equity floor, $150 target; pause control.
- **Execution:** simulated paper fills at the displayed ask/bid with configurable cost buffers. Quotes are not guaranteed fills and may be stale. **No real trading methods, API credentials or order-writing endpoints are included.**
- **Persistence:** SQLite for markets, cash, positions, decisions and trades. Use PostgreSQL for multi-worker production concurrency.

## Known limitations / before live trading

1. The public market endpoint can change; discovery has not been confirmed against a live endpoint in this package. Pagination only samples the first five pages, so it is not complete across all sports.
2. The current bot **will not autonomously open positions**: no reliable independent probability model has been integrated. This is deliberate to prevent fabricated trading edges.
3. Live sports data, real-time WebSocket streams, liquidity/order-book depth, fill simulation, market closure and settlement reconciliation are not yet integrated.
4. No momentum forecasting, hold-vs-sell expected value comparison, sport-specific models, backtesting or paper-performance validation yet.
5. The paper engine assumes instant fills and simple fixed fees/slippage; actual fees depend on exchange rules and contract specifics.
6. Stop thresholds based on periodic quotes cannot guarantee exits at threshold prices; the daily loss rule uses realized P&L only.
7. A fresh quote requirement applies to exits; new positions should also require freshness checks before any future automated execution.
8. For reliable concurrent deployment, use one engine worker and persistent DB storage; do not run multiple instances against the same SQLite database.
9. A separate, audited live-execution adapter, explicit operator authorization, exchange eligibility checks and extensive testing are required before any real-money mode can be considered.

## Next milestones

- Metadata-based all-sports market discovery and real-time streaming.
- Live sports provider adapter and sport-specific probability models.
- Historical quote replay and out-of-sample backtests.
- Realistic paper matching engine, settlement handling, risk ledger and Telegram alerts.
- Paper-trading acceptance criteria before considering real trading.
