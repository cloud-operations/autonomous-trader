"""Experimental NHL score/time model, trained only on historical games.
No Kalshi inputs. No trading. Standard-library only.
"""
import math

def sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, x))))

def features(home_score, away_score, seconds_left):
    # No future information: scores and remaining time are as of the snapshot.
    t = max(0.0, min(3600.0, float(seconds_left))) / 3600.0
    diff = max(-8, min(8, int(home_score) - int(away_score)))
    return [1.0, diff, diff * (1.0 - t), diff * (1.0 - t)**2, 1.0 - t]

def predict(weights, row):
    return sigmoid(sum(w*x for w,x in zip(weights, row)))

def train(games, epochs=1500, rate=0.15, ridge=0.02):
    """Equal game weight, even if a game has multiple checkpoints."""
    w = [0.0]*5
    for _ in range(epochs):
        grad = [0.0]*5
        for game in games:
            scale = 1.0/len(game['rows'])
            for row in game['rows']:
                err = predict(w, row['x']) - game['home_won']
                for j,x in enumerate(row['x']):
                    grad[j] += err*x*scale
        n = max(1,len(games))
        for j in range(5):
            grad[j] = grad[j]/n + (ridge*w[j] if j else 0)
            w[j] -= rate*grad[j]
    return w

def evaluate(games, predict_fn):
    if not games: return None
    briers, losses = [], []
    bins = {i: [0,0.0,0.0] for i in range(10)}
    for game in games:
        bs, ls = [], []
        for row in game['rows']:
            p = min(1-1e-6,max(1e-6,predict_fn(row)))
            y = game['home_won']
            bs.append((p-y)**2)
            ls.append(-y*math.log(p)-(1-y)*math.log(1-p))
            bucket = min(9,int(p*10))
            bins[bucket][0] += 1
            bins[bucket][1] += p
            bins[bucket][2] += y
        briers.append(sum(bs)/len(bs))
        losses.append(sum(ls)/len(ls))
    return {'games':len(games), 'snapshots':sum(len(g['rows']) for g in games),
            'brier':sum(briers)/len(briers),'logloss':sum(losses)/len(losses), 'bins':bins}
