"""専門家の選好(chosen vs rejected)から Action Scorer を学習(ランキング損失)。

価値関数ではなく『その局面でどの合法手が良いか』の方策側の局所評価器(advantage)を学ぶ。
- 『効く決定』に絞る(攻撃/進化/特性/逃げ がある局面・カード選択)。育成順の交換可能な決定は除外。
- デッキ非依存特徴(featurize_generic)で表現＝他デッキへ転移可能。
- chosen の点数 > rejected の点数 + margin の pairwise hinge を最小化。
- ゲーム単位で train/test 分割し、ランキング一致率(chosen>rejected)で検証。
出力: out/action_scorer.json。実行: python tools/train_scorer.py
"""
import sys, os, json
sys.path.insert(0, ".")
import numpy as np
from cabt_bot.imitation import featurize_generic, GENERIC_DIM


def matters(x):
    """選好が意味を持つ『効く決定』か。育成順など交換可能な決定は除外。"""
    opts = x["options"]
    if not x["chosen"]:
        return False
    types = {o["otype"] for o in opts}
    chosen_t = opts[x["chosen"][0]]["otype"] if x["chosen"][0] < len(opts) else None
    if 13 in types:                       # 攻撃という選択肢がある＝攻撃する/しないは重い
        return True
    if chosen_t in (9, 10, 12):           # 進化・特性・逃げ＝コミット
        return True
    if x["stype"] == 1 and len(opts) >= 2:  # どのカードをサーチ/トラッシュするか
        return True
    return False


def build():
    ds = json.load(open("out/archaludon_decisions.json", encoding="utf-8"))
    data = []   # (file, X[n,d], chosen_idx)
    for x in ds:
        if len(x["chosen"]) != 1 or not matters(x):
            continue
        opts = x["options"]
        if len(opts) < 2 or x["chosen"][0] >= len(opts):
            continue
        X = np.array([featurize_generic(x["ctx"], o) for o in opts], dtype=float)
        data.append((x["file"], X, x["chosen"][0]))
    return ds, data


def train(data, iters=400, lr=0.1, l2=1e-4, margin=1.0):
    w = np.zeros(GENERIC_DIM)
    for it in range(iters):
        g = np.zeros(GENERIC_DIM)
        for _, X, c in data:
            s = X @ w
            fc = X[c]
            for r in range(len(X)):
                if r == c:
                    continue
                if margin - (s[c] - s[r]) > 0:      # hinge: マージン未達なら勾配
                    g += -(fc - X[r])
        w -= lr * (g / max(1, len(data)) + l2 * w)
    return w


def rank_acc(data, w):
    """ペア単位の一致率(chosen>rejected) と 決定単位の的中率(argmax==chosen)。"""
    pair_ok = pair_tot = dec_ok = 0
    for _, X, c in data:
        s = X @ w
        for r in range(len(X)):
            if r == c:
                continue
            pair_ok += (s[c] > s[r]); pair_tot += 1
        dec_ok += (int(np.argmax(s)) == c)
    return pair_ok / max(1, pair_tot), dec_ok / max(1, len(data))


def main():
    ds, data = build()
    files = sorted({f for f, _, _ in data})
    rng = np.random.default_rng(0); rng.shuffle(files)
    te_files = set(files[: max(1, len(files) // 5)])
    tr = [d for d in data if d[0] not in te_files]
    te = [d for d in data if d[0] in te_files]
    print(f"効く決定 {len(data)}件 (全{len(ds)}決定中) / 学習{len(tr)} 検証{len(te)} (特徴{GENERIC_DIM}次元, ゲーム分割)")
    w = train(tr)
    pa_tr, da_tr = rank_acc(tr, w)
    pa_te, da_te = rank_acc(te, w)
    print(f"\nペア一致率(chosen>rejected): 学習 {pa_tr:.3f} / 検証 {pa_te:.3f}  (基準0.500)")
    print(f"決定的中率(argmax==chosen):  学習 {da_tr:.3f} / 検証 {da_te:.3f}")
    # 重み解釈
    names = ([f"otype_{t}" for t in (7, 8, 9, 10, 12, 13, 14, 3)]
             + ["is_poke", "is_trainer", "is_energy",
                "maxdmg", "mincost", "evo", "has_ability", "pv", "hp",
                "is_atk", "dmg", "KOs", "KO*pv", "dmg/hp", "tgt_attacker",
                "turn", "myprize", "bench", "have_atk", "behind", "low_hand",
                "atk*behind", "atk*ahead", "KOs2", "evo*noatk", "trainer*lowhand", "atk*noatk"])
    print("\n重み上位(専門家が重視する性質):")
    for n, wi in sorted(zip(names, w), key=lambda t: -abs(t[1]))[:12]:
        print(f"  {n:14s} {wi:+.3f}")
    os.makedirs("out", exist_ok=True)
    json.dump({"type": "linear", "w": list(map(float, w)), "feature_dim": GENERIC_DIM},
              open("out/action_scorer.json", "w", encoding="utf-8"))
    print("\n→ out/action_scorer.json に保存")


if __name__ == "__main__":
    main()
