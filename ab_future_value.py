"""A/B: エネ将来価値原則(avoid_overstack一般化=②'死亡濃厚activeへの注ぎ回避+Ignition解放例外)。

対象: 提出bot(MegaStarmiePlanBot)。B案=plan.avoid_overstack=True(新原則ごと有効化)。
測定(ユーザ指定): 勝率(新旧ミラー+対フィールドmegaruka/archaludon) と
                 行動メトリクス「死亡濃厚activeへのAttach率」(何%→何%)。
"""
import sys, os
from dataclasses import replace
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cabt_bot.arena import run_match
from cabt_bot import Observation, load_cards
from cabt_bot.bots import deck_registry as R
from cabt_bot.bots.deck_registry import MegaStarmiePlanBot, STARMIE_PLAN
from cabt_bot.state_encoder import line_threat
from cabt_bot.enums import SelectType, OptionType

C = load_cards()
MAIN = int(SelectType.MAIN); ATTACH = int(OptionType.ATTACH)
MEGA = 1031; STARYU = 1030


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def make_tracked(bot, met):
    def agent(o):
        sel_ids = bot.select(Observation.from_dict(o)) or [0]
        s = o.get("select") or {}
        opts = s.get("option") or []
        if s.get("type") == MAIN and sel_ids and sel_ids[0] < len(opts):
            ch = opts[sel_ids[0]]
            cur = o.get("current") or {}
            yi = cur.get("yourIndex", 0)
            me = (cur.get("players") or [{}, {}])[yi]
            opp = (cur.get("players") or [{}, {}])[1 - yi]
            a = (me.get("active") or [None])[0]
            oa = (opp.get("active") or [None])[0]
            if ch.get("type") == ATTACH and a and oa:
                dmg = line_threat(oa.get("id")) or 0
                mc = C.get(a.get("id")); oc = C.get(oa.get("id"))
                if mc and oc and mc.weakness and oc.type == mc.weakness:
                    dmg *= 2
                doomed = (a.get("hp") or 999) <= dmg
                succ = any(b and b.get("id") in (MEGA, STARYU) for b in (me.get("bench") or []))
                if doomed and succ:
                    met["doomed_states"] += 1
                    if ch.get("inPlayArea") == 4:
                        met["doomed_act_attach"] += 1
        return sel_ids
    return agent


def series(mk_a, mk_b, deck_a, deck_b, games):
    """mk_*: fn()->bot。aの勝率とaの行動メトリクスを返す(先後交替)。"""
    wins = 0; dec = 0
    met = {"doomed_states": 0, "doomed_act_attach": 0}
    for g in range(games):
        ba = mk_a(); bb = mk_b()
        aa = make_tracked(ba, met)
        ab = (lambda b: (lambda o: b.select(Observation.from_dict(o)) or [0]))(bb)
        if g % 2 == 0:
            r = run_match(aa, ab, deck_a, deck_b); w = (r.winner == 0)
        else:
            r = run_match(ab, aa, deck_b, deck_a); w = (r.winner == 1)
        if r.winner in (0, 1):
            dec += 1; wins += int(w)
    rate = met["doomed_act_attach"] / max(1, met["doomed_states"])
    return wins / max(1, dec), rate, met["doomed_states"]


def main(games=100):
    md = load("deck")
    NEW_PLAN = replace(STARMIE_PLAN, avoid_overstack=True)
    mk_old = lambda: MegaStarmiePlanBot(decklist=md)
    def mk_new():
        b = MegaStarmiePlanBot(decklist=md); b.plan = NEW_PLAN; b._base_plan = NEW_PLAN
        return b
    print("=== A/B: エネ将来価値原則 (提出bot) ===")
    wr, dr, n = series(mk_new, mk_old, md, md, games)
    print(f"ミラー新旧: 新の勝率 {wr:.1%} | 新の死亡濃厚Attach率 {dr:.0%} ({n}局面)")
    _, dro, no = series(mk_old, mk_new, md, md, 30)
    print(f"  (参考: 旧の死亡濃厚Attach率 {dro:.0%} ({no}局面))")
    for opp_key, opp_deck in [("megaruka", "megaruka"), ("archaludon", "archaludon_real")]:
        od = load(opp_deck)
        mk_o = lambda: R.DECK_BOTS[opp_key](decklist=od)
        wr_n, dr_n, n_n = series(mk_new, mk_o, md, od, games)
        wr_o, dr_o, n_o = series(mk_old, mk_o, md, od, games)
        print(f"vs {opp_key}: 旧 {wr_o:.1%} → 新 {wr_n:.1%} | 死亡濃厚Attach率 旧{dr_o:.0%}({n_o}) → 新{dr_n:.0%}({n_n})")


if __name__ == "__main__":
    main()
