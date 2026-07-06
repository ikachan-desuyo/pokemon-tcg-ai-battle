"""Episode 4: infer_plan(UniversalBotの心臓)の推論精度を監査する。

専用botの手書きDeckPlan(検証済=ground truth)と infer_plan の出力を全デッキで比較。
attackers を間違えると全部崩れるので、まず attackers の recall/spurious を見る。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cabt_bot import load_cards
from cabt_bot.bots import deck_registry as R
from cabt_bot.bots.universal_bot import infer_plan

C = load_cards()
nm = lambda i: (C[i].name if i in C else f"#{i}")


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


# (表示名, csv stem, 専用botキー)
DECKS = [
    ("MegaStarmie", "deck", "deck"),
    ("MegaSpread", "mega_spread", "mega_spread"),
    ("Lightning", "lightning", "lightning"),
    ("Archaludon", "archaludon_real", "archaludon"),
    ("Dragapult", "dragapult", "dragapult"),
    ("Lopunny", "lopunny", "lopunny"),
    ("Lucario", "megaruka", "megaruka"),
    ("Iwapa", "iwapa", "iwapa"),
    ("Yukinooh", "sample_deck", "sample_deck"),
    ("Gardevoir", "gardevoir", "gardevoir"),
    ("Alakazam", "alakazam", "alakazam"),
    ("Froslass", "froslass", "froslass"),
    ("Scrafty", "scrafty", "scrafty"),
]


def infer_score(inf, truth):
    """Infer Score(主要KPI): attackers40 / energy25 / setup20 / play_priority15 = 100点。"""
    t_atk = set(truth.attackers or ())
    i_atk = set(inf.attackers or ())
    # attackers 40: 真の攻撃役の recall
    s_atk = 40 * (len(t_atk & i_atk) / len(t_atk)) if t_atk else 40
    # energy 25: 真の energy_rules で使うエネidを推論もカバーするか。
    #   真が None(任意エネ)の枠は「推論が何かエネを割当てていれば可」とする(不当減点回避)。
    t_pairs = truth.energy_rules or ()
    i_e = {e for e, _ in (inf.energy_rules or ())}
    t_specific = {e for e, _ in t_pairs if e is not None}
    t_flex = any(e is None for e, _ in t_pairs)
    if not t_pairs:
        s_e = 25
    else:
        hit = len(t_specific & i_e) + (1 if (t_flex and i_e) else 0)
        need = len(t_specific) + (1 if t_flex else 0)
        s_e = 25 * (hit / need) if need else 25
    # setup 20: 一致=20, ±1=10, それ以外=0
    d = abs((inf.setup_energy or 0) - (truth.setup_energy or 3))
    s_s = 20 if d == 0 else (10 if d == 1 else 0)
    # play_priority 15: 真の攻撃役が推論の play_priority に載っているか
    pp = set((inf.play_priority or {}).keys())
    s_p = 15 * (len(t_atk & pp) / len(t_atk)) if t_atk else 15
    return round(s_atk + s_e + s_s + s_p), (round(s_atk), round(s_e), s_s, round(s_p))


def main():
    print(f"{'デッキ':<12} {'Score':>6}  {'atk':>4} {'ene':>4} {'setup':>5} {'pp':>4}   setup(推/真)")
    tot = 0; n = 0; dim = [0.0, 0.0, 0.0, 0.0]; cap = [40, 25, 20, 15]
    for name, stem, key in DECKS:
        if not os.path.exists(f"decks/{stem}.csv") or key not in R.DECK_BOTS:
            continue
        dl = load(stem)
        inf = infer_plan(dl)
        try:
            truth = R.DECK_BOTS[key](decklist=dl).plan
        except Exception as e:
            print(f"{name:<12} (専用bot生成失敗: {e})"); continue
        if not (truth.attackers or ()):
            print(f"{name:<12} (専用planにattackers無し=比較不可)"); continue
        score, (a, e, s, p) = infer_score(inf, truth)
        tot += score; n += 1
        for k, v in enumerate((a, e, s, p)):
            dim[k] += v
        print(f"{name:<12} {score:>4}/100  {a:>4} {e:>4} {s:>5} {p:>4}   {inf.setup_energy}/{truth.setup_energy or 3}")
    if n:
        print(f"\n=== 平均 Infer Score: {tot/n:.1f}/100 ({n}デッキ) ===")
        print("=== 次元別(達成率) ===")
        labels = ["Attackers", "Energy", "Setup", "Play"]
        for k in range(4):
            print(f"  {labels[k]:<10} {dim[k]/n:>5.1f}/{cap[k]}  = {100*dim[k]/(n*cap[k]):>3.0f}%")


if __name__ == "__main__":
    main()
