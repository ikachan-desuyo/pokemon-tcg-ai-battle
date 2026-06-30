"""学習価値モデル(状態ベクトル→勝率)のプロトタイプ。

ポケカ盤面を固定長ベクトルに『ベクトル化』し、自己対戦で集めた(状態, 最終勝敗)から
価値モデル(状態→勝率)を学習する。AlphaZero型の価値ネットの最小版＝LLMの埋め込み理論を
ポケカに適用した実証。ヒューリスティック基準(サイド差)と精度を比較する。

実行: python tools/value_model.py --games 120
"""
import sys, argparse
sys.path.insert(0, ".")
import numpy as np
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class
from cabt_bot import Observation
from cabt_bot.bots import deck_registry as R

FEATURES = [
    "my_prizes_left", "opp_prizes_left", "prize_diff",
    "my_active_hp_ratio", "opp_active_hp_ratio",
    "my_active_energy", "opp_active_energy",
    "my_bench", "opp_bench", "my_board_energy", "opp_board_energy",
    "my_hand", "opp_hand", "turn", "my_has_active", "opp_has_active",
]


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def _side(p):
    act = (p.get("active") or [None])[0]
    bench = [s for s in (p.get("bench") or []) if s]
    def en(s):
        e = s.get("energyCards") or s.get("energies") or []
        return len(e)
    pr = p.get("prize") or p.get("prizes") or []
    prizes_left = sum(1 for x in pr if x) if pr else 6
    return {
        "prizes": prizes_left,
        "active_hp_ratio": (act.get("hp", 0) / act["maxHp"]) if (act and act.get("maxHp")) else 0.0,
        "active_energy": en(act) if act else 0,
        "bench": len(bench),
        "board_energy": (en(act) if act else 0) + sum(en(s) for s in bench),
        "hand": len(p.get("hand") or []),
        "has_active": 1 if act else 0,
    }


def encode_state(cur, who):
    me = _side(cur["players"][who]); opp = _side(cur["players"][1 - who])
    return [
        me["prizes"], opp["prizes"], opp["prizes"] - me["prizes"],
        me["active_hp_ratio"], opp["active_hp_ratio"],
        me["active_energy"], opp["active_energy"],
        me["bench"], opp["bench"], me["board_energy"], opp["board_energy"],
        me["hand"], opp["hand"], cur.get("turn", 0), me["has_active"], opp["has_active"],
    ]


def collect(games):
    """色々な対面で(状態, そのプレイヤーが勝ったか)を両者視点で収集＝多様＆バランス。"""
    field = [o for o in R.DECK_BOTS if o not in ("gardevoir",)]
    X, y = [], []
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
                        snaps.append((who, encode_state(cur, who))); lastturn[who] = t
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


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--games", type=int, default=120); a = ap.parse_args()
    print(f"自己対戦で状態を収集中... ({a.games}試合)")
    X, y = collect(a.games)
    n = len(y); split = int(n * 0.8)
    idx = np.arange(n); rng = np.random.default_rng(0); rng.shuffle(idx)
    tr, te = idx[:split], idx[split:]
    w, b, mu, sd = train_logreg(X[tr], y[tr])
    Xte = (X[te] - mu) / sd; pte = 1 / (1 + np.exp(-(Xte @ w + b)))
    acc = ((pte > 0.5) == y[te]).mean()
    # AUC
    order = np.argsort(pte); ranks = np.empty(len(pte)); ranks[order] = np.arange(1, len(pte) + 1)
    pos, neg = y[te].sum(), (1 - y[te]).sum()
    auc = (ranks[y[te] == 1].sum() - pos * (pos + 1) / 2) / (pos * neg) if pos and neg else float("nan")
    # 基準: サイド差(prize_diff)符号だけで予測
    base_pred = (X[te][:, 2] >= 0).astype(float)  # opp_prizes>=my_prizes → 自分有利
    base_acc = (base_pred == y[te]).mean()
    print(f"\n学習サンプル {n}状態 (勝ち{int(y.sum())}/負け{int(n-y.sum())})")
    print(f"価値モデル: テスト精度 {acc:.3f} / AUC {auc:.3f}")
    print(f"基準(サイド差符号のみ): 精度 {base_acc:.3f}")
    print("\n特徴量の重み(勝率への寄与, 標準化済):")
    for f, wi in sorted(zip(FEATURES, w), key=lambda t: -abs(t[1])):
        print(f"  {f:18s} {wi:+.3f}")


if __name__ == "__main__":
    main()
