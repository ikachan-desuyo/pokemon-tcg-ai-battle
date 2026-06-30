"""学習価値モデル(状態ベクトル→勝率)のプロトタイプ。

ポケカ盤面を固定長ベクトルに『ベクトル化』し、自己対戦で集めた(状態, 最終勝敗)から
価値モデル(状態→勝率)を学習する。AlphaZero型の価値ネットの最小版＝LLMの埋め込み理論を
ポケカに適用した実証。ヒューリスティック基準(サイド差)と精度を比較する。

実行: python tools/value_model.py --games 120
"""
import sys, argparse, json
sys.path.insert(0, ".")
import numpy as np
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class
from cabt_bot import Observation
from cabt_bot.bots import deck_registry as R
from cabt_bot.state_encoder import encode_state, FEATURES, encode_state_v2, FEATURES_V2_DIM


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def collect(games, general=False, encoder=encode_state):
    """色々な対面で(状態, そのプレイヤーが勝ったか)を両者視点で収集＝多様＆バランス。
    general=True: 全デッキをP0に据えた多デッキ均衡データ(汎用な価値関数のため)。"""
    field = [o for o in R.DECK_BOTS if o not in ("gardevoir",)]
    X, y = [], []
    if general:
        pairs = [(a, b) for a in field for b in field if a != b]
    else:
        pairs = [("deck", o) for o in field if o != "deck"] + [("deck", "deck")]
    gi = 0
    while gi < games:
        for me_s, opp_s in pairs:
            if gi >= games:
                break
            gi += 1
            da, db = load(me_s), load(opp_s)
            a = R.DECK_BOTS[me_s](decklist=da); b = R.DECK_BOTS[opp_s](decklist=db)
            obs, sd = battle_start(da, db); steps = 0; res = None
            snaps = []  # (who, features) at each player's turn-start
            lastturn = {0: -1, 1: -1}
            while obs is not None and steps < 1500:
                o = to_observation_class(obs); st = o.current; cur = obs.get("current")
                if st and st.result != -1:
                    res = (st.yourIndex, st.result); break
                if cur is not None:
                    who = cur.get("yourIndex")
                    t = cur.get("turn")
                    if who in (0, 1) and t != lastturn[who]:
                        snaps.append((who, encoder(cur, who))); lastturn[who] = t
                if not (obs.get("select") and obs["select"].get("option")):
                    break
                who = st.yourIndex if st else 0; p = Observation.from_dict(obs)
                ret = (a if who == 0 else b).select(p)
                obs = battle_select(ret or [0]); steps += 1
            battle_finish()
            if res is None:
                continue
            # result は st.result(その視点の勝敗) を yourIndex 視点で。0=その視点の勝ち。
            # 各スナップは who 視点 → who が勝ったか?
            winner = None
            # st.result: 0=yourIndex勝ち,1=負け。yourIndex=res[0]
            ywin = (res[1] == 0)
            winner = res[0] if ywin else (1 - res[0])
            for who, feat in snaps:
                X.append(feat); y.append(1 if who == winner else 0)
    return np.array(X, dtype=float), np.array(y, dtype=float)


def train_logreg(X, y, iters=4000, lr=0.3):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Xs = (X - mu) / sd
    n, d = Xs.shape
    w = np.zeros(d); b = 0.0
    for _ in range(iters):
        z = Xs @ w + b; p = 1 / (1 + np.exp(-z))
        g = p - y
        w -= lr * (Xs.T @ g / n + 1e-3 * w); b -= lr * g.mean()
    return w, b, mu, sd


def train_mlp(X, y, H=64, iters=3000, lr=0.2, l2=1e-4, seed=0):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Xs = (X - mu) / sd
    n, d = Xs.shape
    rng = np.random.default_rng(seed)
    W1 = rng.normal(0, 0.1, (d, H)); b1 = np.zeros(H)
    w2 = rng.normal(0, 0.1, H); b2 = 0.0
    for _ in range(iters):
        Z1 = Xs @ W1 + b1; A1 = np.maximum(0.0, Z1)
        z = A1 @ w2 + b2; p = 1 / (1 + np.exp(-z))
        dz = (p - y) / n
        gw2 = A1.T @ dz; gb2 = dz.sum()
        dA1 = np.outer(dz, w2); dZ1 = dA1 * (Z1 > 0)
        gW1 = Xs.T @ dZ1; gb1 = dZ1.sum(0)
        W1 -= lr * (gW1 + l2 * W1); b1 -= lr * gb1
        w2 -= lr * (gw2 + l2 * w2); b2 -= lr * gb2
    return {"type": "mlp", "W1": W1.tolist(), "b1": b1.tolist(), "w2": w2.tolist(),
            "b2": float(b2), "mu": mu.tolist(), "sd": sd.tolist()}


def mlp_predict(m, X):
    W1 = np.array(m["W1"]); b1 = np.array(m["b1"]); w2 = np.array(m["w2"]); b2 = m["b2"]
    mu = np.array(m["mu"]); sd = np.array(m["sd"])
    Xs = (X - mu) / sd
    A1 = np.maximum(0.0, Xs @ W1 + b1)
    return 1 / (1 + np.exp(-(A1 @ w2 + b2)))


def auc_score(y, p):
    order = np.argsort(p); ranks = np.empty(len(p)); ranks[order] = np.arange(1, len(p) + 1)
    pos, neg = y.sum(), (1 - y).sum()
    return (ranks[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg) if pos and neg else float("nan")


def save_model(path, w, b, mu, sd):
    import json
    json.dump({"features": FEATURES, "w": list(map(float, w)), "b": float(b),
               "mu": list(map(float, mu)), "sd": list(map(float, sd))},
              open(path, "w", encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--games", type=int, default=120)
    ap.add_argument("--save", default="out/value_model.json")
    ap.add_argument("--general", action="store_true", help="全デッキをP0にした汎用データ")
    ap.add_argument("--v2", action="store_true", help="全盤面DeepSets風エンコーダ(encode_state_v2)")
    ap.add_argument("--mlp", action="store_true", help="非線形MLPで学習")
    ap.add_argument("--hidden", type=int, default=64)
    a = ap.parse_args()
    enc = encode_state_v2 if a.v2 else encode_state
    print(f"自己対戦で状態を収集中... ({a.games}試合, general={a.general}, v2={a.v2}, mlp={a.mlp})")
    X, y = collect(a.games, a.general, encoder=enc)
    n = len(y); split = int(n * 0.8)
    idx = np.arange(n); rng = np.random.default_rng(0); rng.shuffle(idx)
    tr, te = idx[:split], idx[split:]
    import os
    base_pred = (X[te][:, 2] <= X[te][:, 1] if a.v2 else X[te][:, 2] >= 0).astype(float)
    base_acc = (base_pred == y[te]).mean() if not a.v2 else float("nan")
    print(f"\n学習サンプル {n}状態 (勝ち{int(y.sum())}/負け{int(n-y.sum())}) 特徴{X.shape[1]}次元")
    if a.mlp:
        m = train_mlp(X[tr], y[tr], H=a.hidden)
        pte = mlp_predict(m, X[te])
        acc = ((pte > 0.5) == y[te]).mean(); auc = auc_score(y[te], pte)
        print(f"価値モデル(MLP h={a.hidden}): テスト精度 {acc:.3f} / AUC {auc:.3f}")
        m_full = train_mlp(X, y, H=a.hidden)
        os.makedirs(os.path.dirname(a.save), exist_ok=True)
        json.dump(m_full, open(a.save, "w", encoding="utf-8"))
    else:
        w, b, mu, sd = train_logreg(X[tr], y[tr])
        Xte = (X[te] - mu) / sd; pte = 1 / (1 + np.exp(-(Xte @ w + b)))
        acc = ((pte > 0.5) == y[te]).mean(); auc = auc_score(y[te], pte)
        print(f"価値モデル(線形): テスト精度 {acc:.3f} / AUC {auc:.3f}")
        if not a.v2:
            for f, wi in sorted(zip(FEATURES, w), key=lambda t: -abs(t[1]))[:8]:
                print(f"  {f:18s} {wi:+.3f}")
        w, b, mu, sd = train_logreg(X, y)
        os.makedirs(os.path.dirname(a.save), exist_ok=True)
        save_model(a.save, w, b, mu, sd)
    print(f"基準(サイド差): 精度 {base_acc}")
    print(f"\n→ モデルを {a.save} に保存(全{n}状態)")


if __name__ == "__main__":
    main()
