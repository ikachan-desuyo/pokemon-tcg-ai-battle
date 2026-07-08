"""Episode 4: Megaベンチ薄さのExplain分解(数でなく内容・「置けたのに置かない」vs「置けない(運)」の分離)。

Part A: Uniの各ターン終了時(END/ATTACK選択時)に分類
  - MISSED_DIRECT: 選択肢にたねのPLAYがあったのに選ばなかった(=AIの問題)
  - HELD_SEARCH  : ベンチ空きあり・手札にサーチ札(Poffin/Ball等)があるのに温存
  - NO_RESOURCE  : ベンチ空きあり・置く手段が手札に無い(=運/ドロー力)
  - BENCH_FULL   : 空きなし(問題なし)
Part B: ベンチ"内容"の比較(自ターン3/5時点のベンチ構成を Uni実プレイ vs 専用実プレイで集計)
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
MAIN = int(SelectType.MAIN); PLAY = int(OptionType.PLAY)
END = int(OptionType.END); ATTACK = int(OptionType.ATTACK)
SEARCH_KEYS = ("Ball", "Poffin", "Pad", "Pokégear")


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def audit(deck, spec_key, botfn, games=12):
    dl = load(deck)
    cls = Counter(); missed = Counter(); bench_at = {3: Counter(), 5: Counter()}
    for g in range(games):
        bot = botfn(dl); opp = R.DECK_BOTS[spec_key](decklist=dl)
        obs, _ = battle_start(dl, dl); steps = 0; my_turn = 0; last_turn = None
        while obs is not None and steps < 400:
            st = to_observation_class(obs).current
            if st and st.result != -1:
                break
            if not (obs.get("select") and obs["select"].get("option")):
                break
            who = st.yourIndex if st else 0; sel = obs["select"]
            if who == 0:
                cur = obs["current"]; me = cur["players"][0]; turn = cur.get("turn", 0)
                if turn != last_turn:
                    last_turn = turn; my_turn += 1
                    if my_turn in bench_at:
                        for b in (me.get("bench") or []):
                            if b:
                                bench_at[my_turn][nm(b["id"])] += 1
                ret = bot.select(Observation.from_dict(obs)) or [0]
                if sel.get("type") == MAIN and ret and ret[0] < len(sel["option"]):
                    ch = sel["option"][ret[0]]
                    if ch.get("type") in (END, ATTACK):          # ターン終了時に分類
                        hand = me.get("hand") or []
                        space = 5 - len([b for b in (me.get("bench") or []) if b])
                        if space <= 0:
                            cls["BENCH_FULL"] += 1
                        else:
                            playable_basic = None
                            for op_ in sel["option"]:
                                if op_.get("type") == PLAY and op_.get("index") is not None \
                                        and op_["index"] < len(hand):
                                    cid = hand[op_["index"]]["id"]
                                    ci = C.get(cid)
                                    if ci and ci.is_pokemon and ci.is_basic:
                                        playable_basic = cid; break
                            if playable_basic is not None:
                                cls["MISSED_DIRECT"] += 1
                                missed[nm(playable_basic)] += 1
                            elif any(any(k in (C.get(c["id"]).name if C.get(c["id"]) else "")
                                         for k in SEARCH_KEYS) for c in hand):
                                cls["HELD_SEARCH"] += 1
                            else:
                                cls["NO_RESOURCE"] += 1
            else:
                ret = opp.select(Observation.from_dict(obs)) or [0]
            obs = battle_select(ret); steps += 1
        battle_finish()
    return cls, missed, bench_at


def main(deck="deck", spec_key="deck", games=12):
    print(f"=== {deck}: ベンチ薄さの分解 (Uni実プレイ, {games}戦) ===")
    cls, missed, uni_b = audit(deck, spec_key, lambda d: UniversalBot(decklist=d), games)
    tot = sum(cls.values())
    for k, n in cls.most_common():
        print(f"  {k:<14} {n:>3} ({100*n//max(1,tot)}%)")
    if missed:
        print(f"  MISSED_DIRECTの内訳: {dict(missed.most_common())}")
    _, _, spec_b = audit(deck, spec_key, lambda d: R.DECK_BOTS[spec_key](decklist=d), games)
    for t in (3, 5):
        print(f"\n  --- 自ターン{t}時点のベンチ内容(出現回数/{games}戦) ---")
        names = sorted(set(uni_b[t]) | set(spec_b[t]))
        for n_ in names:
            print(f"    {n_:<18} Uni:{uni_b[t].get(n_,0):>2}  専用:{spec_b[t].get(n_,0):>2}")


if __name__ == "__main__":
    main()
