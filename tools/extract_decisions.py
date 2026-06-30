"""1位ブリジュラス(ShumpeiNomura)のリプレイから意思決定を抽出し、行動クローン用データ＋思考解析を出力。

各リプレイで本人がACTIVEな選択を、選んだ選択肢(action)を『カード/技/対象』に解決して記録。
- 解析: 選択種別の分布、使用カード頻度、攻撃選択、ターン別の動き＝『同じ思考』の中身。
- 学習データ: 各決定の全選択肢を特徴量化し、chosen=1/0 のラベル付きで out/archaludon_decisions.json に保存。

実行: python tools/extract_decisions.py
"""
import sys, os, json, glob
sys.path.insert(0, ".")
from collections import Counter
from cabt_bot import load_cards
from cabt_bot.state_encoder import caps
from cabt_bot.imitation import resolve as _resolve, board_ctx as _board_ctx
try:
    from cg.api import all_attack
    ATKNAME = {a.attackId: a.name for a in all_attack()}
    ATKDMG = {a.attackId: (getattr(a, "damage", 0) or 0) for a in all_attack()}
except Exception:
    ATKNAME, ATKDMG = {}, {}

C = load_cards()
nm = lambda c: (C[c].name if c in C else f"#{c}")
PLAYER = "ShumpeiNomura"

# OptionType: 0 NUMBER,1 YES,2 NO,3 CARD,4 TOOL_CARD,5 ENERGY_CARD,6 ENERGY,7 PLAY,8 ATTACH,
#             9 EVOLVE,10 ABILITY,11 DISCARD,12 RETREAT,13 ATTACK,14 END,15 SKILL,16 SPECIAL_CONDITION
OTYPE = {0: "NUMBER", 1: "YES", 2: "NO", 3: "CARD", 4: "TOOL_CARD", 5: "ENERGY_CARD", 6: "ENERGY",
         7: "PLAY", 8: "ATTACH", 9: "EVOLVE", 10: "ABILITY", 11: "DISCARD", 12: "RETREAT",
         13: "ATTACK", 14: "END", 15: "SKILL", 16: "SPECIAL_CONDITION"}


def _spot_at(player, area, index):
    if area == 4:   # ACTIVE
        spots = player.get("active") or []
    elif area == 5:  # BENCH
        spots = player.get("bench") or []
    elif area == 2:  # HAND
        spots = player.get("hand") or []
    else:
        return None
    if index is not None and 0 <= index < len(spots) and spots[index]:
        sp = spots[index]
        return sp.get("id") if isinstance(sp, dict) else sp
    return None


def resolve(op, cur, me):
    """選択肢を意味(カードid/対象id/技)に解決。"""
    t = op.get("type")
    p = cur["players"][me]
    out = {"otype": t, "card_id": None, "target_id": None, "attack_id": None, "damage": 0}
    if t in (3, 4, 5):           # CARD系: area/index/playerIndex のカード
        pl = cur["players"][op.get("playerIndex", me)]
        out["card_id"] = _spot_at(pl, op.get("area"), op.get("index"))
    elif t == 7:                 # PLAY: 手札のindex
        out["card_id"] = _spot_at(p, 2, op.get("index"))
    elif t in (8, 9, 10):        # ATTACH/EVOLVE/ABILITY: 手札カード + 場の対象
        out["card_id"] = _spot_at(p, op.get("area", 2), op.get("index"))
        out["target_id"] = _spot_at(p, op.get("inPlayArea"), op.get("inPlayIndex"))
    elif t == 12:                # RETREAT
        out["card_id"] = _spot_at(p, 4, 0)
    elif t == 13:                # ATTACK
        aid = op.get("attackId") or op.get("skillId")
        out["attack_id"] = aid
        out["damage"] = ATKDMG.get(aid, 0)
        out["card_id"] = _spot_at(p, 4, 0)
    return out


def board_ctx(cur, me):
    p = cur["players"][me]; o = cur["players"][1 - me]
    act = (p.get("active") or [None])[0]
    return {
        "turn": cur.get("turn", 0),
        "my_prizes": len(p.get("prize") or []),
        "opp_prizes": len(o.get("prize") or []),
        "my_bench": len([b for b in (p.get("bench") or []) if b]),
        "my_hand": p.get("handCount", len(p.get("hand") or [])),
        "my_active": (act.get("id") if act else None),
        "opp_active": ((o.get("active") or [None])[0] or {}).get("id"),
    }


def run():
    files = sorted(glob.glob("input_data/archaludon/*.json"))
    decisions = []
    for f in files:
        d = json.load(open(f))
        ag = [a.get("Name") for a in d.get("info", {}).get("Agents", [])]
        if PLAYER not in ag:
            continue
        me = ag.index(PLAYER)
        for st in d["steps"]:
            if me >= len(st) or st[me].get("status") != "ACTIVE":
                continue
            obs = st[me]["observation"]; sel = obs.get("select"); cur = obs.get("current")
            act = st[me].get("action")
            if not (sel and sel.get("option") and cur):
                continue
            stype = sel.get("type")
            chosen = set(act) if isinstance(act, list) else set()
            # MAIN/CARD/ATTACK 等の選択のみ(初期デッキ提出=巨大actionは除外)
            if stype == 9 and any(a > 2 for a in chosen):   # setup keep(YES_NO)でactionがデッキ → skip
                continue
            opts = []
            for op in sel["option"]:
                r = _resolve(op, cur, me)
                if r.get("attack_id"):
                    r["damage"] = ATKDMG.get(r["attack_id"], 0)
                opts.append(r)
            decisions.append({
                "file": os.path.basename(f), "stype": stype, "context": sel.get("context"),
                "ctx": _board_ctx(cur, me),
                "options": opts,
                "chosen": sorted(i for i in chosen if i < len(opts)),
            })
    os.makedirs("out", exist_ok=True)
    json.dump(decisions, open("out/archaludon_decisions.json", "w", encoding="utf-8"), ensure_ascii=False)
    return decisions


def analyze(decisions):
    print(f"総意思決定数: {len(decisions)} (全{len(set(x['file'] for x in decisions))}戦)")
    st = Counter(x["stype"] for x in decisions)
    print("選択種別:", {f"{k}({['MAIN','CARD','ATTACHED','C/A','ENERGY','SKILL','ATTACK','EVOLVE','COUNT','YESNO','SPCOND'][k] if k<11 else k})": v for k, v in sorted(st.items())})
    # MAINで選んだ行動(otype)分布
    main_act = Counter()
    play_cards = Counter()
    attacks = Counter()
    for x in decisions:
        for i in x["chosen"]:
            if i >= len(x["options"]):
                continue
            op = x["options"][i]; t = op["otype"]
            main_act[OTYPE.get(t, t)] += 1
            if t in (7, 9) and op["card_id"]:
                play_cards[nm(op["card_id"])] += 1
            if t == 13 and op["attack_id"]:
                attacks[ATKNAME.get(op["attack_id"], op["attack_id"])] += 1
    print("\n選んだ行動の種別:", dict(main_act.most_common()))
    print("\nプレイ/進化したカード(頻度):")
    for c, n in play_cards.most_common(15):
        print(f"  {n:4d}  {c}")
    print("\n攻撃の選択(頻度):")
    for a, n in attacks.most_common():
        print(f"  {n:4d}  {a}")


if __name__ == "__main__":
    ds = run()
    analyze(ds)
