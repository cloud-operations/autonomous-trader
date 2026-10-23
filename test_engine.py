import engine

def test_skip_without_model():
    m={'ticker':'NFL-EXAMPLE','yes_ask':.35,'yes_bid':.33}
    assert engine.decision(m)[0]=='SKIP'

def test_model_edge():
    m={'ticker':'NFL-EXAMPLE','yes_ask':.35,'yes_bid':.33}
    assert engine.decision(m,.55)[0]=='BUY'

def test_risk_and_trade(tmp_path,monkeypatch):
    monkeypatch.setattr(engine,'DB',str(tmp_path/'test.db'))
    con=engine.connect()
    m={'ticker':'NFL-EXAMPLE','title':'NFL example','category':'Sports','yes_bid':.33,'yes_ask':.35,'status':'active'}
    engine.record_markets(con,[m])
    action,_=engine.buy(con,m,.55)
    assert action=='BUY'
    assert engine.exposure(con)<=10
    assert engine.buy(con,m,.55)[0]=='BLOCKED'
    engine.set_pause(con,True)
    assert engine.paused(con)
    engine.sell(con,m['ticker'])
    assert engine.exposure(con)==0
