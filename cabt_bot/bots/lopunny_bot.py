"""Mega Lopunny ex 専用 bot。

回し方の方針: ミミロル→メガミミロップex を立て、ベンチからバトル場に出して
しっぷうづき(60+170=230)を狙う／スパイクホッパー(160,効果無視)で殴る。
ノココッチ・ケーシィでドローを回す。エネは無色なので攻撃役へ集約。
"""
from .deck_bot import DeckBot, DeckPlan

PLAN = DeckPlan(
    name="MegaLopunny",
    go_first=False,
    attackers=(849, 758),                 # メガミミロップex / ミミロル
    key_cards=(849, 758),
    preferred_attacks=(),                 # 既定: 最大ダメージ（後で「しっぷうづき」優先を検討）
    energy_rules=((None, 849),),          # 任意→メガミミロップex
    play_priority={758: 82, 66: 80, 109: 78},  # ミミロル/ノココッチ/ケーシィ
    card_values={849: 100, 758: 80},
)


class MegaLopunnyBot(DeckBot):
    plan = PLAN
