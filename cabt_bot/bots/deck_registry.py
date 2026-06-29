"""デッキ(csv stem) → 専用 bot の対応表。総当たり評価ループで使う。

各デッキに専用 bot を割り当てる。Starmie 系は DeckBot プランをここで定義。
"""
from __future__ import annotations

from .deck_bot import DeckBot, DeckPlan
from .dragapult_bot import DragapultBot
from .iwapa_bot import IwapaBot
from .lopunny_bot import MegaLopunnyBot
from .lucario_bot import MegaLucarioBot
from .yukinooh_bot import MegaYukinoohBot

# Mega Starmie（Nebula 主軸）
STARMIE_PLAN = DeckPlan(
    name="MegaStarmie",
    go_first=True,
    attackers=(1031, 1030),               # メガスターミーex / ヒトデマン
    key_cards=(1031, 1030),
    preferred_attacks=("Nebula Beam", "Jetting Blow"),
    energy_rules=((17, 1031), (3, 1031)),  # イグニ→メガ, 水→メガ
    play_priority={1030: 80, 666: 60},
    card_values={1031: 100, 17: 90, 1030: 84},
    lethal=True,
    volatile_energies=(17,),       # イグニはメガ(進化)の場・攻撃できる番のみ付与（浪費防止）
    heal_return_cards=(1229,),     # ミツルは負傷時のみ（無傷使用＝エネ全戻しで有害なため抑止）
    boss_cards=(1182,),            # ボスはKO(サイド)を生む時のみ＋引きずり出し対象もKO優先
    recover_cards=(1097,),         # 夜のタンカは回収価値がある時のみ（無駄打ち防止）
    switch_cards=(1123,),          # ポケモンいれかえは攻撃役を前に出す必要がある時のみ
    smart_take=True,               # ポケギア等のサポ取得を効果×盤面で選ぶ（展開/KO/手札立て直し）
)
# Mega Starmie（spread 主軸）
SPREAD_PLAN = DeckPlan(
    name="MegaStarmieSpread",
    go_first=True,
    attackers=(1031, 112),
    key_cards=(1031, 112),
    preferred_attacks=("Jetting Blow",),
    energy_rules=((7, 112), (3, 1031)),    # 悪→マシマシラ, 水→メガ
    play_priority={112: 84, 103: 76, 1030: 78},
    card_values={1031: 100, 112: 85, 104: 70},
    lethal=True,
    smart_gust=True,   # A/B(80戦) +0.027
    reposition=True,   # A/B(80戦) +0.069
)


class MegaStarmiePlanBot(DeckBot):
    plan = STARMIE_PLAN


class MegaStarmieSpreadPlanBot(DeckBot):
    plan = SPREAD_PLAN


# csv stem -> bot class（引数なしで生成できる）
DECK_BOTS: dict[str, type] = {
    "deck": MegaStarmiePlanBot,
    "mega_spread": MegaStarmieSpreadPlanBot,
    "dragapult": DragapultBot,
    "lopunny": MegaLopunnyBot,
    "megaruka": MegaLucarioBot,
    "iwapa": IwapaBot,
    "sample_deck": MegaYukinoohBot,
}
