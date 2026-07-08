"""Chandelureコントロール(実ラダー上位、episode 84544160 から採取 2026-07-08)。
上位1043点grimmに2連勝した実在コントロールデッキ。PLANはノブ最小主義(Universal infer)。
主役=Chandelure線(130)+Comfey。Hammer4/Eri2/Xerosic3の妨害+Gravity Gemstone。"""
from __future__ import annotations

import dataclasses as _dc
from pathlib import Path as _P

from ..bots.deck_bot import DeckBot
from ..bots.universal_bot import infer_plan as _infer

DECK_CSV = "decks/chandelure_control.csv"

_deck = [int(x) for x in (_P(__file__).resolve().parents[2] / DECK_CSV).read_text().split() if x.strip()]
PLAN = _dc.replace(_infer(_deck), name="ChandelureControl",
                   attackers=(98, 164, 343))  # infer漏れ: 主砲Chandelure(130)を追加


class Bot(DeckBot):
    plan = PLAN


THREAT = {"boss_count": 3, "max_line_damage": 130, "spread": 0, "bases": (164, 97, 343), "hand_disruption": 5}
