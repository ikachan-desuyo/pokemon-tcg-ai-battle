"""Plan AI (Episode 1) 核心の測定: 1ターン評価と3ターン評価で"最善候補"が食い違う決定を集める。

問い: per-turn(TurnResult) の argmax と、複数ターン(evaluate_plan) の argmax は一致するか?
  一致するなら per-turn で十分。食い違う所こそ Plan の出番(今の犠牲/仕込みが後で効く)。
規律: 勝率を見ない。Invariant違反を全rolloutで監視(Plan rolloutが健全か)。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class
from cabt_bot import Observation
from cabt_bot.bots import deck_registry as R
from cabt_bot.enums import SelectType, OptionType

MAIN = int(SelectType.MAIN)
OT = {int(getattr(OptionType, x)): x for x in ("PLAY", "ATTACH", "EVOLVE", "ABILITY", "RETREAT", "ATTACK", "END", "CARD")}


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def main(max_decisions=24, max_cand=5, horizon=3, seeds=(7, 17, 29)):
    ad = load("archaludon_real"); md = load("deck")
    b = R.DECK_BOTS["archaludon"](decklist=ad); o = R.DECK_BOTS["deck"]()
    obs, _ = battle_start(ad, md); steps = 0
    n_dec = 0; n_div = 0; viol = 0; divergences = []
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
                t1 = {}; tH = {}; trajs = {}
                for i in cands:
                    p = b.evaluate_plan(obs, i, root_player=0, horizon=horizon, seeds=seeds)
                    if p and len(p["trajectory"]) >= 2:
                        # フェア比較: 1ターン値も3ターン値も同一plan(同一seed集合)から取る=差はhorizon純粋由来
                        t1[i] = p["trajectory"][0]; tH[i] = p["trajectory"][-1]; trajs[i] = p["trajectory"]
                        viol += p["invariant_violations"]
                if len(t1) >= 2:
                    n_dec += 1
                    a1 = max(t1, key=lambda i: t1[i])       # 1ターン最善
                    aH = max(tH, key=lambda i: tH[i])       # 3ターン最善
                    if a1 != aH:
                        n_div += 1
                        divergences.append({
                            "turn": st.turn, "a1": a1, "aH": aH,
                            "a1_type": OT.get(sel["option"][a1].get("type")),
                            "aH_type": OT.get(sel["option"][aH].get("type")),
                            "t1_gap": round(t1[a1] - t1[aH], 1),      # 1ターンでa1がaHをどれだけ上回るか
                            "tH_gap": round(tH[aH] - tH[a1], 1),      # 3ターンでaHがa1をどれだけ上回るか
                            "traj_a1": trajs[a1], "traj_aH": trajs[aH]})
                ret = b.select(Observation.from_dict(obs))
            else:
                ret = b.select(Observation.from_dict(obs)) if who == 0 else o.select(Observation.from_dict(obs))
            obs = battle_select(ret or [0]); steps += 1
        battle_finish()

    print(f"=== Plan Episode 1: 1ターン vs 3ターン 最善の食い違い ===")
    print(f"  検査した決定: {n_dec}")
    print(f"  食い違い(argmax1 != argmaxH): {n_div} ({100*n_div//max(1,n_dec)}%)")
    print(f"  Plan rollout中のInvariant違反: {viol} (0が健全)")
    print(f"  --- 食い違い例(3ターン視点で別の手が最善になった) ---")
    for d in divergences[:10]:
        print(f"  T{d['turn']}: 1turn最善={d['a1_type']}(#{d['a1']}) → 3turn最善={d['aH_type']}(#{d['aH']})")
        print(f"      1turnではa1が+{d['t1_gap']}上 / 3turnではaHが+{d['tH_gap']}逆転")
        print(f"      traj a1={d['traj_a1']}  aH={d['traj_aH']}")


if __name__ == "__main__":
    main()
