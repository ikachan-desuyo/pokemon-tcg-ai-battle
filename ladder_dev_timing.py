"""人間レビューで発見した2パターンを、提出Bot(リプレイの実選択) vs 最新UniversalBot で同一局面比較。

① 壁交代: active=Cinderace(壁)から RETREAT して主軸前段を前に出す(先攻の攻撃不可ターン等)
② 後続育成不足: 現アタッカーが被KO圏 & ベンチに後続なし & 手札に育成手段あり なのに ATTACK/END

分類目的(修正なし): Universalも同じ→OS全体の課題(Episode5テーマ) / Universalは違う→提出Botへの移植漏れ。
"""
import json, os, sys, pathlib
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cabt_bot import Observation, load_cards
from cabt_bot.bots.universal_bot import UniversalBot
from cabt_bot.bots.deck_registry import MegaStarmiePlanBot
from cabt_bot.enums import SelectType, OptionType

C = load_cards(); nm = lambda i: (C[i].name if i in C else f"#{i}")
SC = pathlib.Path("/tmp/claude-0/-mnt-h-work-pokemon-tcg-ai-battle/2f724d4e-1596-4a25-8039-795c317c6f22/scratchpad")
MAIN = int(SelectType.MAIN)
OT = {int(getattr(OptionType, x)): x for x in dir(OptionType) if x.isupper()}
CIND = 666; STARYU = 1030; MEGA = 1031
DEV_CARDS = {1030, 1086}          # Staryu / Buddy-Buddy Poffin(たね2枚ベンチへ)


def desc(ch, me):
    t = OT.get(ch.get("type"), str(ch.get("type")))
    hand = me.get("hand") or []
    idx = ch.get("index")
    if idx is not None and 0 <= idx < len(hand) and ch.get("area") in (None, 2):
        return f"{t} {nm(hand[idx]['id'])}"
    return t


def main():
    dl = [int(x) for x in open("decks/deck.csv").read().split() if x.strip()]
    rows = json.load(open(SC / "ladder_rows.json"))
    losses = [r["ep"] for r in rows if r["arch"] in ("MegaLucario", "Archaludon") and not r["win"]]
    p1 = Counter(); p2 = Counter(); ex1 = []; ex2 = []
    for ep in losses:
        p = SC / "replays" / f"{ep}.json"
        if not p.exists():
            continue
        rj = json.load(open(p))
        d0 = rj["steps"][1][0]["action"]
        my = 0 if (d0 and MEGA in d0) else 1
        for t in range(2, len(rj["steps"]) - 1):
            ob = rj["steps"][t][my].get("observation") or {}
            cur = ob.get("current"); sel = ob.get("select")
            if not cur or not sel or sel.get("type") != MAIN:
                continue
            if cur.get("yourIndex") != my:
                continue
            act = rj["steps"][t + 1][my].get("action")   # off-by-one補正
            if not act:
                continue
            actual = act[0]
            if actual >= len(sel.get("option") or []):
                continue
            ch = sel["option"][actual]
            me = cur["players"][my]
            a = (me.get("active") or [None])[0]
            bench = [b for b in (me.get("bench") or []) if b]
            hand = me.get("hand") or []
            turn = cur.get("turn", 0)
            # --- ① 壁(Cinderace)active から RETREAT ---
            if a and a.get("id") == CIND and OT.get(ch.get("type")) == "RETREAT":
                uni = UniversalBot(decklist=dl)
                u = uni.select(Observation.from_dict(ob)) or [0]
                ud = desc(sel["option"][u[0]] if u[0] < len(sel["option"]) else {}, me)
                same = (OT.get(ch.get("type")) == ud.split()[0])
                p1["Universalも交代"] += int(same); p1["Universalは別行動"] += int(not same)
                if len(ex1) < 5:
                    ex1.append(f"ep{ep} T{turn}: 提出=RETREAT / Uni={ud} (bench:{[nm(b['id']) for b in bench]})")
            # --- ② 被KO圏active & 後続なし & 手札に育成手段 & 提出=ATTACK/END ---
            if a and a.get("id") in (MEGA, STARYU) and (a.get("hp") or 999) <= 220:
                has_successor = any(b.get("id") in (MEGA, STARYU) for b in bench)
                dev_in_hand = [c["id"] for c in hand if c.get("id") in DEV_CARDS]
                if (not has_successor) and dev_in_hand and OT.get(ch.get("type")) in ("ATTACK", "END"):
                    uni = UniversalBot(decklist=dl)
                    u = uni.select(Observation.from_dict(ob)) or [0]
                    ud = desc(sel["option"][u[0]] if u[0] < len(sel["option"]) else {}, me)
                    develops = ud.split()[0] in ("PLAY",) and any(nm(i) in ud for i in dev_in_hand)
                    p2["Universalは育成"] += int(develops)
                    p2["Universalも同型(攻撃/END等)"] += int(not develops)
                    if len(ex2) < 6:
                        ex2.append(f"ep{ep} T{turn}: 提出={OT.get(ch.get('type'))} / Uni={ud} "
                                   f"(act:{nm(a['id'])}hp{a.get('hp')} 手札育成:{[nm(i) for i in dev_in_hand]})")
    print("=== ① 壁(Cinderace)からのRETREAT局面 ===")
    print(dict(p1))
    for e in ex1:
        print("  ", e)
    print("\n=== ② 被KO圏&後続なし&育成手段ありでATTACK/ENDした局面 ===")
    print(dict(p2))
    for e in ex2:
        print("  ", e)


if __name__ == "__main__":
    main()
