"""Mega Lopunny ex 専用 bot。

回し方の方針: ミミロル→メガミミロップex を立て、ベンチからバトル場に出して
しっぷうづき(60+170=230)を狙う／スパイクホッパー(160,効果無視)で殴る。
ノココッチ・ケーシィでドローを回す。エネは無色なので攻撃役へ集約。
"""
from .deck_bot import DeckBot, DeckPlan

PLAN = DeckPlan(
    name="MegaLopunny",
    go_first=True,
    attackers=(849, 758),                 # メガミミロップex / ミミロル
    key_cards=(849, 758),
    preferred_attacks=(),                 # 既定: 最大ダメージ（後で「しっぷうづき」優先を検討）
    energy_rules=((None, 849),),          # 任意→メガミミロップex
    play_priority={758: 82, 66: 80, 109: 78},  # ミミロル/ノココッチ/ケーシィ
    card_values={849: 100, 758: 80},
    lethal=True,
    smart_gust=True,   # KOしやすい相手を引きずり出す（A/B +0.050）
    reposition=True,   # 攻撃役を前に出してから殴る（A/B(80戦) +0.038）
    boss_cards=(1182,),            # ボスはKO時のみ
    recover_cards=(1097,),         # 夜タンカは回収価値がある時のみ
    switch_cards=(1123,),          # いれかえは攻撃役を前に出す時のみ
    smart_take=True,               # ポケギアの取得を効果×盤面で選ぶ（共通ノブ A/B +0.038）
)


class MegaLopunnyBot(DeckBot):
    plan = PLAN
