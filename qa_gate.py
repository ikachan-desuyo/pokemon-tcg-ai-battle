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
# 相手ベンチマークbot側の検出もブロック対象(ベンチマーク健全性が崩れると全測定が信用できない)。
BLOCKING_PREFIXES = [
    "ValuelessSupportPlay",                                  # 無価値サポでサポ権消費
    "MissedLethal",                                          # 勝ち筋逃し
    "WallRetreat",                                           # 逃げ0壁の無意味な交代
    "LastStand|単騎×被KO×非致死|リーリエ打てたのに未使用",       # 確定敗北圏でドローサポ未活用(選択肢実在時のみ)
    "DeadMoveAttack",                                        # 条件未成立の0ダメ技で攻撃(人間レビュー2巡目)
    "SpreadSkew",                                            # 撒き先が主力線進化前を外す(人間レビュー2巡目)
    "PartnerUnbenched",                                      # 依存技の相方を出さず手番終了(同上・現0件)
    "MissedFreeAdvance",                                     # 逃げ0壁でEND=攻撃機会喪失(人間レビュー3巡目)
    "DoomedNoSwitch",                                        # 被KO圏の攻撃役を温存せず喪失(人間レビュー3巡目)
    "BossNoPathGain",                                        # 勝ち筋を早めない1枚取りボス(人間レビュー4巡目)
    "VolatileOverPermanent",                                 # 恒久エネ完成を捨ててイグニ貼付(人間レビュー4巡目)
    "HealMissed",                                            # 重傷activeで回復サポより低価値サポ(人間レビュー5巡目)
    "CapeSkew",                                              # ケープの貼り先が生存反転を逃す(人間レビュー5巡目)
    "EnergyStuckNoLillie",                                   # エネ不足×手札エネ0×リーリエ未使用(人間レビュー5巡目)
    "SetupSkew",                                             # 開幕activeに進化土台(人間レビュー6巡目)
    "DeadEvolutionPick",                                     # 進化元不在の進化ポケをサーチ(人間レビュー6巡目)
    "LillieOverLiveHeal",                                    # 生きた状況札をリーリエで流す(人間レビュー6巡目)
    "DoomedNoRetreat",                                       # 被KO確定×不利トレードで残留(人間レビュー6巡目)
    "GustTargetSkew",                                        # 引き出し先がKO×サイド最大でない(人間レビュー7巡目)
    "PromotionSkew",                                         # 昇格が耐える主力を選ばない(人間レビュー7巡目)
    "WeakAdvance",
    "BasicUnbenched",
    "EvolveTriggerBeforeDevelop",
    "SpreadIntoImmune",
    "BenchHealMissed",
    "EnergyTypeSkew",
    "DoomedGameLoss",                             # 死んだら負けのactive放置(退避可)(自己レビューarch-7)                             # 未充足コストを進めないエネ選択(10巡目: R+P二色でR重ね)                            # 展開前に進化トリガー消費(9巡目)                                        # 単騎でたね在手なのに未展開(8巡目)                                           # 耐える壁を退き脆いたねを前進(人間レビュー7巡目)
]


def play_and_record(mk_me, mk_opp, deck_me, deck_opp, label):
    """ローカル1試合を実行し、ReplayReviewer互換のgame dictへ(両サイド分)。
    相手側(ベンチマークbot)も監査対象=人間が1試合見れば相手の異常にも気付くため。"""
    me_bot = mk_me(); opp_bot = mk_opp()
    decisions = [[], []]
    step_i = [0]

    def mk_agent(bot, side):
        def agent(obs_dict):
            sel = bot.select(Observation.from_dict(obs_dict)) or [0]
            if obs_dict.get("current"):
                decisions[side].append((step_i[0], obs_dict, list(sel)))
            step_i[0] += 1
            return sel
        return agent

    run_match(mk_agent(me_bot, 0), mk_agent(opp_bot, 1), deck_me, deck_opp)
    return [{"ep": label, "my": 0, "decisions": decisions[0]},
            {"ep": f"{label}(相手bot)", "my": 1, "decisions": decisions[1]}]


def qa(games_per_matchup=5):
    dl = [int(x) for x in open("decks/deck.csv").read().split() if x.strip()]
    matchups = [
        ("mirror", "deck", "deck"),
        ("lucario", "ladder_lucario", "ladder_lucario"),
        ("arch", "ladder_archaludon", "ladder_archaludon"),
        ("dragapult", "dragapult", "dragapult"),
        ("alakazam", "alakazam", "alakazam"),
        ("grimmsnarl", "grimmsnarl", "meta_grimmsnarl"),
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
            games = play_and_record(
                lambda: R.DECK_BOTS["deck"](decklist=dl),
                lambda: R.DECK_BOTS[opp_key](decklist=od),
                dl, od, f"local-{tag}-{g_i}")
            n += 1
            for game in games:
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
