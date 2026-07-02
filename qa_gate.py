"""提出前QAゲート: ローカル対戦をReplayReviewerの検出器にかけ、Known問題が残っていれば提出不可。

運用ルール(2026-07-03確定):
  「人間が1試合見れば気付く問題」は、提出前にReplayReviewerが検出できなければならない。
  Kaggleは未知の問題を発見する場所であって、既知の問題を見つける場所ではない。

フロー: ローカル20-50試合(ミラー+実ラダー復元ベンチ) → 検出器 → BLOCKING署名が1件でもあれば FAIL。
"""
import sys, os
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cabt_bot.arena import run_match
from cabt_bot import Observation
from cabt_bot.bots import deck_registry as R
import replay_reviewer as RR

# 提出ブロック対象(=直すまで提出しない Known 問題)。それ以外はレポートのみ(Fact)。
BLOCKING_PREFIXES = [
    "ValuelessSupportPlay",                                  # 無価値サポでサポ権消費
    "MissedLethal",                                          # 勝ち筋逃し
    "WallRetreat",                                           # 逃げ0壁の無意味な交代
    "LastStand|単騎×被KO×非致死|リーリエ手札あり",              # 確定敗北圏でドローサポ未活用
]


def play_and_record(mk_me, mk_opp, deck_me, deck_opp, label):
    """ローカル1試合を実行し、ReplayReviewer互換のgame dictへ(自分=agent0)。"""
    me_bot = mk_me(); opp_bot = mk_opp()
    decisions = []
    step_i = [0]

    def me_agent(obs_dict):
        sel = me_bot.select(Observation.from_dict(obs_dict)) or [0]
        if obs_dict.get("current"):
            decisions.append((step_i[0], obs_dict, list(sel)))
        step_i[0] += 1
        return sel

    def opp_agent(obs_dict):
        step_i[0] += 1
        return opp_bot.select(Observation.from_dict(obs_dict)) or [0]

    run_match(me_agent, opp_agent, deck_me, deck_opp)
    return {"ep": label, "my": 0, "decisions": decisions}


def qa(games_per_matchup=10):
    dl = [int(x) for x in open("decks/deck.csv").read().split() if x.strip()]
    matchups = [
        ("mirror", "deck", "deck"),
        ("lucario", "ladder_lucario", "ladder_lucario"),
        ("arch", "ladder_archaludon", "ladder_archaludon"),
    ]
    counts = Counter(); reps = defaultdict(list)

    def sig(key, ep, turn):
        counts[key] += 1
        if len(reps[key]) < 3:
            reps[key].append(f"{ep}:T{turn}")
    n = 0
    for tag, opp_key, opp_deck in matchups:
        od = [int(x) for x in open(f"decks/{opp_deck}.csv").read().split() if x.strip()]
        for g_i in range(games_per_matchup):
            game = play_and_record(
                lambda: R.DECK_BOTS["deck"](decklist=dl),
                lambda: R.DECK_BOTS[opp_key](decklist=od),
                dl, od, f"local-{tag}-{g_i}")
            n += 1
            for det in RR.DETECTORS:
                det(game, sig)
    print(f"=== 提出前QAゲート: ローカル{n}試合 ===")
    blocking = []
    for key, c in counts.most_common():
        is_block = any(key.startswith(p) for p in BLOCKING_PREFIXES)
        mark = " ❌BLOCKING" if is_block else ""
        print(f"  {key:<58}{c:>4}  {','.join(reps[key])}{mark}")
        if is_block:
            blocking.append((key, c))
    print()
    if blocking:
        print(f"判定: ❌ FAIL — Known問題 {sum(c for _, c in blocking)}件が残存。修正するまで提出不可。")
        return 1
    print("判定: ✅ PASS — Known問題0件。提出可。")
    return 0


if __name__ == "__main__":
    sys.exit(qa())
