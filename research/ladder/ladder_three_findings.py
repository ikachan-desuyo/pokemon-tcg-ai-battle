"""人間レビュー3指摘のExplain-first分類(修正禁止)。全リプレイ走査で頻度→カーネルregret→Universal比較。

① リーリエ不使用END: active=Mega(0E)・手札にリーリエ(1227)・水(3)/イグニ(17)/トウコ(1225)無し → END
② トウコ→イグニ取得: 相手activeHP<=120(Jetting1エネ圏)なのにトウコ(1225)後の山→手札が17(イグニ)
③ Boss勝ち逃し: 残りサイド1・手札にボス(1182)・相手ベンチにKO圏 → Boss不使用でATTACK/END
"""
import json, os, sys, pathlib
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cabt_bot import Observation, load_cards
from cabt_bot.bots.deck_registry import MegaStarmiePlanBot
from cabt_bot.bots.universal_bot import UniversalBot
from cabt_bot.enums import SelectType, OptionType

C = load_cards(); nm = lambda i: (C[i].name if i in C else f"#{i}")
SC = pathlib.Path("/tmp/claude-0/-mnt-h-work-pokemon-tcg-ai-battle/2f724d4e-1596-4a25-8039-795c317c6f22/scratchpad")
MAIN = int(SelectType.MAIN)
OT = {int(getattr(OptionType, x)): x for x in dir(OptionType) if x.isupper()}
MEGA, LILLIE, TOUKO, BOSS, IGN, WATER = 1031, 1227, 1225, 1182, 17, 3


def hand_ids(me):
    return [c.get("id") for c in (me.get("hand") or [])]


def my_attack_dmg(a):
    e = len(a.get("energyCards") or []) if a else 0
    return 210 if e >= 3 else (120 if e >= 1 else 0)


def main():
    dl = [int(x) for x in open("decks/deck.csv").read().split() if x.strip()]
    rows = json.load(open(SC / "ladder_rows.json"))
    ship = MegaStarmiePlanBot(decklist=dl)
    f1 = []; f2 = Counter(); f2ex = []; f3 = []
    for r in rows:
        p = SC / "replays" / f"{r['ep']}.json"
        if not p.exists():
            continue
        rj = json.load(open(p))
        d0 = rj["steps"][1][0]["action"]
        my = 0 if (d0 and MEGA in d0) else 1
        steps = rj["steps"]
        touko_pending = None
        seen_fetch = set()
        for t in range(2, len(steps) - 1):
            ob = steps[t][my].get("observation") or {}
            cur = ob.get("current"); sel = ob.get("select")
            if not cur:
                continue
            # ② の fetch 検出(ログ: 山→手札 with serial, トウコ直後)
            if touko_pending is not None:
                for lg in (ob.get("logs") or []):
                    if (lg.get("type") == 6 and lg.get("fromArea") == 1 and lg.get("toArea") == 2
                            and lg.get("playerIndex") == my and lg.get("serial") is not None
                            and lg.get("serial") not in seen_fetch):
                        seen_fetch.add(lg.get("serial"))
                        cid = lg.get("cardId")
                        if cid in (IGN, WATER):
                            lethal1e, ep_, turn_ = touko_pending
                            key = f"{'イグニ取得' if cid == IGN else '水取得'}|1エネ圏{'○' if lethal1e else '×'}"
                            f2[key] += 1
                            if cid == IGN and lethal1e and len(f2ex) < 4:
                                f2ex.append(f"ep{ep_} T{turn_}")
                            touko_pending = None
                            break
            if not sel or sel.get("type") != MAIN or cur.get("yourIndex") != my:
                continue
            act = steps[t + 1][my].get("action")
            if not act or act[0] >= len(sel.get("option") or []):
                continue
            ch = sel["option"][act[0]]
            me = cur["players"][my]; opp = cur["players"][1 - my]
            h = hand_ids(me)
            a = (me.get("active") or [None])[0]
            ct = OT.get(ch.get("type"))
            # ② トウコをPLAYした瞬間を記録
            if ct == "PLAY" and ch.get("index") is not None and ch["index"] < len(h) and h[ch["index"]] == TOUKO:
                oa = (opp.get("active") or [None])[0]
                lethal1e = bool(oa) and (oa.get("hp") or 999) <= 120
                touko_pending = (lethal1e, r["ep"], cur.get("turn"))
            # ① リーリエ不使用END
            if (ct == "END" and a and a.get("id") == MEGA and not (a.get("energyCards") or [])
                    and LILLIE in h and WATER not in h and IGN not in h and TOUKO not in h):
                f1.append((r["ep"], cur.get("turn"), ob))
            # ③ Boss勝ち逃し
            if ct in ("ATTACK", "END") and len(me.get("prize") or []) == 1 and BOSS in h:
                dmg = my_attack_dmg(a)
                bench_ko = any(b and (b.get("hp") or 999) <= dmg for b in (opp.get("bench") or []))
                oa = (opp.get("active") or [None])[0]
                act_ko = bool(oa) and (oa.get("hp") or 999) <= dmg
                if bench_ko and not act_ko:      # activeでは勝てないがベンチなら勝てた
                    f3.append((r["ep"], cur.get("turn"), ob, dmg))
    print(f"=== 頻度(全{len(rows)}試合走査) ===")
    print(f"① リーリエ不使用END(該当局面): {len(f1)}件  例:{[(e, t) for e, t, _ in f1[:5]]}")
    print(f"② トウコ取得先: {dict(f2)}  イグニ取得&1エネ圏の例:{f2ex}")
    print(f"③ Boss勝ち逃し(ベンチで勝てたのに): {len(f3)}件  例:{[(e, t) for e, t, _, _ in f3[:5]]}")
    # カーネル&Universal比較(各カテゴリ最大4局面)
    for label, states in (("①", f1[:4]), ("③", [(e, t, o) for e, t, o, _ in f3[:4]])):
        for ep_, turn_, ob in states:
            sel = ob.get("select"); me = ob["current"]["players"][ob["current"]["yourIndex"]]
            if not ob.get("search_begin_input"):
                print(f"{label} ep{ep_} T{turn_}: search不可(スキップ)"); continue
            trs = {}
            for i in range(min(len(sel["option"]), 8)):
                tr = ship.evaluate_decision(ob, i, root_player=ob["current"]["yourIndex"], seed=7)
                if tr:
                    trs[i] = tr
            if not trs:
                continue
            best = max(trs, key=lambda i: trs[i]["position"])
            h = hand_ids(me)
            def d_(i):
                c = sel["option"][i]; tt = OT.get(c.get("type"))
                idx = c.get("index")
                card = nm(h[idx]) if (idx is not None and idx < len(h) and c.get("area") in (None, 2)) else ""
                return f"{tt} {card}".strip()
            uni = UniversalBot(decklist=dl)
            u = uni.select(Observation.from_dict(ob)) or [0]
            print(f"{label} ep{ep_} T{turn_}: カーネル最善={d_(best)}(pos{trs[best]['position']:.0f}) "
                  f"| 候補regret={[(d_(i), round(trs[best]['position']-trs[i]['position'])) for i in trs]} "
                  f"| Universal={d_(u[0]) if u[0] < len(sel['option']) else '?'}")


if __name__ == "__main__":
    main()
