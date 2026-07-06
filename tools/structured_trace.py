"""LLMコーチ用の『構造化(JSON)意思決定トレース』を出力する。

人間用の decision_trace.py と違い、機械可読JSONで出す:
各P0決定について {turn, my_board, opp_board, candidates:[{type,name,score,reason,chosen}], outcome}。
これを LLM コーチ(tools/coach.py)に渡し、misplay検出と改善提案を得る = LLM-in-the-loop開発の入力。
"""
import sys, json, argparse
sys.path.insert(0, ".")
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class, all_attack
from cabt_bot import Observation, load_cards
from cabt_bot.enums import OptionType
from cabt_bot.bots import deck_registry as R

C = load_cards(); nm = lambda c: C[c].name if c in C else f"#{c}"
AN = {a.attackId: a.name for a in all_attack()}
OT = {int(getattr(OptionType, x)): x for x in ("PLAY", "ATTACH", "EVOLVE", "ATTACK", "ABILITY", "RETREAT", "END")}


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def spot(s):
    if not s:
        return None
    e = s.get("energyCards") or s.get("energies") or []
    return {"id": s.get("id"), "name": nm(s.get("id")), "hp": s.get("hp"),
            "maxHp": s.get("maxHp"), "energy": len(e)}


def board(cur, who):
    p = cur["players"][who]
    pr = p.get("prize") or p.get("prizes") or []
    return {
        "active": spot((p.get("active") or [None])[0]),
        "bench": [spot(s) for s in (p.get("bench") or []) if s],
        "prizes_left": sum(1 for x in pr if x) if pr else None,
        "hand_size": len(p.get("hand") or []),
    }


def decision_record(bot, parsed, cur, rs):
    """1決定の構造化レコードを返す(候補手＋score＋reason＋選択)。"""
    opts = rs["option"]; ch = bot.select(parsed); chosen = ch[0] if ch else None
    hand = cur["players"][0].get("hand") or []
    cands = []
    for i, op in enumerate(opts):
        ty = op.get("type"); rec = {"type": OT.get(ty, ty), "chosen": (i == chosen)}
        if ty in (int(OptionType.PLAY), int(OptionType.ATTACH), int(OptionType.EVOLVE)):
            ix = op.get("index"); cid = hand[ix]["id"] if ix is not None and ix < len(hand) else None
            rec["name"] = nm(cid) if cid is not None else None
            if ty == int(OptionType.PLAY) and cid is not None:
                sc = bot._play_score(cid, hand) if hasattr(bot, "_play_score") else None
                rec["score"] = sc
                if hasattr(bot, "explain_play"):
                    rec["reason"] = bot.explain_play(cid)
        elif ty == int(OptionType.ATTACK):
            rec["name"] = AN.get(op.get("attackId"))
            rec["damage"] = bot._dmg(parsed.select.options[i]) if hasattr(bot, "_dmg") else None
            oa = (cur["players"][1].get("active") or [None])[0]
            rec["ko"] = bool(oa and rec.get("damage") and rec["damage"] >= (oa.get("hp") or 9999))
        cands.append(rec)
    # 攻撃/プレイ以外で候補が大量(エネ選択等)なら要約のみ
    if len(cands) > 14 and not any(c.get("type") in ("ATTACK", "PLAY") for c in cands):
        cands = [c for c in cands if c["chosen"]]
    return {"select": str(rs.get("type")).split(".")[-1],
            "context": str(rs.get("context")).split(".")[-1], "candidates": cands}, ch


def run(games, me_stem, opp_stem):
    d = load(me_stem); opp_deck = load(opp_stem); out = []
    for game in range(games):
        bot = R.DECK_BOTS[me_stem](decklist=d); opp = R.DECK_BOTS[opp_stem]()
        obs, sd = battle_start(d, opp_deck); steps = 0; res = None; turns = []; lastturn = -1; cur_turn = None
        while obs is not None and steps < 1500:
            o = to_observation_class(obs); st = o.current; cur = obs.get("current")
            if st and st.result != -1:
                res = st.result; break
            rs = obs.get("select")
            if not rs or not rs.get("option"):
                break
            who = st.yourIndex if st else 0; parsed = Observation.from_dict(obs)
            if who == 0 and cur:
                t = cur.get("turn")
                if t != lastturn:
                    cur_turn = {"turn": t, "my_board": board(cur, 0), "opp_board": board(cur, 1), "decisions": []}
                    turns.append(cur_turn); lastturn = t
                rec, ch = decision_record(bot, parsed, cur, rs)
                cur_turn["decisions"].append(rec); ret = ch
            else:
                ret = opp.select(Observation.from_dict(obs))
            obs = battle_select(ret or [0]); steps += 1
        battle_finish()
        out.append({"game": game + 1, "me": me_stem, "opp": opp_stem,
                    "result": ("win" if res == 0 else "loss" if res == 1 else "unknown"), "turns": turns})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--me", default="deck"); ap.add_argument("--opp", default="dragapult")
    ap.add_argument("--games", type=int, default=3); ap.add_argument("--out", default="")
    a = ap.parse_args()
    data = run(a.games, a.me, a.opp)
    js = json.dumps(data, ensure_ascii=False, indent=1)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(js); print(f"wrote {a.out} ({len(js)} bytes, {len(data)} games)")
    else:
        print(js)
