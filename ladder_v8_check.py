"""v8 Runtime Fix 発火確認(勝率は見ない): line_threat依存の行動が実戦で動き始めたか。

比較: v7(データ欠落=line_threat0) vs v8(データ同梱)。
  A. derank発火: 死亡濃厚activeへの「解放なし」エネ注ぎ(v7で6/38) → v8ではbenchへ回るはず
  B. スプレッド標的: Jetting Blowのベンチ50ダメの対象が「大型ライン(line_threat>=180)の進化前」を
     狙えているか(ダメージログ type16 value=-50 から対象を抽出)
"""
import json, os, sys, pathlib
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from replay_reviewer import load_game, my_view, chosen, MAIN, ATTACH, hand_ids
from cabt_bot.state_encoder import line_threat
from cabt_bot import load_cards
C = load_cards(); nm = lambda i: (C[i].name if i in C else f"#{i}")
SC = pathlib.Path("/tmp/claude-0/-mnt-h-work-pokemon-tcg-ai-battle/2f724d4e-1596-4a25-8039-795c317c6f22/scratchpad")
MEGA, STARYU, IGN = 1031, 1030, 17


def doomed_no_unlock(eps):
    """死亡濃厚active × 解放なしエネ注ぎ: act行き vs bench行き。"""
    act_n = bench_n = 0
    for ep in eps:
        g = load_game(ep)
        if not g:
            continue
        for t, ob, a in g["decisions"]:
            cur, me, opp = my_view(ob, g["my"])
            sel, ch = chosen(ob, a)
            if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
                continue
            if ch.get("type") != ATTACH:
                continue
            av = (me.get("active") or [None])[0]; oa = (opp.get("active") or [None])[0]
            if not av or not oa:
                continue
            dmg = line_threat(oa.get("id")) or 0
            mc = C.get(av.get("id")); oc = C.get(oa.get("id"))
            if mc and oc and mc.weakness and oc.type == mc.weakness:
                dmg *= 2
            if (av.get("hp") or 999) > dmg:
                continue
            if not any(b and b.get("id") in (MEGA, STARYU) for b in (me.get("bench") or [])):
                continue
            h = hand_ids(me)
            idx = ch.get("index")
            eid = h[idx] if (idx is not None and idx < len(h)) else None
            prov = 3 if eid == IGN else 1
            cur_e = len(av.get("energyCards") or []) if ch.get("inPlayArea") == 4 else \
                    len(((me.get("bench") or [None]*5)[ch.get("inPlayIndex", 0)] or {}).get("energyCards") or [])
            # 「activeに注いだ場合に解放があるか」はactive基準で判定
            act_e = len(av.get("energyCards") or [])
            info = C.get(av.get("id")); best_now = 0; best_unl = 0
            for mv in (info.moves if info else ()):
                if (mv.name or "").startswith("[Ability]") or mv.cost is None:
                    continue
                cost = mv.cost.count("{") + mv.cost.count("●")
                try:
                    d_ = int(str(mv.damage or "0").rstrip("+×x"))
                except ValueError:
                    d_ = 0
                if cost <= act_e:
                    best_now = max(best_now, d_)
                elif cost <= act_e + prov:
                    best_unl = max(best_unl, d_)
            if best_unl > best_now:
                continue                      # 解放あり=正当な注ぎは対象外
            if ch.get("inPlayArea") == 4:
                act_n += 1
            elif ch.get("inPlayArea") == 5:
                bench_n += 1
    return act_n, bench_n


def spread_targets(eps):
    """Jetting等のベンチ-50ダメ対象の質: 大型ライン(line_threat>=180)の進化前を狙えた割合。
    ダメージログ(type16, value=-50, 相手側)から対象を抽出。"""
    hit = Counter()
    for ep in eps:
        g = load_game(ep)
        if not g:
            continue
        seen = set()
        for t, ob, a in g["decisions"]:
            for lg in (ob.get("logs") or []):
                if (lg.get("type") == 16 and lg.get("value") == -50
                        and lg.get("playerIndex") == 1 - g["my"] and lg.get("serial") is not None):
                    key = (lg.get("serial"), lg.get("cardId"))
                    if key in seen:
                        continue
                    seen.add(key)
                    tid = lg.get("cardId")
                    big = (line_threat(tid) or 0) >= 180
                    hit["大型ライン狙い" if big else "小物"] += 1
    return hit


def main():
    rows = json.load(open(SC / "ladder_rows.json"))
    v7 = [r["ep"] for r in rows if r["tag"] == "v7"]
    v8 = [r["ep"] for r in rows if r["tag"] == "v8"]
    print(f"母数: v7={len(v7)}試合  v8={len(v8)}試合")
    a7, b7 = doomed_no_unlock(v7); a8, b8 = doomed_no_unlock(v8)
    print(f"\nA. 死亡濃厚×解放なしエネ注ぎ(derank発火確認)")
    print(f"   v7: act {a7} / bench {b7}   → v8: act {a8} / bench {b8}")
    s7 = spread_targets(v7); s8 = spread_targets(v8)
    print(f"\nB. ベンチ50ダメの対象の質(スプレッド標的)")
    print(f"   v7: {dict(s7)}   → v8: {dict(s8)}")


if __name__ == "__main__":
    main()
