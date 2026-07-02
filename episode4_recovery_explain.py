"""Episode 4 Phase1: Archaludon の Recovery(夜のタンカ等)142回/100戦 の Explain 分解。

測定:
  ① 使用回数と「何を回収したか」(Uni実プレイ vs 専用実プレイ)
  ② 同一局面ペア: UniがRecoveryを選んだ局面で専用は何を選ぶか
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
MAIN = int(SelectType.MAIN); PLAY = int(OptionType.PLAY); CARD = int(SelectType.CARD)


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def run(deck, spec_key, botfn, shadow_pairs=False, games=12):
    dl = load(deck)
    rec_ids = {1097}                         # Night Stretcher(夜のタンカ)
    plays = 0; retrieved = Counter(); pair = Counter()
    for g in range(games):
        bot = botfn(dl); opp = R.DECK_BOTS[spec_key](decklist=dl)
        shadow = R.DECK_BOTS[spec_key](decklist=dl) if shadow_pairs else None
        obs, _ = battle_start(dl, dl); steps = 0; pending_recover = False
        while obs is not None and steps < 400:
            st = to_observation_class(obs).current
            if st and st.result != -1:
                break
            if not (obs.get("select") and obs["select"].get("option")):
                break
            who = st.yourIndex if st else 0; sel = obs["select"]
            if who == 0:
                cur = obs["current"]; me = cur["players"][0]
                ret = bot.select(Observation.from_dict(obs)) or [0]
                if pending_recover and sel.get("type") == CARD:
                    disc = me.get("discard") or []
                    for r in ret:
                        ch = sel["option"][r] if r < len(sel["option"]) else {}
                        idx = ch.get("index")
                        if idx is not None and 0 <= idx < len(disc):
                            retrieved[nm(disc[idx]["id"])] += 1
                    pending_recover = False
                if sel.get("type") == MAIN and ret and ret[0] < len(sel["option"]):
                    ch = sel["option"][ret[0]]
                    hand = me.get("hand") or []
                    if ch.get("type") == PLAY and ch.get("index") is not None and ch["index"] < len(hand) \
                            and hand[ch["index"]]["id"] in rec_ids:
                        plays += 1; pending_recover = True
                        if shadow is not None:
                            s = shadow.select(Observation.from_dict(obs)) or [0]
                            so = sel["option"][s[0]] if s[0] < len(sel["option"]) else {}
                            t = so.get("type"); lbl = str(t)
                            if t == PLAY and so.get("index") is not None and so["index"] < len(hand):
                                lbl = f"PLAY {nm(hand[so['index']]['id'])}"
                            else:
                                from cabt_bot.enums import OptionType as _O
                                lbl = {int(_O.ATTACH): "ATTACH", int(_O.ATTACK): "ATTACK",
                                       int(_O.EVOLVE): "EVOLVE", int(_O.END): "END"}.get(t, lbl)
                            pair[lbl] += 1
            else:
                ret = opp.select(Observation.from_dict(obs)) or [0]
            obs = battle_select(ret); steps += 1
        battle_finish()
    return plays, retrieved, pair


if __name__ == "__main__":
    d, k = "archaludon_real", "archaludon"
    up, uret, upair = run(d, k, lambda x: UniversalBot(decklist=x), shadow_pairs=True)
    sp, sret, _ = run(d, k, lambda x: R.DECK_BOTS[k](decklist=x))
    print(f"=== {d}: Recovery(夜のタンカ) 使用分析 (12戦) ===")
    print(f"① 使用回数: Uni {up}回 / 専用 {sp}回")
    print(f"   Uni回収内容: {dict(uret.most_common())}")
    print(f"   専用回収内容: {dict(sret.most_common())}")
    print(f"② UniがRecoveryした同一局面で専用が選んだ手: {dict(upair.most_common())}")
