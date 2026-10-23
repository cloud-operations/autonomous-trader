"""Paper-only sports prediction market agent. No live order endpoint exists here."""
from __future__ import annotations
import json, os, sqlite3, time, logging, math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import requests

DB = os.getenv('DB_PATH', 'paper_trader.db')
API = os.getenv('KALSHI_API_BASE', 'https://api.elections.kalshi.com/trade-api/v2')
SPORTS = ('NFL','NBA','NHL','MLB','NCAA','SOCCER','TENNIS','GOLF','UFC','MMA','CRICKET','WNBA','MLS','F1')
START_CASH = float(os.getenv('START_CASH', '100'))
MAX_POSITION = float(os.getenv('MAX_POSITION', '10'))
MAX_EXPOSURE = float(os.getenv('MAX_EXPOSURE', '30'))
DAILY_LOSS = float(os.getenv('DAILY_LOSS', '5'))
EQUITY_FLOOR = float(os.getenv('EQUITY_FLOOR', '80'))
TARGET = float(os.getenv('TRADER_TARGET', '150'))
FEE_PER_CONTRACT = float(os.getenv('PAPER_FEE_PER_CONTRACT', '0.02'))
SPREAD_BUFFER = float(os.getenv('PAPER_SLIPPAGE_PER_CONTRACT', '0.01'))
MIN_EDGE = float(os.getenv('MIN_EDGE', '0.05'))
POLL_SECONDS = int(os.getenv('POLL_SECONDS', '120'))
LOG = logging.getLogger('paper-agent')


def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.executescript('''
    CREATE TABLE IF NOT EXISTS cash (id INTEGER PRIMARY KEY CHECK(id=1), amount REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS markets (ticker TEXT PRIMARY KEY, title TEXT, category TEXT, yes_bid REAL, yes_ask REAL, updated_at TEXT, status TEXT);
    CREATE TABLE IF NOT EXISTS positions (ticker TEXT PRIMARY KEY, qty INTEGER NOT NULL, cost REAL NOT NULL, opened_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, ticker TEXT, side TEXT, qty INTEGER, price REAL, fees REAL, realized_pnl REAL, reason TEXT);
    CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, ticker TEXT, action TEXT, reason TEXT, confidence REAL);
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')
    con.execute('INSERT OR IGNORE INTO cash(id,amount) VALUES(1,?)', (START_CASH,))
    con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('paused','0')")
    con.commit()
    return con


def now(): return datetime.now(timezone.utc).isoformat()

def to_dollars(v):
    if v is None or v == '': return None
    try: return float(v)
    except (TypeError, ValueError): return None


def normalize(m):
    """Use executable bid/ask, not last trade or mid, for paper fills."""
    title = str(m.get('title') or '')
    ticker = str(m.get('ticker') or '')
    event = str(m.get('event_ticker') or '')
    cat = ' '.join((title,ticker,event,str(m.get('category') or ''))).upper()
    if not any(s in cat for s in SPORTS): return None
    bid = to_dollars(m.get('yes_bid_dollars'))
    ask = to_dollars(m.get('yes_ask_dollars'))
    if bid is None:
        p = to_dollars(m.get('yes_bid'))
        bid = p/100 if p is not None else None
    if ask is None:
        p = to_dollars(m.get('yes_ask'))
        ask = p/100 if p is not None else None
    if bid is None or ask is None or not (0 < bid <= ask < 1): return None
    return dict(ticker=ticker,title=title,category=str(m.get('category') or 'Sports'),yes_bid=bid,yes_ask=ask,status=str(m.get('status') or 'active'))


def discover(session=None, pages=5):
    """Public read-only API. Market classification is conservative and incomplete."""
    session = session or requests.Session()
    cursor = None; out = []
    for _ in range(pages):
        params = {'limit': 200, 'status': 'open'}
        if cursor: params['cursor'] = cursor
        r = session.get(API+'/markets',params=params,timeout=15)
        r.raise_for_status()
        data = r.json()
        for raw in data.get('markets',[]):
            m = normalize(raw)
            if m: out.append(m)
        cursor = data.get('cursor')
        if not cursor: break
    return out


def record_markets(con, markets):
    for m in markets:
        con.execute('INSERT INTO markets VALUES(?,?,?,?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET title=excluded.title, category=excluded.category,yes_bid=excluded.yes_bid,yes_ask=excluded.yes_ask,updated_at=excluded.updated_at,status=excluded.status',
                    (m['ticker'],m['title'],m['category'],m['yes_bid'],m['yes_ask'],now(),m['status']))
    con.commit()


def equity(con):
    cash = con.execute('SELECT amount FROM cash WHERE id=1').fetchone()[0]
    positions = con.execute('SELECT p.qty,m.yes_bid FROM positions p LEFT JOIN markets m USING(ticker)').fetchall()
    # Missing quotes valued at zero for conservative risk accounting.
    value = sum(p['qty'] * (p['yes_bid'] or 0) for p in positions)
    return cash+value


def exposure(con):
    return con.execute('SELECT COALESCE(SUM(cost),0) FROM positions').fetchone()[0]


def daily_pnl(con):
    date = datetime.now(timezone.utc).date().isoformat()
    return con.execute("SELECT COALESCE(SUM(realized_pnl),0) FROM trades WHERE timestamp LIKE ?",(date+'%',)).fetchone()[0]


def paused(con):
    return con.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0] == '1'


def set_pause(con, pause=True):
    con.execute("UPDATE settings SET value=? WHERE key='paused'", ('1' if pause else '0',)); con.commit()


def risk_check(con, ticker, qty, ask):
    if paused(con): return 'Paused by operator'
    if equity(con) >= TARGET: return 'Target reached'
    if equity(con) <= EQUITY_FLOOR: return 'Equity floor reached'
    if daily_pnl(con) <= -DAILY_LOSS: return 'Daily realized loss limit'
    if con.execute('SELECT 1 FROM positions WHERE ticker=?',(ticker,)).fetchone(): return 'Already holding'
    if qty <= 0 or not 0 < ask < 1: return 'Invalid order'
    cost = qty*(ask+FEE_PER_CONTRACT+SPREAD_BUFFER)
    if cost > MAX_POSITION+1e-8: return 'Per-position limit'
    if exposure(con)+cost > MAX_EXPOSURE+1e-8: return 'Exposure limit'
    if con.execute('SELECT amount FROM cash').fetchone()[0] < cost: return 'Insufficient cash'
    return None


def decision(m, external_probability=None):
    """No invented probability edge: absent independent model, do not buy."""
    if external_probability is None:
        return ('SKIP','No calibrated independent probability model; market price alone is not an edge',0.0)
    p = float(external_probability)
    if not 0 <= p <= 1: return ('SKIP','Invalid probability',0.0)
    edge = p - m['yes_ask'] - FEE_PER_CONTRACT - SPREAD_BUFFER
    if edge >= MIN_EDGE: return ('BUY',f'Independent probability {p:.3f}; net estimated edge {edge:.3f}',p)
    return ('SKIP',f'Net estimated edge {edge:.3f} below threshold',p)


def buy(con,m,probability=None):
    action,reason,conf = decision(m,probability)
    con.execute('INSERT INTO decisions(timestamp,ticker,action,reason,confidence) VALUES(?,?,?,?,?)',(now(),m['ticker'],action,reason,conf))
    if action != 'BUY': con.commit(); return action,reason
    unit = m['yes_ask']+FEE_PER_CONTRACT+SPREAD_BUFFER
    qty = math.floor(MAX_POSITION/unit)
    error = risk_check(con,m['ticker'],qty,m['yes_ask'])
    if error: con.commit(); return 'BLOCKED',error
    total = qty*unit
    with con:
        con.execute('UPDATE cash SET amount=amount-? WHERE id=1',(total,))
        con.execute('INSERT INTO positions VALUES(?,?,?,?)',(m['ticker'],qty,total,now()))
        con.execute('INSERT INTO trades(timestamp,ticker,side,qty,price,fees,realized_pnl,reason) VALUES(?,?,?,?,?,?,?,?)',
                    (now(),m['ticker'],'BUY',qty,m['yes_ask']+SPREAD_BUFFER,qty*FEE_PER_CONTRACT,0,reason))
    return 'BUY',f'Paper bought {qty} contracts for ${total:.2f}'


def sell(con,ticker,reason='Momentum exit'):
    pos = con.execute('SELECT * FROM positions WHERE ticker=?',(ticker,)).fetchone()
    m = con.execute('SELECT * FROM markets WHERE ticker=?',(ticker,)).fetchone()
    if not pos or not m or not m['yes_bid'] or m['yes_bid'] <= 0: return 'BLOCKED','No position or executable bid'
    qty = pos['qty']; proceeds = qty*max(0,m['yes_bid']-SPREAD_BUFFER-FEE_PER_CONTRACT)
    pnl = proceeds-pos['cost']
    with con:
        con.execute('UPDATE cash SET amount=amount+? WHERE id=1',(proceeds,))
        con.execute('DELETE FROM positions WHERE ticker=?',(ticker,))
        con.execute('INSERT INTO trades(timestamp,ticker,side,qty,price,fees,realized_pnl,reason) VALUES(?,?,?,?,?,?,?,?)',
                    (now(),ticker,'SELL',qty,max(0,m['yes_bid']-SPREAD_BUFFER),qty*FEE_PER_CONTRACT,pnl,reason))
    return 'SELL',f'Paper sold {qty}; realized P&L ${pnl:.2f}'


def manage_positions(con):
    """Simple demonstrator: take profit at +15%, cut at -20% of invested capital.
    Missing/stale quotes do not trigger a fictitious fill.
    """
    for p in con.execute('SELECT * FROM positions').fetchall():
        m = con.execute('SELECT * FROM markets WHERE ticker=?',(p['ticker'],)).fetchone()
        if not m: continue
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(m['updated_at'])).total_seconds()
        if age > max(POLL_SECONDS*2,300): continue
        estimated = p['qty']*max(0,m['yes_bid']-SPREAD_BUFFER-FEE_PER_CONTRACT)
        pnl_pct = estimated/p['cost']-1
        if pnl_pct >= .15: sell(con,p['ticker'],'Profit-taking threshold')
        elif pnl_pct <= -.20: sell(con,p['ticker'],'Stop-loss threshold')


def run_once(con):
    markets = discover()
    record_markets(con,markets)
    manage_positions(con)
    # Intentionally no auto-buys without an independently validated model.
    for m in markets[:100]: buy(con,m,None)
    return len(markets)


def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    con = connect()
    LOG.info('PAPER ONLY: live execution is not implemented')
    while True:
        try: LOG.info('Discovered %s sports markets',run_once(con))
        except Exception: LOG.exception('Scan failed; no orders placed')
        time.sleep(POLL_SECONDS)

if __name__ == '__main__': main()
