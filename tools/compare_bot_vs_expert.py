"""現状のArchaludonBotと1位(ShumpeiNomura)の実プレイを、同一局面で比較して差異を洗い出す。

1位リプレイの各意思決定(状態+合法手+本人の選択)に対し、その状態をそのままbotに食わせて
『同じ局面でbotが何を選ぶか』を求め、本人の選択と一致/相違を集計する。相違は状況(ターン・
先行後攻・手札・盤面・選択肢)付きで記録し、系統的な差を分析する。

実行: python tools/compare_bot_vs_expert.py
"""
import sys, os, json, glob
sys.path.insert(0, ".")
from collections import Counter, defaultdict
from cabt_bot import Observation, load_cards
from cabt_bot.enums import OptionType, SelectType
from cabt_bot.bots.deck_registry import ArchaludonBot
from cabt_bot.imitation import resolve
try:
    from cg.api import all_attack
    AN = {a.attackId: a.name for a in all_attack()}
except Exception:
    AN = {}

C = load_cards(); nm = lambda c: C[c].name if c in C else f"#{c}"
PLAYER = "ShumpeiNomura"
OT = {int(getattr(OptionType, x)): x for x in ("PLAY", "ATTACH", "EVOLVE", "ABILITY",
      "RETREAT", "ATTACK", "END", "CARD", "YES", "NO", "NUMBER", "ENERGY")}
REAL_DECK = [int(x) for x in open("decks/archaludon_real.csv").read().split() if x.strip()]


def describe(op_dict, cur, me):
    r = resolve(op_dict, cur, me)
    t = r["otype"]; name = OT.get(t, str(t))
    if t in (7, 9, 8) and r["card_id"]:
        s = f"{name}:{nm(r['card_id'])}"
        if r["target_id"]:
            s += f"→{nm(r['target_id'])}"
        return s
    if t == 13:
        return f"ATTACK:{AN.get(r['attack_id'], r['attack_id'])}"
    if t in (3, 4, 5) and r["card_id"]:
        return f"CARD:{nm(r['card_id'])}"
    return name


def run():
    files = sorted(glob.glob("input_data/archaludon/*.json"))
    total = same = 0
    diff_by_stype = Counter()
    diff_examples = defaultdict(list)   # カテゴリ -> [状況]
    action_diff = Counter()             # (本人の行動種別 -> botの行動種別)
    for f in files:
        d = json.load(open(f))
        ag = [a.get("Name") for a in d.get("info", {}).get("Agents", [])]
        if PLAYER not in ag:
            continue
        me = ag.index(PLAYER)
        bot = ArchaludonBot(decklist=REAL_DECK)
        for st in d["steps"]:
            if me >= len(st) or st[me].get("status") != "ACTIVE":
                continue
            obs_d = st[me]["observation"]; sel = obs_d.get("select"); cur = obs_d.get("current")
            act = st[me].get("action")
            if not (sel and sel.get("option") and cur and isinstance(act, list)):
                continue
            stype = sel.get("type")
            if stype == 9 and any(a > 2 for a in act):   # 初期デッキ提出等は除外
                continue
            opts = sel["option"]
            expert = sorted(i for i in act if i < len(opts))
            if not expert:
                continue
            try:
                bot_choice = sorted(bot.select(Observation.from_dict(obs_d)) or [])
            except Exception:
                continue
            total += 1
            if bot_choice == expert:
                same += 1
                continue
            diff_by_stype[stype] += 1
            # 本人とbotの行動を記述
            exp_desc = describe(opts[expert[0]], cur, me) if expert[0] < len(opts) else "?"
            bot_desc = describe(opts[bot_choice[0]], cur, me) if (bot_choice and bot_choice[0] < len(opts)) else "END/なし"
            exp_t = OT.get(opts[expert[0]].get("type"), "?") if expert[0] < len(opts) else "?"
            bot_t = OT.get(opts[bot_choice[0]].get("type"), "?") if (bot_choice and bot_choice[0] < len(opts)) else "END"
            action_diff[(exp_t, bot_t)] += 1
            # 状況
            p = cur["players"][me]; opp = cur["players"][1 - me]
            act_sp = (p.get("active") or [None])[0]
            ctx = {
                "turn": cur.get("turn"), "先攻": (me == cur.get("firstPlayer")),
                "手札": [nm(c.get("id")) for c in (p.get("hand") or [])][:8],
                "自active": (nm(act_sp["id"]) + f"(HP{act_sp.get('hp')})" if act_sp else "なし"),
                "自ベンチ数": len([b for b in (p.get("bench") or []) if b]),
                "相手active": (nm((opp.get("active") or [{}])[0].get("id")) if (opp.get("active") and opp["active"][0]) else "なし"),
                "本人": exp_desc, "bot": bot_desc,
            }
            cat = f"{exp_t}→{bot_t}"
            diff_examples[cat].append(ctx)
    return total, same, diff_by_stype, action_diff, diff_examples


def main():
    total, same, diff_by_stype, action_diff, diff_examples = run()
    STN = {0: "MAIN", 1: "CARD", 4: "ENERGY", 6: "SKILL", 8: "COUNT", 9: "YESNO"}
    print(f"比較した意思決定: {total} / 一致 {same} ({same/total:.1%}) / 相違 {total-same}")
    print("\n■ 選択種別ごとの相違数:")
    for st, n in diff_by_stype.most_common():
        print(f"  {STN.get(st, st)}: {n}")
    print("\n■ 『本人の行動 → botの行動』の相違(頻度上位)＝系統的な差:")
    for (e, b), n in action_diff.most_common(12):
        print(f"  {n:4d}  本人={e:8s} → bot={b}")
    print("\n■ カテゴリ別の代表状況(各3件):")
    for cat, n in sorted(diff_examples.items(), key=lambda kv: -len(kv[1]))[:6]:
        print(f"\n--- {cat} ({len(diff_examples[cat])}件) ---")
        for ex in diff_examples[cat][:3]:
            print(f"  T{ex['turn']} {'先攻' if ex['先攻'] else '後攻'} 自{ex['自active']} ベンチ{ex['自ベンチ数']} 相手{ex['相手active']}")
            print(f"     手札{ex['手札']}")
            print(f"     本人={ex['本人']} / bot={ex['bot']}")
    os.makedirs("out", exist_ok=True)
    json.dump({k: v for k, v in diff_examples.items()}, open("out/bot_vs_expert_diffs.json", "w", encoding="utf-8"), ensure_ascii=False)
    print("\n→ 全相違を out/bot_vs_expert_diffs.json に保存")


if __name__ == "__main__":
    main()
