"""cabt エンジンの列挙型を Python 側にミラーしたもの。

値は公式 API ドキュメント (https://matsuoinstitute.github.io/cabt/api.html) の
定義に合わせている。エンジン側の更新で値が変わる可能性があるため、
ロジックでは可能な限り名前 (Enum メンバ) を使うこと。
"""

from __future__ import annotations

from enum import IntEnum


class SelectType(IntEnum):
    """エンジンがプレイヤーに要求する「選択の種類」。"""

    MAIN = 0                    # メインの行動メニュー
    CARD = 1                    # 手札・場のカード1枚を選ぶ
    ATTACHED_CARD = 2           # ポケモンに付いているカードを選ぶ
    CARD_OR_ATTACHED_CARD = 3  # カード or 付属カードを選ぶ
    ENERGY = 4                  # エネルギーを選ぶ
    SKILL = 5                   # ワザ/特性などスキルを選ぶ
    ATTACK = 6                  # ワザ(攻撃)を選ぶ
    EVOLVE = 7                  # 進化先を選ぶ
    COUNT = 8                   # 数値入力
    YES_NO = 9                  # はい/いいえ
    SPECIAL_CONDITION = 10      # 特殊状態の選択


class OptionType(IntEnum):
    """各選択肢 (Option) が表す行動の種別。"""

    NUMBER = 0
    YES = 1
    NO = 2
    CARD = 3
    TOOL_CARD = 4
    ENERGY_CARD = 5
    ENERGY = 6
    PLAY = 7
    ATTACH = 8
    EVOLVE = 9
    ABILITY = 10
    DISCARD = 11
    RETREAT = 12
    ATTACK = 13
    END = 14
    SKILL = 15
    SPECIAL_CONDITION = 16


class AreaType(IntEnum):
    """場の領域。

    注意: ドキュメントに数値の明示がないため暫定値。実エンジンの値が判明したら
    修正すること。Option 側では生の int も保持しているので、ロジックは
    `Option.area_raw` を併用しても良い。
    """

    ACTIVE = 0   # バトル場
    BENCH = 1    # ベンチ
    HAND = 2     # 手札
    DISCARD = 3  # トラッシュ
    DECK = 4     # 山札
    PRIZE = 5    # サイド


class SpecialConditionType(IntEnum):
    """特殊状態。AreaType 同様、数値は暫定。"""

    POISONED = 0
    BURNED = 1
    ASLEEP = 2
    PARALYZED = 3
    CONFUSED = 4
