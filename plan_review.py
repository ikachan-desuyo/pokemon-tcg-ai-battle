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


DEV_CAPS = {"攻撃役Exists", "エネReady", "進化Attacker", "攻撃Possible"}   # 育成の「途中」=Plan価値


def chain_diff(ca1, caH):
    """Chain Difference: aHのcap_chainにあってa1に無い能力/イベント(と逆)。順序でなく多重集合差。"""
    from collections import Counter
    c1 = Counter(ca1 or []); cH = Counter(caH or [])
    only_aH = list((cH - c1).elements())     # aHだけが到達した能力/成果
    only_a1 = list((c1 - cH).elements())
    return only_aH, only_a1


DECOMP_SEEDS = (7, 17, 29, 41, 53, 67, 79, 97)   # A判定だけを個別seedで検証


def seed_decompose(b, obs, a1, aH, dev_caps, horizon):
    """A判定の妥当性テスト: a1/aHを個別seedで走らせ、aHが「全seedで勝つ＋育成能力を安定して築く」か。
    全seed勝ち=decision由来(本物Plan) / seed毎に勝者が変わる=引き運。"""
    wins = 0; dev_ok = 0; n = 0; margins = []
    for s in DECOMP_SEEDS:
        p1 = b.evaluate_plan(obs, a1, root_player=0, horizon=horizon, seeds=(s,), record_chain=True)
        pH = b.evaluate_plan(obs, aH, root_player=0, horizon=horizon, seeds=(s,), record_chain=True)
        if not (p1 and pH):
            continue
        n += 1
        m = round(pH["terminal"] - p1["terminal"], 1); margins.append(m)
        if m > 0:
            wins += 1
        if all(c in set(pH["cap_chain"]) for c in dev_caps):   # aHが同じ育成能力を築いたか
            dev_ok += 1
    return {"wins": wins, "dev_ok": dev_ok, "n": n, "margins": margins}


def categorize(ca1, caH):
    """A=Plan / B=Passive Opponent Bias / C=Equivalent / D=Bug。cap_chainの差で判定。"""
    only_aH, only_a1 = chain_diff(ca1, caH)
    dev_gain_aH = [x for x in only_aH if x in DEV_CAPS]        # aHが余分に築いた"途中(育成)"
    attack_only_aH = [x for x in only_aH if x in ("Attack",) or x.startswith("Prize")]
    if not only_aH and not only_a1:
        return "C(Equivalent: cap_chain同一)"
    # aHが育成の途中(Recovery/Evo/Ready)を余分に築いた＝本物のPlan
    if dev_gain_aH:
        return f"A(Plan: aHが育成連鎖を築いた {dev_gain_aH})"
    # aHの差が攻撃/サイドのみで、育成の途中を築いていない＝前のめり(相手が殴らせてくれた疑い)
    if attack_only_aH and not dev_gain_aH:
        return f"B(Passive Opponent Bias: 育成でなく先制Attack/Prize {attack_only_aH})"
    return "C/D(要精査: cap差はあるが育成でも攻撃でもない)"


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
                t1 = {}; tH = {}; trajs = {}; capchains = {}
                for i in cands:
                    p = b.evaluate_plan(obs, i, root_player=0, horizon=horizon, seeds=seeds, record_chain=True)
                    if p and len(p["trajectory"]) >= 2:
                        t1[i] = p["trajectory"][0]; tH[i] = p["trajectory"][-1]
                        trajs[i] = p["trajectory"]; capchains[i] = p["cap_chain"]
                        viol += p["invariant_violations"]
                if len(t1) >= 2:
                    n_dec += 1
                    a1 = max(t1, key=lambda i: t1[i]); aH = max(tH, key=lambda i: tH[i])
                    if a1 != aH:
                        only_aH, only_a1 = chain_diff(capchains[a1], capchains[aH])
                        cat = categorize(capchains[a1], capchains[aH])
                        sd = None
                        if cat.startswith("A"):            # A判定だけ seed分解で妥当性を確認
                            dev_caps = [x for x in only_aH if x in DEV_CAPS]
                            sd = seed_decompose(b, obs, a1, aH, dev_caps, horizon)
                        divs.append({"turn": st.turn,
                                     "a1": label(sel["option"][a1], hand), "aH": label(sel["option"][aH], hand),
                                     "t1_gap": round(t1[a1] - t1[aH], 1), "tH_gap": round(tH[aH] - tH[a1], 1),
                                     "traj_a1": trajs[a1], "traj_aH": trajs[aH],
                                     "cap_a1": capchains[a1], "cap_aH": capchains[aH],
                                     "only_aH": only_aH, "only_a1": only_a1, "cat": cat, "sd": sd})
                ret = b.select(Observation.from_dict(obs))
            else:
                ret = b.select(Observation.from_dict(obs)) if who == 0 else o.select(Observation.from_dict(obs))
            obs = battle_select(ret or [0]); steps += 1
        battle_finish()

    from collections import Counter
    tally = Counter(d["cat"][0] for d in divs)   # 先頭文字 A/B/C/D で集計
    print(f"=== Plan Divergence REVIEW ({n_dec}決定中 {len(divs)}件食い違い, Invariant違反{viol}) ===")
    print(f"    カテゴリ集計: {dict(tally)}  (A=Plan / B=PassiveOppBias / C=Equivalent / D=Bug)\n")
    for k, d in enumerate(divs, 1):
        print(f"[{k}] T{d['turn']}  1turn最善: {d['a1']}   →   3turn最善: {d['aH']}")
        print(f"     traj a1={d['traj_a1']}  aH={d['traj_aH']}  (3turnでaHが+{d['tH_gap']})")
        print(f"     Cap a1: {' → '.join(d['cap_a1']) or '(なし)'}")
        print(f"     Cap aH: {' → '.join(d['cap_aH']) or '(なし)'}")
        print(f"     Chain Diff: aHのみ={d['only_aH']}  a1のみ={d['only_a1']}")
        print(f"     判定: {d['cat']}")
        if d["sd"]:
            s = d["sd"]
            verdict = "本物Plan(全seed勝ち＋育成安定)" if (s["wins"] == s["n"] and s["dev_ok"] == s["n"]) \
                else ("引き運疑い(seed毎に勝敗変動)" if s["wins"] <= s["n"] * 0.6 else "有力(過半seed勝ち)")
            print(f"     ★seed分解: aH勝ち {s['wins']}/{s['n']}  育成能力安定 {s['dev_ok']}/{s['n']}  margins={s['margins']} → {verdict}")
        print()


if __name__ == "__main__":
    main()
