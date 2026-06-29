"""Mega Lucario ex 専用 bot（メガルカリオex）。

回し方の方針: リオル→メガルカリオex(HP340)を立て、はどうづき(130＋トラッシュから
闘エネ3枚をベンチに加速)／メガブレイブ(270)で殴る。ソルロック+ルナトーンでドロー、
ハリテヤマ進化時のどすこいキャッチャーで引きずり出し。エネは闘を攻撃役へ。
"""
from .deck_bot import DeckBot, DeckPlan

PLAN = DeckPlan(
    name="MegaLucario",
    go_first=True,
    attackers=(678, 333, 674, 676, 673),                 # メガルカリオex / リオル
    key_cards=(678, 333),
    preferred_attacks=(),                 # 既定: 最大ダメージ（メガブレイブ等）
    energy_rules=((None, 678),),          # 闘→メガルカリオex
    play_priority={333: 82, 675: 78, 676: 78, 673: 70},  # リオル/ルナトーン/ソルロック/マクノシタ
    card_values={678: 100, 333: 78, 674: 70},
    reposition=True,   # 攻撃役を前に出してから殴る（A/B(80戦) +0.035）
)


class MegaLucarioBot(DeckBot):
    plan = PLAN
