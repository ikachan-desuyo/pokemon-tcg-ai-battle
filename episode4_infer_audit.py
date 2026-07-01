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


def main():
    print(f"{'デッキ':<12} {'attacker recall':<26} {'energy':<8} {'setup(推/真)':<10} 判定")
    for name, stem, key in DECKS:
        if not os.path.exists(f"decks/{stem}.csv") or key not in R.DECK_BOTS:
            continue
        dl = load(stem)
        inf = infer_plan(dl)
        try:
            truth = R.DECK_BOTS[key](decklist=dl).plan
        except Exception as e:
            print(f"{name:<12} (専用bot生成失敗: {e})"); continue
        t_atk = set(truth.attackers or ())
        i_atk = set(inf.attackers or ())
        if not t_atk:
            print(f"{name:<12} (専用planにattackers無し=比較不可)"); continue
        missing = [nm(i) for i in t_atk - i_atk]          # 真の攻撃役で推論が取りこぼした=致命的
        recall = len(t_atk & i_atk) / len(t_atk)
        # energy: 真のenergy_rulesで使うエネidが推論にも含まれるか
        t_e = {e for e, _ in (truth.energy_rules or ())}
        i_e = {e for e, _ in (inf.energy_rules or ())}
        e_ok = "○" if (t_e & i_e or not t_e) else "×"
        t_setup = truth.setup_energy or 3
        s_ok = "○" if abs((inf.setup_energy or 0) - t_setup) <= 1 else "×"
        verdict = "OK" if (recall == 1.0 and e_ok == "○") else "要修正"
        miss = f" 取零し={missing}" if missing else ""
        print(f"{name:<12} recall {recall:>4.0%}{miss:<20} {e_ok:<8} {inf.setup_energy}/{t_setup:<8} {verdict}")


if __name__ == "__main__":
    main()
