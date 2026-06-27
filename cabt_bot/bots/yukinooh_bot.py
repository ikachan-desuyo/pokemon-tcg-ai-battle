"""Mega Yukinooh ex（メガユキノオーex / sample 由来）専用 bot。

回し方の方針: ユキカブリ→メガユキノオーex(HP350)を立て、水エネを攻撃役へ集約して
殴る。タンク性能を活かして打ち合う。
"""
from .deck_bot import DeckBot, DeckPlan

PLAN = DeckPlan(
    name="MegaYukinooh",
    go_first=False,
    attackers=(723, 722),                 # メガユキノオーex / ユキカブリ
    key_cards=(723, 722),
    preferred_attacks=(),
    energy_rules=((None, 723),),          # 水→メガユキノオーex
    play_priority={722: 82, 721: 76},     # ユキカブリ/カイオーガ
    card_values={723: 100, 722: 78, 721: 72},
)


class MegaYukinoohBot(DeckBot):
    plan = PLAN
