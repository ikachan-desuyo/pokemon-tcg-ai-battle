"""cabt エンジンの列挙型（公式 cg/api.py に厳密に一致）。

値・名前は公式 SDK (cg.api) の定義に合わせている。エンジン本体 (cg/) は
再配布不可のためリポジトリには含めないが、これらの列挙はドキュメント化された
スキーマの再実装であり、bot ロジックをエンジン非依存でテストするために用いる。

注意: 公式コメントにある通り、コンペ期間中に Enum 要素が追加されうる。
未知の値は models 側で生の int のまま保持する。
"""

from __future__ import annotations

from enum import IntEnum


class AreaType(IntEnum):
    DECK = 1
    HAND = 2
    DISCARD = 3            # トラッシュ
    ACTIVE = 4            # バトル場
    BENCH = 5
    PRIZE = 6            # サイド
    STADIUM = 7
    ENERGY = 8
    TOOL = 9
    PRE_EVOLUTION = 10   # 場のポケモンの進化前
    PLAYER = 11
    LOOKING = 12         # 見ているカード


class EnergyType(IntEnum):
    COLORLESS = 0
    GRASS = 1
    FIRE = 2
    WATER = 3
    LIGHTNING = 4
    PSYCHIC = 5
    FIGHTING = 6
    DARKNESS = 7
    METAL = 8
    DRAGON = 9
    RAINBOW = 10        # 全タイプ
    TEAM_ROCKET = 11    # PSYCHIC かつ DARKNESS


class CardType(IntEnum):
    POKEMON = 0
    ITEM = 1
    TOOL = 2            # ポケモンのどうぐ
    SUPPORTER = 3
    STADIUM = 4
    BASIC_ENERGY = 5
    SPECIAL_ENERGY = 6


class SpecialConditionType(IntEnum):
    POISON = 0
    BURN = 1
    SLEEP = 2
    PARALYZE = 3
    CONFUSE = 4


class SelectType(IntEnum):
    MAIN = 0                    # OptionType: PLAY, ATTACH, EVOLVE, ABILITY, DISCARD, RETREAT, ATTACK, END
    CARD = 1                    # OptionType: CARD
    ATTACHED_CARD = 2           # OptionType: TOOL_CARD, ENERGY_CARD
    CARD_OR_ATTACHED_CARD = 3  # OptionType: CARD, TOOL_CARD, ENERGY_CARD
    ENERGY = 4                  # OptionType: ENERGY
    SKILL = 5                   # OptionType: SKILL
    ATTACK = 6                  # OptionType: ATTACK
    EVOLVE = 7                  # OptionType: EVOLVE
    COUNT = 8                   # OptionType: NUMBER
    YES_NO = 9                  # OptionType: YES, NO
    SPECIAL_CONDITION = 10      # OptionType: SPECIAL_CONDITION


class OptionType(IntEnum):
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


class SelectContext(IntEnum):
    """何を選んでいるかの文脈（公式 48 種）。"""

    MAIN = 0
    SETUP_ACTIVE_POKEMON = 1
    SETUP_BENCH_POKEMON = 2
    SWITCH = 3
    TO_ACTIVE = 4
    TO_BENCH = 5
    TO_FIELD = 6
    TO_HAND = 7
    DISCARD = 8
    TO_DECK = 9
    TO_DECK_BOTTOM = 10
    TO_PRIZE = 11
    NOT_MOVE = 12
    DAMAGE_COUNTER = 13
    DAMAGE_COUNTER_ANY = 14
    DAMAGE = 15
    REMOVE_DAMAGE_COUNTER = 16
    HEAL = 17
    EVOLVES_FROM = 18
    EVOLVES_TO = 19
    DEVOLVE = 20
    ATTACH_FROM = 21
    ATTACH_TO = 22
    DETACH_FROM = 23
    LOOK = 24
    EFFECT_TARGET = 25
    DISCARD_ENERGY_CARD = 26
    DISCARD_TOOL_CARD = 27
    SWITCH_ENERGY_CARD = 28
    DISCARD_CARD_OR_ATTACHED_CARD = 29
    DISCARD_ENERGY = 30
    TO_HAND_ENERGY = 31
    TO_DECK_ENERGY = 32
    SWITCH_ENERGY = 33
    SKILL_ORDER = 34
    ATTACK = 35
    DISABLE_ATTACK = 36
    EVOLVE = 37
    DRAW_COUNT = 38
    DAMAGE_COUNTER_COUNT = 39
    REMOVE_DAMAGE_COUNTER_COUNT = 40
    IS_FIRST = 41
    MULLIGAN = 42
    ACTIVATE = 43
    FIRST_EFFECT = 44
    MORE_DEVOLVE = 45
    COIN_HEAD = 46
    AFFECT_SPECIAL_CONDITION = 47
    RECOVER_SPECIAL_CONDITION = 48


class LogType(IntEnum):
    """対戦ログの種別（公式 24 種）。"""

    SHUFFLE = 0
    HAS_BASIC_POKEMON = 1
    TURN_START = 2
    TURN_END = 3
    DRAW = 4
    DRAW_REVERSE = 5
    MOVE_CARD = 6
    MOVE_CARD_REVERSE = 7
    SWITCH = 8
    CHANGE = 9
    PLAY = 10
    ATTACH = 11
    EVOLVE = 12
    DEVOLVE = 13
    MOVE_ATTACHED = 14
    ATTACK = 15
    HP_CHANGE = 16
    POISONED = 17
    BURNED = 18
    ASLEEP = 19
    PARALYZED = 20
    CONFUSED = 21
    COIN = 22
    RESULT = 23
