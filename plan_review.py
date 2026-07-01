"""Plan AI: divergence の genuine review。1ターン最善≠3ターン最善の各局面で、
「Planが何を見たか」を終端盤面の事実(Analyzer)差分で説明する（=PlanにExplainを付ける, Episode2）。

規律: horizon統一やseed分解より先に、まず6件の中身を人間が読む。
各件で: a1(1turn最善)/aH(3turn最善) のカード名＋終端事実の差 を出し、A/B/C/D判定の材料にする。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class
from cabt_bot import Observation, load_cards
from cabt_bot.bots import deck_registry as R
from cabt_bot.enums import SelectType, OptionType

MAIN = int(SelectType.MAIN)
OT = {int(getattr(OptionType, x)): x for x in ("PLAY", "ATTACH", "EVOLVE", "ABILITY", "RETREAT", "ATTACK", "END", "CARD")}
C = load_cards()
NM = lambda cid: (C[cid].name if cid in C else f"#{cid}")


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def label(opt, hand):
    """optionを人間可読に: 'PLAY レリカンス' 等。index=手札インデックス。"""
    t = OT.get(opt.get("type"), "?")
    idx = opt.get("index")
    if idx is not None and hand and 0 <= idx < len(hand):
        return f"{t} {NM(hand[idx].get('id'))}"
    return t


def explain(a1c, aHc):
    """終端事実(aH vs a1)の差をPlanのExplainとして返す＋自動ヒント。"""
    if not a1c or not aHc:
        return "(終端事実なし)", "C"
    parts = []
    for k, lab in [("evolved", "進化済攻撃役"), ("attackers", "攻撃役"), ("energy", "盤面エネ"),
                   ("ready", "攻撃準備"), ("prize_diff", "サイド差"), ("hits_to_lose", "被KO余裕")]:
        d = round(aHc[k] - a1c[k], 1)
        if abs(d) >= 0.3:
            parts.append(f"{lab}{'+' if d>0 else ''}{d}")
    # 自動ヒント: 育成事実がaHで明確に良い=Plan / ほぼ同一なのにposition差=運疑い
    dev_gain = (aHc["evolved"] - a1c["evolved"]) * 2 + (aHc["ready"] - a1c["ready"]) * 2 + \
               (aHc["energy"] - a1c["energy"]) + (aHc["prize_diff"] - a1c["prize_diff"]) - \
               (aHc["evolution_short"] - a1c["evolution_short"])
    if dev_gain >= 2:
        hint = "A/B(育成/サイドがaHで明確に良い=Plan)"
    elif dev_gain <= -1:
        hint = "D?(aHの終端事実が悪いのにposition高=要精査)"
    elif not parts:
        hint = "C(終端事実ほぼ同一=引き運疑い)"
    else:
        hint = "B/C(小差)"
    return ("; ".join(parts) if parts else "終端事実ほぼ同一"), hint


def main(max_decisions=24, max_cand=5, horizon=3, seeds=(7, 17, 29)):
    ad = load("archaludon_real"); md = load("deck")
    b = R.DECK_BOTS["archaludon"](decklist=ad); o = R.DECK_BOTS["deck"]()
    n_dec = 0; viol = 0; divs = []
    for g in range(25):
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
                hand = obs["current"]["players"][0].get("hand") if obs.get("current") else None
                cands = list(range(min(len(sel["option"]), max_cand)))
                t1 = {}; tH = {}; trajs = {}; comps = {}; chains = {}
                for i in cands:
                    p = b.evaluate_plan(obs, i, root_player=0, horizon=horizon, seeds=seeds, record_chain=True)
                    if p and len(p["trajectory"]) >= 2:
                        t1[i] = p["trajectory"][0]; tH[i] = p["trajectory"][-1]
                        trajs[i] = p["trajectory"]; comps[i] = p["terminal_comp"]; chains[i] = p["chain"]
                        viol += p["invariant_violations"]
                if len(t1) >= 2:
                    n_dec += 1
                    a1 = max(t1, key=lambda i: t1[i]); aH = max(tH, key=lambda i: tH[i])
                    if a1 != aH:
                        exp, hint = explain(comps[a1], comps[aH])
                        divs.append({"turn": st.turn,
                                     "a1": label(sel["option"][a1], hand), "aH": label(sel["option"][aH], hand),
                                     "t1_gap": round(t1[a1] - t1[aH], 1), "tH_gap": round(tH[aH] - tH[a1], 1),
                                     "traj_a1": trajs[a1], "traj_aH": trajs[aH],
                                     "comp_a1": comps[a1], "comp_aH": comps[aH], "explain": exp, "hint": hint,
                                     "chain_a1": chains[a1], "chain_aH": chains[aH]})
                ret = b.select(Observation.from_dict(obs))
            else:
                ret = b.select(Observation.from_dict(obs)) if who == 0 else o.select(Observation.from_dict(obs))
            obs = battle_select(ret or [0]); steps += 1
        battle_finish()

    print(f"=== Plan Divergence REVIEW ({n_dec}決定中 {len(divs)}件食い違い, Invariant違反{viol}) ===\n")
    for k, d in enumerate(divs, 1):
        print(f"[{k}] T{d['turn']}  1turn最善: {d['a1']}   →   3turn最善: {d['aH']}")
        print(f"     1turn: a1が+{d['t1_gap']}上 / 3turn: aHが+{d['tH_gap']}逆転")
        print(f"     traj a1={d['traj_a1']}  aH={d['traj_aH']}")
        print(f"     終端事実(aH-a1): {d['explain']}")
        print(f"     Chain a1: {' → '.join(d['chain_a1'])}")
        print(f"     Chain aH: {' → '.join(d['chain_aH'])}")
        print(f"     自動ヒント: {d['hint']}\n")


if __name__ == "__main__":
    main()
