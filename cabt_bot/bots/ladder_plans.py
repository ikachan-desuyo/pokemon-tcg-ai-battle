"""実ラダー復元ベンチ用の手書き DeckPlan 群(Benchmark Phase, 2026-07)。

目的: ベンチマーク相手を UniversalBot(自動導出=ノブ全OFF) から
「そのデッキの勝ち方」を知る PLAN 版へ強化し、評価環境の天井を上げる。
高勝率=相手bot改善余地、の解消(勝率はメガスターミーの強さと相手の弱さの合成)。

方針: デッキ固有ロジックはここ(PLAN)に、機構はエンジン(deck_bot.py)に汎用ノブとして。
各PLANの受け入れ基準: ①同デッキのUniversal版との直接対決で勝率55%+
②対メガスターミーbotの勝率が有意に上昇 ③QAゲートで相手側BLOCKINGゼロ。
"""
from __future__ import annotations

from .deck_bot import DeckBot, DeckPlan

# ==== Mega Lucario (実ラダー最多33戦・実勝率30%の最重要対面) ====
# 勝ち筋: リオル→メガルカリオex(340)。Mega Brave 270 は次番使用不可ロックのため
# Aura Jab 130(トラッシュからFエネ3枚をベンチへ加速)と自然交互になる=2体目の育成が回る。
# ルナトーン(ルナサイクル=手札のFを捨てて3ドロー)がトラッシュ燃料を作り、
# ハリテヤマ進化時のどすこいキャッチャー(ベンチ引きずり出し)が確定ボスとして機能する。
# 観測済みの弱点(精読R23-R30): リオルが単発置き→Boss+Jettingで土台狩りされ
# メガルカリオが立たない。土台の複数展開と即進化を最優先にする。
LADDER_LUCARIO_PLAN = DeckPlan(
    name="LadderLucario",
    go_first=True,
    attackers=(678, 674, 676),            # メガルカリオex / ハリテヤマ / ソルロック
    key_cards=(678, 677),
    preferred_attacks=(),                  # 既定=最大ダメージ(MB⇄AJは使用ロックで自然交互)
    energy_rules=((None, 678), (None, 674)),  # F→メガルカリオ最優先、次点ハリテヤマ
    play_priority={677: 86, 673: 78, 676: 74, 675: 74},  # リオル(土台)>マクノシタ>ソル/ルナ
    card_values={678: 100, 677: 85, 674: 72, 676: 62, 675: 62},
    lethal=True,
    reposition=True,
    hp_boost_tools={1159: 100},            # ヒーローマント(被KO圏→生存圏の反転)
    boss_cards=(1182,),                    # ボスはKO(サイド)を生む時のみ
    switch_cards=(1123,),                  # いれかえは攻撃役前進が必要な時のみ
    smart_take=True,                       # ダークボール/ポケパッド取得を盤面で選ぶ
    setup_wall=(673,),                     # 先攻T1はマクノシタ壁(土台リオルを晒さない)
    dup_play_caps={676: 1, 675: 1, 673: 2},  # ソル/ルナは各1体で特性条件充足。重ね置きはML再建枠の渋滞
)


class LadderLucarioBot(DeckBot):
    plan = LADDER_LUCARIO_PLAN
