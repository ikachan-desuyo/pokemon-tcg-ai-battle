"""1位ブリジュラス(ShumpeiNomura)の意思決定データから行動クローン方策を学習(MLP)。

各決定(選択肢群+本人が選んだindex)に対し、選択肢をfeaturizeして per-decision softmax を学習
(本人の選択を最も高く採点)。非線形(1隠れ層MLP)で条件の組合せを捉え忠実度を上げる。
保持データで模倣精度を測定。出力: out/archaludon_policy.json。

実行: python tools/train_policy.py [--hidden 48] [--iters 600]
"""
import sys, os, json, argparse
sys.path.insert(0, ".")
import numpy as np
from cabt_bot.imitation import featurize, FEATURE_DIM, policy_scores


def softmax(z):
    z = z - z.max(); e = np.exp(z); return e / (e.sum() + 1e-12)


def load_decisions():
    ds = json.load(open("out/archaludon_decisions.json", encoding="utf-8"))
    samples = []
    for x in ds:
        if len(x["chosen"]) != 1:
            continue
        opts = x["options"]
        if len(opts) < 2 or x["chosen"][0] >= len(opts):
            continue
        X = np.array([featurize(x["ctx"], o) for o in opts], dtype=float)
        samples.append((X, x["chosen"][0], x["stype"]))
    return samples


def train_mlp(samples, H=48, iters=600, lr=0.15, l2=1e-4, seed=0):
    rng = np.random.default_rng(seed)
    d = FEATURE_DIM
    W1 = rng.normal(0, 0.1, (d, H)); b1 = np.zeros(H)
    w2 = rng.normal(0, 0.1, H); b2 = 0.0
    for it in range(iters):
        gW1 = np.zeros_like(W1); gb1 = np.zeros_like(b1); gw2 = np.zeros_like(w2); gb2 = 0.0
        for X, tgt, _ in samples:
            Z1 = X @ W1 + b1; A1 = np.maximum(0.0, Z1)
            s = A1 @ w2 + b2; p = softmax(s)
            ds = p.copy(); ds[tgt] -= 1.0          # ∂L/∂s
            gw2 += A1.T @ ds; gb2 += ds.sum()
            dA1 = np.outer(ds, w2); dZ1 = dA1 * (Z1 > 0)
            gW1 += X.T @ dZ1; gb1 += dZ1.sum(0)
        n = len(samples)
        W1 -= lr * (gW1 / n + l2 * W1); b1 -= lr * gb1 / n
        w2 -= lr * (gw2 / n + l2 * w2); b2 -= lr * gb2 / n
    return {"type": "mlp", "W1": W1.tolist(), "b1": b1.tolist(),
            "w2": w2.tolist(), "b2": float(b2), "feature_dim": d, "hidden": H}


def accuracy(samples, params):
    by = {}; ok = tot = 0
    for X, tgt, st in samples:
        pred = int(np.argmax(policy_scores(X, params)))
        hit = pred == tgt; ok += hit; tot += 1
        dd = by.setdefault(st, [0, 0]); dd[0] += hit; dd[1] += 1
    return ok / tot, by


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hidden", type=int, default=48); ap.add_argument("--iters", type=int, default=600)
    a = ap.parse_args()
    samples = load_decisions()
    rng = np.random.default_rng(0); idx = np.arange(len(samples)); rng.shuffle(idx)
    sp = int(len(samples) * 0.8)
    tr = [samples[i] for i in idx[:sp]]; te = [samples[i] for i in idx[sp:]]
    print(f"学習 {len(tr)} / 検証 {len(te)} (特徴{FEATURE_DIM}次元, MLP隠れ{a.hidden})")
    params = train_mlp(tr, H=a.hidden, iters=a.iters)
    base = float(np.mean([1.0 / len(X) for X, _, _ in te]))
    acc, by = accuracy(te, params); tracc, _ = accuracy(tr, params)
    STN = {0: "MAIN", 1: "CARD", 4: "ENERGY", 8: "COUNT", 9: "YESNO", 6: "SKILL"}
    print(f"\n模倣精度(検証) {acc:.3f}  (学習{tracc:.3f} / ランダム基準 {base:.3f})")
    for st, (o, t) in sorted(by.items()):
        print(f"  {STN.get(st, st):6s}: {o/t:.3f} ({o}/{t})")
    os.makedirs("out", exist_ok=True)
    json.dump(params, open("out/archaludon_policy.json", "w", encoding="utf-8"))
    print("\n→ out/archaludon_policy.json に保存")


if __name__ == "__main__":
    main()
