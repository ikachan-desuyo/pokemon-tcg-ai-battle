"""Episode 4: Attach先53%不一致の『なぜ』をExplainで切り分ける（修正前の原因確認）。

同一局面で 専用=ATTACH→X / Universal=ATTACH→Y (X≠Y) となった各ケースについて:
  - Universalの付け先(主にactive)は既にエネ飽和(=最大技コスト充足)だったか → 過積み(エンジンに飽和チェック無し)
  - 専用の付け先はどのポケモンで、専用planのenergy_rules最上位(主役)か → エネ優先度の違い(plan差)
  - その他(手札/ボール温存/volatile等)
を分類し「本当にUniversalの改善ポイントか」をデータで確定する。
"""
import sys, os
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class
from cabt_bot import Observation, load_cards
from cabt_bot.bots import deck_registry as R
from cabt_bot.bots.universal_bot import UniversalBot, interpret_move
from cabt_bot.enums import SelectType, OptionType

C = load_cards(); nm = lambda i: (C[i].name if i in C else f"#{i}")
MAIN = int(SelectType.MAIN); ATTACH = int(OptionType.ATTACH)


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def costs(cid):
    """そのポケモンの技コスト(最小/最大)。攻撃を持たなければ(None,None)。"""
    ci = C.get(cid)
    if not ci:
        return None, None
    atks = [im for im in (interpret_move(mv) for mv in ci.moves) if im["is_attack"]]
    if not atks:
        return None, None
    lens = [len(a["cost_syms"]) for a in atks]
    return min(lens), max(lens)


def target_spot(ch, me):
    if ch.get("inPlayArea") == 4:
        a = me.get("active") or [None]; return a[0], "act"
    if ch.get("inPlayArea") == 5:
        b = me.get("bench") or []; i = ch.get("inPlayIndex", 0)
        return (b[i] if i < len(b) else None), f"bench{ch.get('inPlayIndex', 0)}"
    return None, "?"


def main(deck, spec_key, games=10):
    dl = load(deck)
    spec_plan = R.DECK_BOTS[spec_key](decklist=dl).plan
    spec_rule1 = spec_plan.energy_rules[0][1] if spec_plan.energy_rules else None   # 専用のエネ最優先先
    cats = Counter(); ex = []
    for g in range(games):
        uni = UniversalBot(decklist=dl)
        shadow = R.DECK_BOTS[spec_key](decklist=dl)
        opp = R.DECK_BOTS[spec_key](decklist=dl)
        obs, _ = battle_start(dl, dl); steps = 0
        while obs is not None and steps < 400:
            st = to_observation_class(obs).current
            if st and st.result != -1:
                break
            if not (obs.get("select") and obs["select"].get("option")):
                break
            who = st.yourIndex if st else 0; sel = obs["select"]
            if who == 0:
                if sel.get("type") == MAIN and len(sel["option"]) >= 2:
                    me = obs["current"]["players"][0]
                    u = uni.select(Observation.from_dict(obs)) or [0]
                    s = shadow.select(Observation.from_dict(obs)) or [0]
                    uo = sel["option"][u[0]] if u[0] < len(sel["option"]) else {}
                    so = sel["option"][s[0]] if s[0] < len(sel["option"]) else {}
                    if uo.get("type") == ATTACH and so.get("type") == ATTACH:
                        ut, uw = target_spot(uo, me); st_, sw = target_spot(so, me)
                        if ut and st_ and (uw != sw or ut.get("id") != st_.get("id")):
                            uid, sid = ut.get("id"), st_.get("id")
                            ue = len(ut.get("energyCards") or []); se = len(st_.get("energyCards") or [])
                            umin, umax = costs(uid)
                            # 分類
                            if umax is not None and ue >= umax:
                                cat = "A:Uni付け先は飽和(過積み)"
                            elif sid == spec_rule1 and uid != spec_rule1:
                                cat = "B:専用はplan主役(エネ優先先)を充電"
                            elif umin is not None and ue < umin:
                                cat = "C:Uni付け先はまだ技コスト未達(積み途中)"
                            else:
                                cat = "D:その他"
                            cats[cat] += 1
                            if len(ex) < 6:
                                ex.append(f"T{st.turn} Uni:{nm(uid)}@{uw}({ue}エネ/コスト{umin}-{umax}) ⇔ 専用:{nm(sid)}@{sw}({se}エネ)")
                    ret = u
                else:
                    ret = uni.select(Observation.from_dict(obs)) or [0]
            else:
                ret = opp.select(Observation.from_dict(obs)) or [0]
            obs = battle_select(ret); steps += 1
        battle_finish()
    total = sum(cats.values())
    print(f"=== {deck}: Attach先不一致の原因分類 ({total}件, 専用のエネ最優先先={nm(spec_rule1)}) ===")
    for cat, n in cats.most_common():
        print(f"  {cat:<36} {n:>3} ({100*n//max(1,total)}%)")
    for e in ex:
        print(f"    例: {e}")
    return cats


if __name__ == "__main__":
    total = Counter()
    for d, k in [("lightning", "lightning"), ("archaludon_real", "archaludon")]:
        total += main(d, k); print()
    s = sum(total.values())
    print("=== 合計 ===")
    for cat, n in total.most_common():
        print(f"  {cat:<36} {n:>3} ({100*n//max(1,s)}%)")
