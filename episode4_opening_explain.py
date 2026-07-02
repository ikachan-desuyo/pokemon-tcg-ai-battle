"""Episode 4: Opening(開幕)弱点のExplain分解。T0〜T2の全選択を専用bot(shadow)と同一局面比較。

分類したい原因候補:
  (a) go_first: 先攻/後攻の回答が違う
  (b) SETUP(初期配置): 同じ手札から置く枚数/選択が違う(ベンチ薄さの根源?)
  (c) 早期MAIN: PLAY(ポケモン展開)/ボール系の使い方が違う
  (d) 手札運(そもそも置ける札が無い)
"""
import sys, os
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class
from cabt_bot import Observation, load_cards
from cabt_bot.bots import deck_registry as R
from cabt_bot.bots.universal_bot import UniversalBot
from cabt_bot.enums import SelectType, OptionType

C = load_cards(); nm = lambda i: (C[i].name if i in C else f"#{i}")
ST = {int(getattr(SelectType, x)): x for x in dir(SelectType) if x.isupper()}
OT = {int(getattr(OptionType, x)): x for x in dir(OptionType) if x.isupper()}


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def choice_desc(sel, ret, me):
    """選択リストを内容(カード名/タイプ)の集合で表す。"""
    out = []
    hand = me.get("hand") or []
    for r in ret:
        if r >= len(sel["option"]):
            continue
        ch = sel["option"][r]
        t = OT.get(ch.get("type"), str(ch.get("type")))
        idx = ch.get("index")
        card = nm(hand[idx]["id"]) if (idx is not None and 0 <= idx < len(hand) and ch.get("area") in (None, 2)) else ""
        out.append(f"{t} {card}".strip())
    return tuple(sorted(out))


def main(deck, spec_key, games=14):
    dl = load(deck)
    cats = Counter(); ex = []
    for g in range(games):
        uni = UniversalBot(decklist=dl)
        shadow = R.DECK_BOTS[spec_key](decklist=dl)
        opp = R.DECK_BOTS[spec_key](decklist=dl)
        obs, _ = battle_start(dl, dl); steps = 0
        while obs is not None and steps < 120:
            st = to_observation_class(obs).current
            if st and st.result != -1:
                break
            if not (obs.get("select") and obs["select"].get("option")):
                break
            turn = (obs.get("current") or {}).get("turn", 0)
            if turn > 2:
                break
            who = st.yourIndex if st else 0; sel = obs["select"]
            if who == 0:
                me = obs["current"]["players"][0]
                u = uni.select(Observation.from_dict(obs)) or [0]
                s = shadow.select(Observation.from_dict(obs)) or [0]
                ud = choice_desc(sel, u, me); sd = choice_desc(sel, s, me)
                if ud != sd:
                    styp = ST.get(sel.get("type"), sel.get("type"))
                    ctx = sel.get("context")
                    key = f"{styp}/ctx{ctx}"
                    cats[key] += 1
                    if len(ex) < 10:
                        hand_pokes = [nm(c["id"]) for c in (me.get("hand") or [])
                                      if C.get(c["id"]) and C[c["id"]].is_pokemon]
                        ex.append(f"T{turn} [{key}] Uni:{list(ud)} ⇔ 専用:{list(sd)} | 手札ポケ:{hand_pokes}")
                ret = u
            else:
                ret = opp.select(Observation.from_dict(obs)) or [0]
            obs = battle_select(ret); steps += 1
        battle_finish()
    print(f"=== {deck}: 開幕(T0-T2) 同一局面の選択差分 ===")
    for k, n in cats.most_common():
        print(f"  {k:<28} {n}")
    for e in ex:
        print(f"    {e}")


if __name__ == "__main__":
    for d, k in [("deck", "deck"), ("archaludon_real", "archaludon")]:
        main(d, k); print()
