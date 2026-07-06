"""Plan AI Episode 3: Opponent Rollout が Plan に影響するかを、既存OSだけで測る（勝率でない）。

自分だけ未来(passive) vs 相手も打つ未来(opponent) を同一seedで比べ、3つを見る:
  ① Decision Difference : 相手が入ると 3ターン最善(argmax) が変わるか
  ② Capability Difference: passiveで築けた能力が opponent で消える/遅れるか(Recovery→KOされた 等)
  ③ Plan Stability       : 同じ初手の cap_chain が passive と opponent で同じか
制約(遵守): 新Analyzer禁止。OpponentPolicy薄い層。既存 cap_chain / trajectory / chain_diff のみ。
相手は既知Megaデッキで determinize（filler誤プレイを排除）。
"""
import sys, os
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class
from cabt_bot import Observation
from cabt_bot.bots import deck_registry as R
from cabt_bot.bots.opponent_policy import BotOpponent
from cabt_bot.enums import SelectType

MAIN = int(SelectType.MAIN)


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def cdiff(ca, cb):
    A, B = Counter(ca or []), Counter(cb or [])
    return list((A - B).elements()), list((B - A).elements())   # a_only, b_only


def main(max_decisions=8, max_cand=3, horizon=3, seeds=(7, 17, 29)):
    ad = load("archaludon_real"); md = load("deck")
    b = R.DECK_BOTS["archaludon"](decklist=ad); o = R.DECK_BOTS["deck"]()
    mega = BotOpponent(R.DECK_BOTS["deck"]())
    n_dec = 0; dec_changed = 0; stable = 0; viol = 0; lost_all = []; ex = []
    for g in range(20):
        if n_dec >= max_decisions:
            break
        obs, _ = battle_start(ad, md); steps = 0
        while obs is not None and steps < 1500 and n_dec < max_decisions:
            st = to_observation_class(obs).current
            if st and st.result != -1:
                break
            if not (obs.get("select") and obs["select"].get("option")):
                break
            who = st.yourIndex if st else 0; sel = obs["select"]
            if who == 0 and sel.get("type") == MAIN and obs.get("search_begin_input") and len(sel["option"]) >= 2:
                cands = list(range(min(len(sel["option"]), max_cand)))
                pasT = {}; oppT = {}; pasC = {}; oppC = {}
                for i in cands:
                    p = b.evaluate_plan(obs, i, root_player=0, horizon=horizon, seeds=seeds, record_chain=True)
                    q = b.evaluate_plan(obs, i, root_player=0, horizon=horizon, seeds=seeds, record_chain=True,
                                        opponent=mega, opp_decklist=md)
                    if p and q and len(p["trajectory"]) >= 1 and len(q["trajectory"]) >= 1:
                        pasT[i] = p["trajectory"][-1]; oppT[i] = q["trajectory"][-1]
                        pasC[i] = p["cap_chain"]; oppC[i] = q["cap_chain"]
                        viol += p["invariant_violations"] + q["invariant_violations"]
                if len(pasT) >= 2:
                    n_dec += 1
                    a_pas = max(pasT, key=lambda i: pasT[i]); a_opp = max(oppT, key=lambda i: oppT[i])
                    if a_pas != a_opp:
                        dec_changed += 1
                    lost, gained = cdiff(pasC[a_pas], oppC[a_pas])   # passiveで有り→opponentで無い=相手に潰された能力
                    lost_all.append(len(lost))
                    if pasC[a_pas] == oppC[a_pas]:
                        stable += 1
                    if len(ex) < 6 and (a_pas != a_opp or lost):
                        ex.append({"turn": st.turn, "changed": a_pas != a_opp,
                                   "pas_cap": pasC[a_pas], "opp_cap": oppC[a_pas], "lost": lost, "gained": gained})
                ret = b.select(Observation.from_dict(obs))
            else:
                ret = b.select(Observation.from_dict(obs)) if who == 0 else o.select(Observation.from_dict(obs))
            obs = battle_select(ret or [0]); steps += 1
        battle_finish()

    print(f"=== Episode 3: Opponent Rollout の影響 ({n_dec}決定, Invariant違反{viol}) ===")
    print(f"① Decision Difference : 相手で3ターン最善が変わった {dec_changed}/{n_dec}")
    print(f"② Capability Difference: 相手で消えた能力 平均{round(sum(lost_all)/max(1,len(lost_all)),2)}個/決定")
    print(f"③ Plan Stability      : 初手のcap_chainが不変 {stable}/{n_dec}")
    print("--- 例（相手が入って変わった決定）---")
    for e in ex:
        print(f"  T{e['turn']} {'[最善が変化]' if e['changed'] else '[能力が変化]'}")
        print(f"     passive cap: {e['pas_cap']}")
        print(f"     opponent cap: {e['opp_cap']}")
        print(f"     相手に潰された: {e['lost']}   相手で増えた: {e['gained']}")


if __name__ == "__main__":
    main()
