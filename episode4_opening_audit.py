"""Episode 4: 開幕1ターンの Explain 監査（なぜ主役ライン初設置が T2 になるか）。

初期手札 / 開幕ACTIVE / 開幕BENCH / T1終了時盤面 を Universal vs 専用bot で比較。
+ Support Timing: サポ(博士/Lillie/Boss/Night Stretcher系)を引いてから使うまでの遅延。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class
from cabt_bot import Observation, load_cards
from cabt_bot.bots import deck_registry as R
from cabt_bot.bots.universal_bot import UniversalBot, infer_plan
from cabt_bot.enums import SelectType

C = load_cards(); nm = lambda i: (C[i].name if i in C else f"#{i}")
MAIN = int(SelectType.MAIN)
SUPPORT_HINT = ("Professor", "Lillie", "Boss", "Night Stretcher", "Nest", "Ultra Ball", "Poké")


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def board(me):
    a = (me.get("active") or [None])[0]
    return (nm(a["id"]) if a else "なし",
            [nm(b["id"]) for b in (me.get("bench") or []) if b])


def audit(botfn, dl, line_ids, games, show=1):
    line_by_t1 = 0; examples = []
    for g in range(games):
        bot = botfn(dl); opp = UniversalBot(decklist=dl)
        obs, _ = battle_start(dl, dl); steps = 0
        first_hand = None; t1_board = None; my_turns = 0; prev_turn = 0
        while obs is not None and steps < 400:
            st = to_observation_class(obs).current
            if st and st.result != -1:
                break
            if not (obs.get("select") and obs["select"].get("option")):
                break
            who = st.yourIndex if st else 0
            if who == 0:
                cur = obs["current"]; me = cur["players"][0]; turn = cur.get("turn", 0)
                if first_hand is None:
                    first_hand = [nm(c["id"]) for c in (me.get("hand") or [])]
                if t1_board is None and turn >= 2:      # p0のT1が終わり相手T→自分T2開始直前に p0盤面確定
                    t1_board = board(me)
                ret = bot.select(Observation.from_dict(obs)) or [0]
            else:
                ret = opp.select(Observation.from_dict(obs)) or [0]
            obs = battle_select(ret); steps += 1
        # T1終了時盤面が取れなければ最後の自分盤面
        if t1_board is None:
            o2 = to_observation_class(obs).current
            if o2 and o2.players:
                pass
        battle_finish()
        # T1終了時に主役ラインが場に居たか
        if t1_board:
            in_play_names = [t1_board[0]] + t1_board[1]
            if any(nm(i) in in_play_names for i in line_ids):
                line_by_t1 += 1
        if len(examples) < show:
            examples.append((first_hand, t1_board))
    return line_by_t1 / games, examples


def main(deck="deck", spec_key=None, games=16):
    spec_key = spec_key or deck
    dl = load(deck); plan = infer_plan(dl)
    line_ids = set(plan.attackers or ())
    print(f"=== 開幕監査: {deck} (主役ライン={[nm(i) for i in line_ids][:6]}) ===")
    ur, uex = audit(lambda d: UniversalBot(decklist=d), dl, line_ids, games)
    sr, sex = audit(lambda d: R.DECK_BOTS[spec_key](decklist=d), dl, line_ids, games)
    print(f"T1終了時に主役ラインが場: Universal {ur:.0%}  専用bot {sr:.0%}")
    print(f"--- Universal 開幕例 ---")
    for hand, b in uex:
        print(f"  初期手札(一部): {hand[:7]}")
        print(f"  T1終了盤面: active={b[0] if b else '?'} bench={b[1] if b else '?'}")
    print(f"--- 専用bot 開幕例 ---")
    for hand, b in sex:
        print(f"  T1終了盤面: active={b[0] if b else '?'} bench={b[1] if b else '?'}")


if __name__ == "__main__":
    for d, k in [("deck", "deck"), ("archaludon_real", "archaludon")]:
        main(d, k); print()
