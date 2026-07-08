"""③ 競り負け14試合のみ: 実ラダー局面(T3-8)の自分の実決定に evaluate_decision/DecisionDiff を流す。
目的=敗因の分類(genuine gap抽出)。修正はしない。Override=誤りではない(過去の教訓)ため、
「カーネル最善と実選択の食い違い」を頻度パターンとして集計し、レビュー材料にする。
"""
import json, os, sys, pathlib
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cabt_bot import load_cards
from cabt_bot.bots.deck_registry import MegaStarmiePlanBot
from cabt_bot.enums import SelectType, OptionType

C = load_cards(); nm = lambda i: (C[i].name if i in C else f"#{i}")
SC = pathlib.Path("/tmp/claude-0/-mnt-h-work-pokemon-tcg-ai-battle/2f724d4e-1596-4a25-8039-795c317c6f22/scratchpad")
MAIN = int(SelectType.MAIN)
OT = {int(getattr(OptionType, x)): x for x in dir(OptionType) if x.isupper()}
KESHI = [83262979, 83213123, 83096014, 83051917, 83010238, 82919151, 82775247, 82707533,
         82677665, 82672851, 83220098, 83201681, 83135156, 83116603]   # 競り負け(2-4)


def desc(ch, me):
    t = OT.get(ch.get("type"), str(ch.get("type")))
    hand = me.get("hand") or []
    idx = ch.get("index")
    if idx is not None and 0 <= idx < len(hand) and ch.get("area") in (None, 2):
        return f"{t} {nm(hand[idx]['id'])}"
    if t == "ATTACK":
        return f"ATTACK#{ch.get('attackId')}"
    return t


def main():
    dl = [int(x) for x in open("decks/deck.csv").read().split() if x.strip()]
    bot = MegaStarmiePlanBot(decklist=dl)
    pat = Counter(); drivers = Counter(); examples = []
    n_states = 0; n_div = 0
    for ep in KESHI:
        rj = json.load(open(SC / "replays" / f"{ep}.json"))
        d0 = rj["steps"][1][0]["action"]
        my = 0 if (d0 and 1031 in d0) else 1
        used = 0
        for t in range(2, len(rj["steps"])):
            if used >= 3:
                break
            ag = rj["steps"][t][my]
            ob = ag.get("observation") or {}
            cur = ob.get("current"); sel = ob.get("select")
            if not cur or not sel or sel.get("type") != MAIN:
                continue
            turn = cur.get("turn", 0)
            if not (3 <= turn <= 8) or len(sel.get("option") or []) < 3:
                continue
            if not ob.get("search_begin_input"):
                continue
            act = ag.get("action")
            actual = act[0] if isinstance(act, list) and act else 0
            me = cur["players"][cur.get("yourIndex", my)]
            cands = list(range(min(len(sel["option"]), 6)))
            trs = {}
            for i in cands:
                tr = bot.evaluate_decision(ob, i, root_player=cur.get("yourIndex", my), seed=7)
                if tr:
                    trs[i] = tr
            if len(trs) < 2 or actual not in trs:
                continue
            n_states += 1; used += 1
            best = max(trs, key=lambda i: trs[i]["position"])
            regret = trs[best]["position"] - trs[actual]["position"]
            if best != actual and regret >= 40:
                n_div += 1
                dd = bot.decision_diff(trs[best], trs[actual])
                ad = desc(sel["option"][actual], me); bd = desc(sel["option"][best], me)
                pat[f"実:{ad.split()[0]} → 最善:{bd.split()[0]}"] += 1
                for k in ("prize_delta", "threat_delta", "development_delta"):
                    if abs(dd.get(k, 0)) >= 1:
                        drivers[k] += 1
                if len(examples) < 10:
                    examples.append(f"ep{ep} T{turn}: 実{ad} → 最善{bd} (regret+{regret:.0f} diff={dd})")
    print(f"検査局面 {n_states} / regret40+の食い違い {n_div}")
    print("\nパターン:")
    for p, n in pat.most_common(10):
        print(f"  x{n} {p}")
    print("\nDecisionDiff駆動要因:", dict(drivers))
    print("\n例:")
    for e in examples:
        print(f"  {e}")


if __name__ == "__main__":
    main()
